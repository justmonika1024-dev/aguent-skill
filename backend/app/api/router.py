from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..workflow.context import AdmissionMode, RunMode, RunState
from ..workflow.engine import WorkflowConflict, WorkflowEngine
from ..workflow.events import Command

router = APIRouter(prefix="/api/v1")
_engine = WorkflowEngine()


def get_engine() -> WorkflowEngine:
    return _engine


def set_engine(engine: WorkflowEngine) -> None:
    """Replace the process-local engine (used by integration tests/startup wiring)."""
    global _engine
    _engine = engine


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
    try:
        return _engine.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.get("/runs/{run_id}/branches")
async def get_branches(run_id: str) -> list[dict[str, Any]]:
    try:
        return [{"id": k, **v, "is_active": k == _engine.contexts[run_id].active_branch_id}
                for k, v in _engine.contexts[run_id].branches.items()]
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.get("/runs/{run_id}/nodes")
async def get_nodes(run_id: str) -> list[dict[str, Any]]:
    try:
        c = _engine.contexts[run_id]
        return [{"node_key": k, "output": v} for k, v in c.node_outputs.items()]
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.get("/runs/{run_id}/nodes/{execution_id}")
async def get_node(run_id: str, execution_id: str) -> dict[str, Any]:
    try:
        c = _engine.contexts[run_id]
        return {"execution_id": execution_id, "output": c.node_outputs.get(execution_id)}
    except KeyError:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})


@router.post("/runs/{run_id}/commands")
async def command(run_id: str, body: CommandRequest) -> dict[str, Any]:
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
async def submit_evaluation(run_id: str, body: dict[str, Any]) -> dict[str, Any]:
    c = _engine.contexts.get(run_id)
    if c is None:
        raise HTTPException(404, detail={"code": "RUN_NOT_FOUND"})
    expected = body.pop("expected_run_version", None)
    branch = body.pop("branch_id", c.active_branch_id)
    if branch != c.active_branch_id or expected != c.run_version:
        raise HTTPException(409, detail={"code": "RUN_VERSION_CONFLICT"})
    return await _engine.command(run_id, Command(type="EVALUATION_SUBMITTED", expected_run_version=expected,
                                                 payload=body))


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
    return [c.snapshot() for c in _engine.contexts.values()]


@router.get("/memes")
async def list_memes() -> list[dict[str, Any]]:
    return []


@router.get("/memes/{meme_id}")
async def get_meme(meme_id: str) -> dict[str, Any]:
    raise HTTPException(404, detail={"code": "MEME_NOT_FOUND"})


@router.post("/memes/{meme_id}/unpublish")
async def unpublish_meme(meme_id: str) -> dict[str, Any]:
    raise HTTPException(404, detail={"code": "MEME_NOT_FOUND"})


@router.post("/memes/{meme_id}/restore")
async def restore_meme(meme_id: str) -> dict[str, Any]:
    raise HTTPException(404, detail={"code": "MEME_NOT_FOUND"})


@router.get("/strategies")
async def list_strategies() -> list[dict[str, Any]]:
    return []


@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str) -> dict[str, Any]:
    raise HTTPException(404, detail={"code": "STRATEGY_NOT_FOUND"})


@router.post("/strategies/{strategy_id}/activate")
async def activate_strategy(strategy_id: str) -> dict[str, Any]:
    if _engine.active is not None:
        raise HTTPException(409, detail={"code": "ACTIVE_RUN_EXISTS"})
    raise HTTPException(404, detail={"code": "STRATEGY_NOT_FOUND"})
