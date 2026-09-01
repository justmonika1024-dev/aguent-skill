from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..contracts.evaluation import HumanEvaluationRequest
from ..workflow.context import AdmissionMode, RunMode, RunState
from ..workflow.engine import WorkflowConflict, WorkflowEngine
from ..workflow.events import Command

router = APIRouter(prefix="/api/v1")
def _build_engine_from_env() -> WorkflowEngine:
    """Construct the process-local engine from startup environment variables."""
    from os import getenv

    from ..db.persistence import SQLiteRepository
    repository = SQLiteRepository(getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/agugent.db"))
    if getenv("LLM_PROVIDER", "fake") == "fake" and getenv("SEARCH_PROVIDER", "fake") == "fake":
        return WorkflowEngine(repository=repository)
    from ..providers.exa import ExaSearchProvider
    from ..providers.fake import FakeLLMProvider, FakeSearchProvider
    from ..providers.llm import DeepSeekChatProvider, OpenAIResponsesProvider
    llm_provider = getenv("LLM_PROVIDER", "fake")
    llm: Any
    if llm_provider == "deepseek":
        llm = DeepSeekChatProvider(getenv("LLM_API_KEY", ""), getenv("LLM_MODEL", "deepseek-chat"), getenv("LLM_BASE_URL", "https://api.deepseek.com"))
    elif llm_provider == "openai":
        llm = OpenAIResponsesProvider(getenv("LLM_API_KEY", ""), getenv("LLM_MODEL", "gpt-4o-mini"), getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    else:
        llm = FakeLLMProvider()
    search = (ExaSearchProvider(getenv("EXA_API_KEY", ""), getenv("EXA_BASE_URL", "https://api.exa.ai"))
              if getenv("SEARCH_PROVIDER", "fake") == "exa" else FakeSearchProvider())
    from ..workflow.real_registry import build_real_registry
    return WorkflowEngine(registry=build_real_registry(llm=llm, search=search, repository=repository), repository=repository)


_engine = _build_engine_from_env()


def get_engine() -> WorkflowEngine:
    return _engine


def set_engine(engine: WorkflowEngine) -> None:
    """Replace the process-local engine (used by integration tests/startup wiring)."""
    global _engine
    _engine = engine


_MODULAR_EVALUATION_KEYS = (
    "original_search_plan",
    "selected_original_meme",
    "variant_search_plan",
    "variant_search_results",
    "template_extraction",
)
_EVALUATION_FEEDBACK_KEY = "_evaluation_feedback"
_EVALUATION_FEEDBACK_SCHEMA_VERSION = 1


def _automatic_admission_decision(context: Any) -> str | None:
    for artifacts in (context.active_artifacts, context.node_outputs):
        value = artifacts.get("N17", {})
        if isinstance(value, dict) and isinstance(value.get("llm"), dict):
            value = value["llm"]
        if isinstance(value, dict):
            decision = value.get("admission_decision") or value.get("decision")
            if decision in {"ADMIT", "NOT_ADMIT"}:
                return str(decision)
    return None


def _n16_safety_status(context: Any) -> str:
    for artifacts in (context.active_artifacts, context.node_outputs):
        value = artifacts.get("N16")
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(value.get("llm"), dict):
            value = value["llm"]
        if not isinstance(value, dict):
            return "UNCERTAIN"
        safety: Any = value.get("safety", value.get("content_safety"))
        if isinstance(safety, dict):
            safety = safety.get("status", safety.get("result"))
        status = str(safety or "UNCERTAIN").strip().upper()
        return status if status in {"PASS", "REJECT", "UNCERTAIN"} else "UNCERTAIN"
    return "UNCERTAIN"


def _resolve_admission(context: Any, admission: dict[str, Any]) -> str:
    decision = admission.get("decision")
    override = admission.get("override")
    if context.admission_mode is AdmissionMode.HUMAN:
        if decision not in {"ADMIT", "NOT_ADMIT"} or override is not None:
            raise HTTPException(422, detail={
                "code": "INVALID_ADMISSION",
                "message": "HUMAN admission requires decision and forbids override",
            })
        resolved = str(decision)
    else:
        if decision is not None or override not in {
            "KEEP", "OVERRIDE_TO_ADMIT", "OVERRIDE_TO_NOT_ADMIT",
        }:
            raise HTTPException(422, detail={
                "code": "INVALID_ADMISSION",
                "message": "AUTO admission requires override and forbids decision",
            })
        if override == "OVERRIDE_TO_ADMIT":
            resolved = "ADMIT"
        elif override == "OVERRIDE_TO_NOT_ADMIT":
            resolved = "NOT_ADMIT"
        else:
            automatic_decision = _automatic_admission_decision(context)
            if automatic_decision is None:
                raise HTTPException(422, detail={
                    "code": "INVALID_ADMISSION",
                    "message": "AUTO KEEP requires an N17 admission decision",
                })
            resolved = automatic_decision
    if resolved == "ADMIT":
        safety = _n16_safety_status(context)
        if safety != "PASS":
            raise HTTPException(422, detail={
                "code": "CONTENT_SAFETY_NOT_PASS",
                "message": f"内容安全结果为{safety}，仅PASS允许入库",
            })
    return resolved


def _evaluation_record(row: Any) -> dict[str, Any]:
    processing_chain = row.processing_chain_scores_json or {}
    common = {
        "evaluation_id": row.id,
        "final_result": row.final_result_scores_json,
        "main_problem_nodes": row.main_problem_nodes_json,
        "admission_decision": row.admission_decision,
    }
    if all(key in processing_chain for key in _MODULAR_EVALUATION_KEYS):
        feedback = processing_chain.get(_EVALUATION_FEEDBACK_KEY, {})
        if not (isinstance(feedback, dict)
                and feedback.get("schema_version") == _EVALUATION_FEEDBACK_SCHEMA_VERSION):
            feedback = {}
        return {
            **common,
            **{key: processing_chain[key] for key in _MODULAR_EVALUATION_KEYS},
            "candidate_generation": {
                "overall": row.candidate_set_scores_json,
                "candidates": row.candidate_scores_json,
            },
            "admission": feedback.get("admission", {
                "decision": row.admission_decision,
                "override": None,
                "reason": "",
            }),
            "overall_comment": feedback.get("overall_comment", ""),
        }
    return {
        **common,
        "processing_chain": row.processing_chain_scores_json,
        "candidate_set": row.candidate_set_scores_json,
        "candidates": row.candidate_scores_json,
    }


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: RunMode
    admission_mode: AdmissionMode
    seed_text: str | None = None
    continuous_enabled: bool = False


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    type: str
    expected_run_version: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeParameters(BaseModel):
    model_config = ConfigDict(extra="allow")
    values: dict[str, Any] = Field(default_factory=dict)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/config")
async def system_config() -> dict[str, Any]:
    # Never expose secrets: only presence is returned.
    from os import getenv
    return {"llm_provider": getenv("LLM_PROVIDER", "fake"),
            "llm_model": getenv("LLM_MODEL", "fake"),
            "api_key_configured": bool(getenv("LLM_API_KEY")),
            "search_api_key_configured": bool(getenv("EXA_API_KEY"))}


@router.get("/system/runtime-parameters")
async def runtime_parameters() -> dict[str, Any]:
    return {"values": {"search_plan_budget": 2, "discovery_directions": 5,
                        "candidate_batches": 3, "llm_attempts": 3}}


@router.patch("/system/runtime-parameters")
async def patch_runtime_parameters(body: RuntimeParameters) -> dict[str, Any]:
    return {"values": body.values}


@router.post("/system/connection-tests/llm")
async def connection_test_llm() -> dict[str, Any]:
    """Run a provider connection probe without exposing credentials."""
    from os import getenv
    provider = getenv("LLM_PROVIDER", "fake")
    if provider == "fake":
        return {"ok": True, "provider": "fake", "protocol": "fake"}
    p: Any
    if provider == "deepseek":
        from ..providers.llm import DeepSeekChatProvider
        p = DeepSeekChatProvider(getenv("LLM_API_KEY", ""), getenv("LLM_MODEL", "deepseek-chat"), getenv("LLM_BASE_URL", "https://api.deepseek.com"))
    else:
        from ..providers.llm import OpenAIResponsesProvider
        p = OpenAIResponsesProvider(getenv("LLM_API_KEY", ""), getenv("LLM_MODEL", "gpt-5"), getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    return await p.connection_test()


@router.post("/system/connection-tests/search")
async def connection_test_search() -> dict[str, Any]:
    from os import getenv
    if getenv("SEARCH_PROVIDER", "fake") == "fake":
        return {"ok": True, "provider": "fake", "protocol": "search"}
    from ..providers.exa import ExaSearchProvider
    p = ExaSearchProvider(getenv("EXA_API_KEY", ""), getenv("EXA_BASE_URL", "https://api.exa.ai"))
    return await p.connection_test()


@router.post("/runs", status_code=201)
async def create_run(body: RunCreate) -> dict[str, Any]:
    try:
        ctx = await _engine.start_run(mode=body.mode, admission_mode=body.admission_mode,
                                      seed_text=body.seed_text, continuous_enabled=body.continuous_enabled)
    except WorkflowConflict as exc:
        raise HTTPException(409, detail={"code": "ACTIVE_RUN_EXISTS", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))
    return ctx.snapshot()


@router.get("/runs/current")
async def current_run() -> dict[str, Any]:
    ctx = _engine.active
    return {"run": None if ctx is None else ctx.snapshot(),
            "engine_state": RunState.WAITING_START.value if ctx is None else ctx.current_state.value}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    if run_id in _engine.contexts:
        return _engine.snapshot(run_id)
    repository = getattr(_engine, "repository", None)
    if repository:
        from ..db.models import RunRecord
        async with repository.session() as s:
            row = await s.get(RunRecord, run_id)
            if row:
                return {"run_id": row.id, "mode": row.mode, "state": row.status, "seed_text": row.seed_text,
                        "admission_decision": row.admission_decision, "formal_meme_id": row.formal_meme_id}
    raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.get("/runs/{run_id}/branches")
async def get_branches(run_id: str) -> list[dict[str, Any]]:
    try:
        return [{"id": k, **v, "is_active": k == _engine.contexts[run_id].active_branch_id}
                for k, v in _engine.contexts[run_id].branches.items()]
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.get("/runs/{run_id}/record")
async def complete_run_record(run_id: str) -> dict[str, Any]:
    """Return the complete persisted audit record, independent of process memory."""
    repository = getattr(_engine, "repository", None)
    if repository is None:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    from sqlalchemy import select

    from ..db.models import (
        RunAPICall,
        RunBranch,
        RunEvent,
        RunHumanEvaluation,
        RunNodeExecution,
        RunRecord,
        RunSourceEvidence,
    )
    async with repository.session() as session:
        run = await session.get(RunRecord, run_id)
        if run is None:
            raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
        branches = (await session.execute(select(RunBranch).where(RunBranch.run_id == run_id)
                                          .order_by(RunBranch.created_at))).scalars().all()
        nodes = (await session.execute(select(RunNodeExecution).where(RunNodeExecution.run_id == run_id)
                                       .order_by(RunNodeExecution.started_at,
                                                 RunNodeExecution.id))).scalars().all()
        sources = (await session.execute(select(RunSourceEvidence).where(RunSourceEvidence.run_id == run_id)
                                         .order_by(RunSourceEvidence.retrieved_at))).scalars().all()
        evaluations = (await session.execute(select(RunHumanEvaluation).where(RunHumanEvaluation.run_id == run_id)
                                             .order_by(RunHumanEvaluation.submitted_at))).scalars().all()
        events = (await session.execute(select(RunEvent).where(RunEvent.run_id == run_id)
                                        .order_by(RunEvent.sequence))).scalars().all()
        api_calls = (await session.execute(select(RunAPICall).where(RunAPICall.run_id == run_id)
                                           .order_by(RunAPICall.created_at))).scalars().all()
    return {
        "run": {"run_id": run.id, "mode": run.mode, "state": run.status, "seed_text": run.seed_text,
                "admission_mode": run.admission_mode, "admission_decision": run.admission_decision,
                "active_branch_id": run.active_branch_id, "formal_meme_id": run.formal_meme_id,
                "started_at": run.started_at.isoformat(), "ended_at": run.ended_at.isoformat() if run.ended_at else None},
        "branches": [{"branch_id": row.id, "parent_branch_id": row.parent_branch_id,
                      "forked_from_execution_id": row.forked_from_execution_id,
                      "fork_reason": row.fork_reason, "is_final_active": row.is_final_active} for row in branches],
        "nodes": [{"execution_id": row.id, "execution_order": execution_order,
                   "branch_id": row.branch_id, "node_key": row.node_key,
                   "attempt_no": row.attempt_no, "status": row.status, "input": row.input_json,
                   "output": row.output_json, "error_code": row.error_code,
                   "error_message": row.error_message,
                   "started_at": row.started_at.isoformat(),
                   "ended_at": row.ended_at.isoformat() if row.ended_at else None}
                  for execution_order, row in enumerate(nodes)],
        "sources": [{"evidence_id": row.id, "node_execution_id": row.node_execution_id,
                     "source_id": row.source_id, "provider": row.provider, "title": row.title,
                     "url": row.url, "canonical_url": row.canonical_url, "text": row.text,
                     "evidence_type": row.evidence_type, "content_status": row.content_status} for row in sources],
        "evaluations": [_evaluation_record(row) for row in evaluations],
        "events": [{"sequence": row.sequence, "event_type": row.event_type, "state": row.state,
                    "branch_id": row.branch_id, "payload": row.payload_json,
                    "occurred_at": row.occurred_at.isoformat()} for row in events],
        "api_calls": [{"call_id": row.id, "node_key": row.node_key, "api_type": row.api_type,
                       "provider": row.provider, "model": row.model,
                       "provider_request_id": row.provider_request_id,
                       "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                       "total_tokens": row.total_tokens,
                       "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
                       "latency_ms": row.latency_ms, "status": row.status} for row in api_calls],
    }


@router.get("/runs/{run_id}/nodes")
async def get_nodes(run_id: str) -> list[dict[str, Any]]:
    if run_id in _engine.contexts:
        c = _engine.contexts[run_id]
        return [{"node_key": k, "output": v} for k, v in c.node_outputs.items()]
    repository = getattr(_engine, "repository", None)
    if repository:
        from sqlalchemy import select

        from ..db.models import RunNodeExecution
        async with repository.session() as s:
            rows = (await s.execute(select(RunNodeExecution).where(RunNodeExecution.run_id == run_id)
                                    .order_by(RunNodeExecution.started_at))).scalars().all()
            if rows: return [{"execution_id": r.id, "node_key": r.node_key, "attempt_no": r.attempt_no,
                              "status": r.status, "output": r.output_json} for r in rows]
    raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.get("/runs/{run_id}/sources")
async def get_run_sources(run_id: str) -> list[dict[str, Any]]:
    repository = getattr(_engine, "repository", None)
    if repository:
        from sqlalchemy import select

        from ..db.models import RunSourceEvidence
        async with repository.session() as s:
            rows = (await s.execute(select(RunSourceEvidence).where(RunSourceEvidence.run_id == run_id))).scalars().all()
            return [{"source_id": r.source_id, "title": r.title, "url": r.url, "text": r.text,
                     "evidence_type": r.evidence_type, "content_status": r.content_status} for r in rows]
    return []


@router.get("/runs/{run_id}/nodes/{execution_id}")
async def get_node(run_id: str, execution_id: str) -> dict[str, Any]:
    try:
        c = _engine.contexts[run_id]
        return {"execution_id": execution_id, "output": c.node_outputs.get(execution_id)}
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.post("/runs/{run_id}/commands")
async def command(run_id: str, body: CommandRequest) -> dict[str, Any]:
    if body.type == "EVALUATION_SUBMITTED":
        raise HTTPException(422, detail={
            "code": "COMMAND_TYPE_NOT_ALLOWED",
            "message": (
                "EVALUATION_SUBMITTED must be submitted via "
                f"/runs/{run_id}/evaluation"
            ),
        })
    try:
        return await _engine.command(run_id, Command(type=body.type, command_id=str(body.command_id),
                                                     expected_run_version=body.expected_run_version,
                                                     payload=body.payload))
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    except WorkflowConflict as exc:
        raise HTTPException(409, detail={"code": str(exc)})
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))


@router.post("/runs/{run_id}/evaluation")
async def submit_evaluation(run_id: str, body: HumanEvaluationRequest) -> dict[str, Any]:
    c = _engine.contexts.get(run_id)
    if c is None:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    payload = body.model_dump()
    expected = payload.pop("expected_run_version")
    branch = payload.pop("branch_id")
    if branch != c.active_branch_id or expected != c.run_version:
        raise HTTPException(409, detail={"code": "RUN_VERSION_CONFLICT"})
    payload["admission_decision"] = _resolve_admission(c, payload["admission"])
    try:
        return await _engine.submit_evaluation(
            run_id,
            payload,
            expected_run_version=expected,
            branch_id=branch,
        )
    except WorkflowConflict as exc:
        raise HTTPException(409, detail={"code": str(exc)})


@router.get("/runs/{run_id}/evaluation-form")
async def evaluation_form(run_id: str) -> dict[str, Any]:
    if run_id not in _engine.contexts:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    return {"run_id": run_id, "branch_id": _engine.contexts[run_id].active_branch_id,
            "state": _engine.contexts[run_id].current_state.value,
            "candidate_ids": ["C1", "C2", "C3", "C4", "C5"]}


async def _event_stream(run_id: str, since: int) -> AsyncIterator[str]:
    bus = _engine.buses[run_id]
    batch, reset = bus.since(since)
    if reset:
        yield "event: stream.reset\ndata: {\"reason\":\"buffer_exceeded\"}\n\n"
    for event in batch:
        yield event.sse()
    cursor = batch[-1].sequence if batch else since
    while True:
        await asyncio.sleep(15)
        fresh, _ = bus.since(cursor)
        if fresh:
            for event in fresh:
                cursor = event.sequence
                yield event.sse()
        else:
            yield ": heartbeat\nevent: heartbeat\ndata: {}\n\n"


@router.get("/runs/{run_id}/events")
async def events(run_id: str, last_event_id: int = Query(0, alias="lastEventId"),
                 last_event_id_header: str | None = Header(None, alias="Last-Event-ID")) -> StreamingResponse:
    if run_id not in _engine.contexts:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    if last_event_id_header:
        try:
            last_event_id = int(last_event_id_header)
        except ValueError:
            last_event_id = 0
    return StreamingResponse(_event_stream(run_id, last_event_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/runs")
async def list_runs() -> list[dict[str, Any]]:
    repository = getattr(_engine, "repository", None)
    if repository is None:
        return [c.snapshot() for c in _engine.contexts.values()]
    from sqlalchemy import select

    from ..db.models import RunRecord
    async with repository.session() as s:
        rows = (await s.execute(select(RunRecord).order_by(RunRecord.created_at.desc()))).scalars().all()
        return [{"run_id": r.id, "mode": r.mode, "state": r.status, "seed_text": r.seed_text,
                 "admission_mode": r.admission_mode, "continuous_enabled": r.continuous_enabled,
                 "active_branch_id": r.active_branch_id, "admission_decision": r.admission_decision,
                 "formal_meme_id": r.formal_meme_id} for r in rows]

@router.get("/usage")
async def usage_total() -> dict[str, Any]:
    repository = getattr(_engine, "repository", None)
    if repository is None:
        return {"run_id": None, "calls": 0, "llm_calls": 0, "search_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0, "latency_ms": 0}
    from ..services.usage import UsageService
    return await UsageService(repository).total()

@router.get("/runs/{run_id}/usage")
async def usage_for_run(run_id: str) -> dict[str, Any]:
    repository = getattr(_engine, "repository", None)
    if repository is None:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    from ..db.models import RunRecord
    async with repository.session() as session:
        if await session.get(RunRecord, run_id) is None:
            raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    from ..services.usage import UsageService
    return await UsageService(repository).for_run(run_id)


@router.get("/memes")
async def list_memes() -> list[dict[str, Any]]:
    repository = getattr(_engine, "repository", None)
    if repository is None: return []
    from sqlalchemy import select

    from ..db.models import MemeRecord
    async with repository.session() as s:
        rows = (await s.execute(select(MemeRecord).order_by(MemeRecord.created_at.desc()))).scalars().all()
        return [{"id": r.id, "title": r.title, "original_meme_text": r.original_meme_text,
                 "canonical_template_text": r.canonical_template_text, "final_agu_text": r.final_agu_text,
                 "status": r.status, "source_run_id": r.source_run_id} for r in rows]


@router.get("/memes/{meme_id}")
async def get_meme(meme_id: str) -> dict[str, Any]:
    repository = getattr(_engine, "repository", None)
    if repository:
        from sqlalchemy import select

        from ..db.models import MemeRecord, MemeSource
        async with repository.session() as s:
            row = await s.get(MemeRecord, meme_id)
            if row:
                sources = (await s.execute(select(MemeSource).where(MemeSource.meme_id == meme_id)
                                           .order_by(MemeSource.sort_order))).scalars().all()
                return {"id": row.id, "title": row.title, "original_meme_text": row.original_meme_text,
                        "canonical_template_text": row.canonical_template_text, "final_agu_text": row.final_agu_text,
                        "status": row.status, "source_run_id": row.source_run_id,
                        "sources": [{"role": x.source_role, "source_id": x.source_id, "url": x.url,
                                     "evidence_quote": x.evidence_quote} for x in sources]}
    raise HTTPException(404, detail={"code": "MEME_NOT_FOUND"})


@router.post("/memes/{meme_id}/unpublish")
async def unpublish_meme(meme_id: str) -> dict[str, Any]:
    raise HTTPException(404, detail={"code": "MEME_NOT_FOUND"})


@router.post("/memes/{meme_id}/restore")
async def restore_meme(meme_id: str) -> dict[str, Any]:
    raise HTTPException(404, detail={"code": "MEME_NOT_FOUND"})


@router.get("/strategies")
async def list_strategies() -> list[dict[str, Any]]:
    repository = getattr(_engine, "repository", None)
    if repository is None:
        return []
    await repository.ensure_active_strategy()
    from sqlalchemy import select

    from ..db.models import RunStrategyState, RunStrategyVersion
    async with repository.session() as session:
        state = await session.get(RunStrategyState, 1)
        versions = (await session.execute(
            select(RunStrategyVersion).order_by(RunStrategyVersion.version_number)
        )).scalars().all()
    active_id = state.active_strategy_version_id if state else None
    return [{
        "strategy_id": version.id,
        "version_number": version.version_number,
        "parent_version_id": version.parent_version_id,
        "source_run_id": version.source_run_id,
        "source_evaluation_id": version.source_evaluation_id,
        "change_summary": version.change_summary,
        "created_at": version.created_at.isoformat(),
        "is_active": version.id == active_id,
    } for version in versions]


@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str) -> dict[str, Any]:
    repository = getattr(_engine, "repository", None)
    if repository is None:
        raise HTTPException(404, detail={"code": "STRATEGY_NOT_FOUND"})
    await repository.init()
    from sqlalchemy import select

    from ..db.models import RunStrategyPatch, RunStrategyState, RunStrategyVersion
    async with repository.session() as session:
        version = await session.get(RunStrategyVersion, strategy_id)
        if version is None:
            raise HTTPException(404, detail={"code": "STRATEGY_NOT_FOUND"})
        state = await session.get(RunStrategyState, 1)
        patch = await session.scalar(select(RunStrategyPatch).where(
            RunStrategyPatch.after_version_id == strategy_id
        ))
    return {
        "strategy_id": version.id,
        "version_number": version.version_number,
        "parent_version_id": version.parent_version_id,
        "strategy": version.strategy_json,
        "source_run_id": version.source_run_id,
        "source_evaluation_id": version.source_evaluation_id,
        "change_summary": version.change_summary,
        "created_at": version.created_at.isoformat(),
        "is_active": bool(state and state.active_strategy_version_id == version.id),
        "patch_id": patch.id if patch else None,
        "feedback_summary": patch.feedback_summary if patch else "",
        "affected_nodes": patch.affected_nodes_json if patch else [],
        "patch_operations": patch.patch_operations_json if patch else [],
        "score_gaps": patch.score_gaps_json if patch else {},
        "next_round_hypotheses": patch.next_round_hypotheses_json if patch else [],
    }


@router.post("/strategies/{strategy_id}/activate")
async def activate_strategy(strategy_id: str) -> dict[str, Any]:
    try:
        await _engine.activate_strategy(strategy_id)
    except WorkflowConflict as exc:
        raise HTTPException(409, detail={"code": str(exc)})
    except KeyError:
        raise HTTPException(404, detail={"code": "STRATEGY_NOT_FOUND"})
    return {"strategy_id": strategy_id, "is_active": True}
