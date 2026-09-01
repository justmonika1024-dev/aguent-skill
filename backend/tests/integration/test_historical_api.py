import asyncio
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import (
    MemeRecord,
    RunHumanEvaluation,
    RunNodeExecution,
    RunRecord,
    RunStrategyPatch,
)
from app.db.persistence import SQLiteRepository
from app.main import app
from app.providers.fake import FakeLLMProvider, FakeSearchProvider
from app.workflow.context import AdmissionMode, RunContext, RunMode, RunState
from app.workflow.engine import WorkflowEngine
from app.workflow.events import EventBus
from app.workflow.real_registry import build_real_registry


def automatic_admission_artifacts(
    automatic_decision: str, *, safety: str | None = "PASS",
) -> dict:
    accuracy = 5 if automatic_decision == "ADMIT" else 3
    selected_score = {
        "candidate_id": "C1",
        "fluency": 8,
        "recognition": 9,
        "agu_fit": 9,
        "humor": 7,
        "rhythm": 7,
        "adaptation_restraint": 8,
        "minimal_replacement_effect": 8,
        "qualified": True,
        "problems": [],
    }
    artifacts = {
        "N09": {"llm": {"is_sufficient": True, "variants": [{}, {}, {}]}},
        "N11": {"llm": {
            "decision": "PASS", "accuracy": accuracy, "coverage": 0.9,
        }},
        "N11.5": {"llm": {"route": "STRUCTURE_PRESERVING_REWRITE"}},
        "N13": {"llm": {
            "scores": [selected_score], "qualified_candidate_ids": ["C1"],
        }, "minimum_thresholds": {
            "fluency": 6, "recognition": 6, "agu_fit": 6,
        }},
        "N14": {"llm": {"selected_candidate_id": "C1"}},
        "N15": {"llm": {
            "title": "凿agu版·新梗",
            "normalized_title": "凿agu版·新梗",
            "final_agu_text": "他正在凿agu。",
        }},
    }
    if safety is not None:
        artifacts["N15"]["llm"]["content_safety"] = {
            "status": safety,
            "method": "DETERMINISTIC_RULESET",
            "policy_version": "content-safety-v1",
            "checks": [],
        }
    return artifacts


def modular_evaluation_payload(expected_run_version: int, branch_id: str) -> dict:
    candidate = {
        "fluency": 4,
        "original_meme_recognition": 4,
        "agu_zao_naturalness": 4,
        "humor": 4,
        "template_logic": 4,
        "usability": "USABLE",
    }
    return {
        "expected_run_version": expected_run_version,
        "branch_id": branch_id,
        "original_search_plan": {
            "anchor_accuracy": 4,
            "query_coverage": 4,
            "plan_targeting": 4,
        },
        "selected_original_meme": {
            "popularity": 4,
            "applicability": 4,
            "adaptability": 4,
            "evidence_reliability": 4,
        },
        "variant_search_plan": {
            "slot_replacement_targeting": 4,
            "query_diversity": 4,
            "ugc_orientation": 4,
            "noise_avoidance": 4,
        },
        "variant_search_results": {
            "relevance": 4,
            "real_variant_ratio": 4,
            "independent_evidence_quality": 4,
            "variant_diversity": 4,
        },
        "template_extraction": {
            "accuracy": 4,
            "original_reconstruction": 4,
            "variant_coverage": 4,
            "slot_rationality": 4,
        },
        "candidate_generation": {
            "overall": {
                "effective_difference": 4,
                "natural_rewrite_coverage": 4,
                "overall_selectable_quality": 4,
            },
            "candidates": {f"C{index}": dict(candidate) for index in range(1, 6)},
        },
        "final_result": {
            "is_best_candidate": True,
            "better_candidate_id": None,
            "fluency": 4,
            "original_meme_recognition": 4,
            "agu_zao_fit": 4,
            "humor": 4,
            "overall_satisfaction": 4,
        },
        "main_problem_nodes": ["NO_OBVIOUS_PROBLEM"],
        "admission": {"decision": "NOT_ADMIT"},
    }


@pytest.mark.asyncio
async def test_historical_run_usage_is_queryable_after_process_memory_is_lost(tmp_path, monkeypatch):
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    context = RunContext(mode=RunMode.AUTO_DISCOVERY, admission_mode=AdmissionMode.HUMAN)
    await repository.create_run(context)
    await repository.record_api_call(
        context.run_id, api_type="llm", provider="deepseek", model="deepseek-v4-flash",
        input_tokens=120, output_tokens=30, total_tokens=150, node_key="N12",
    )
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", SimpleNamespace(repository=repository, contexts={}))

    usage = await api_router.usage_for_run(context.run_id)

    assert usage["calls"] == 1
    assert usage["total_tokens"] == 150


@pytest.mark.asyncio
async def test_complete_historical_record_exposes_nodes_sources_evaluation_events_and_usage(tmp_path, monkeypatch):
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'complete.db'}")
    context = RunContext(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN, seed_text="种子")
    await repository.create_run(context)
    await repository.persist_node(context, "N09", {"llm": {"variants": [{
        "variant_text": "变式一", "source_id": "V001", "source_url": "https://example.com/v",
        "evidence_quote": "变式一", "shared_anchor": "变式",
    }]}}, "SUFFICIENT")
    async with repository.session() as session:
        session.add(RunHumanEvaluation(
            id="legacy-evaluation",
            run_id=context.run_id,
            branch_id=context.active_branch_id,
            processing_chain_scores_json={"score": 5},
            candidate_set_scores_json={"score": 4},
            candidate_scores_json={"C1": {"score": 4}},
            final_result_scores_json={"score": 3},
            main_problem_nodes_json=["N09"],
            admission_decision="REJECT",
            submitted_at=datetime.now(UTC),
        ))
        await session.commit()
    await repository.record_api_call(
        context.run_id, api_type="search", provider="exa", cost_usd=0.01, node_key="N08",
    )
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", SimpleNamespace(repository=repository, contexts={}))

    record = await api_router.complete_run_record(context.run_id)

    assert record["run"]["run_id"] == context.run_id
    assert record["nodes"][0]["node_key"] == "N09"
    assert record["sources"][0]["evidence_type"] == "VALIDATED_VARIANT"
    assert record["evaluations"][0]["admission_decision"] == "REJECT"
    assert record["evaluations"][0]["processing_chain"] == {"score": 5}
    assert record["api_calls"][0]["provider"] == "exa"


@pytest.mark.asyncio
async def test_complete_record_exposes_stable_node_order_timestamps_and_branch_fork(
    tmp_path, monkeypatch,
):
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'record-order.db'}")
    context = RunContext(mode=RunMode.AUTO_DISCOVERY, admission_mode=AdmissionMode.HUMAN)
    await repository.create_run(context)
    later = datetime(2026, 9, 1, 2, 0, 0, tzinfo=UTC)
    earlier = datetime(2026, 9, 1, 1, 0, 0, tzinfo=UTC)
    await repository.persist_node(
        context,
        "N09",
        {"llm": {"variants": []}},
        "INSUFFICIENT",
        started_at=later,
        ended_at=later,
    )
    await repository.persist_node(
        context,
        "N03",
        {"llm": {"queries": []}},
        "PLAN_READY",
        started_at=earlier,
        ended_at=earlier,
    )
    async with repository.session() as session:
        fork_execution_id = await session.scalar(
            select(RunNodeExecution.id).where(
                RunNodeExecution.run_id == context.run_id,
                RunNodeExecution.node_key == "N09",
            ),
        )
    assert fork_execution_id is not None
    child_branch_id = "corrected-branch"
    await repository.persist_corrected_branch(
        run_id=context.run_id,
        branch_id=child_branch_id,
        parent_branch_id=context.active_branch_id,
        forked_from_execution_id=fork_execution_id,
    )
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", SimpleNamespace(repository=repository, contexts={}))

    first_record = await api_router.complete_run_record(context.run_id)
    second_record = await api_router.complete_run_record(context.run_id)

    assert [node["node_key"] for node in first_record["nodes"]] == ["N03", "N09"]
    assert [node["execution_order"] for node in first_record["nodes"]] == [0, 1]
    assert [
        (node["execution_id"], node["execution_order"])
        for node in first_record["nodes"]
    ] == [
        (node["execution_id"], node["execution_order"])
        for node in second_record["nodes"]
    ]
    assert datetime.fromisoformat(first_record["nodes"][0]["started_at"]) == earlier.replace(tzinfo=None)
    assert datetime.fromisoformat(first_record["nodes"][0]["ended_at"]) == earlier.replace(tzinfo=None)
    child_branch = next(
        branch for branch in first_record["branches"]
        if branch["branch_id"] == child_branch_id
    )
    assert child_branch["parent_branch_id"] == context.active_branch_id
    assert child_branch["forked_from_execution_id"] == fork_execution_id


@pytest.mark.asyncio
async def test_modular_evaluation_api_validates_persists_and_reuses_evaluation_id(tmp_path, monkeypatch):
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'modular.db'}")
    engine = WorkflowEngine(repository=repository)
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", engine)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/runs", json={
            "mode": "MANUAL_SEED",
            "admission_mode": "HUMAN",
            "seed_text": "测试种子",
        })
        assert created.status_code == 201
        run_id = created.json()["run_id"]

        for _ in range(400):
            snapshot = (await client.get(f"/api/v1/runs/{run_id}")).json()
            if snapshot["state"] == "WAITING_HUMAN_EVALUATION":
                break
            await asyncio.sleep(0.005)
        assert snapshot["state"] == "WAITING_HUMAN_EVALUATION"

        legacy_submission = await client.post(f"/api/v1/runs/{run_id}/evaluation", json={
            "expected_run_version": snapshot["run_version"],
            "branch_id": snapshot["active_branch_id"],
            "score": 5,
        })
        assert legacy_submission.status_code == 422

        payload = modular_evaluation_payload(
            snapshot["run_version"], snapshot["active_branch_id"],
        )
        payload["admission"]["reason"] = "默认节点没有安全结果，不入库"
        payload["overall_comment"] = "七模块整体可用"
        submitted = await client.post(
            f"/api/v1/runs/{run_id}/evaluation",
            json=payload,
        )
        assert submitted.status_code == 200

        patch = None
        for _ in range(400):
            record_response = await client.get(f"/api/v1/runs/{run_id}/record")
            record = record_response.json()
            async with repository.session() as session:
                patch = await session.scalar(select(RunStrategyPatch))
            if record["evaluations"] and patch is not None:
                break
            await asyncio.sleep(0.005)

    evaluation = record["evaluations"][0]
    assert evaluation["original_search_plan"]["anchor_accuracy"] == 4
    assert evaluation["variant_search_results"]["comment"] == ""
    assert evaluation["candidate_generation"]["candidates"]["C5"]["usability"] == "USABLE"
    assert evaluation["admission"] == {
        "decision": "NOT_ADMIT",
        "override": None,
        "reason": "默认节点没有安全结果，不入库",
    }
    assert evaluation["overall_comment"] == "七模块整体可用"
    assert patch is not None
    assert patch.evaluation_id == evaluation["evaluation_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("admission_mode", "admission"), [
    (AdmissionMode.HUMAN, {}),
    (AdmissionMode.HUMAN, {"override": "KEEP"}),
    (AdmissionMode.HUMAN, {"decision": "ADMIT", "override": "KEEP"}),
    (AdmissionMode.AUTO, {}),
    (AdmissionMode.AUTO, {"decision": "ADMIT"}),
    (AdmissionMode.AUTO, {"decision": "ADMIT", "override": "KEEP"}),
])
async def test_modular_evaluation_rejects_admission_fields_for_wrong_mode(
    admission_mode, admission, monkeypatch,
):
    context = RunContext(mode=RunMode.AUTO_DISCOVERY, admission_mode=admission_mode)
    context.current_state = RunState.WAITING_HUMAN_EVALUATION
    engine = WorkflowEngine()
    engine.contexts[context.run_id] = context
    engine.buses[context.run_id] = EventBus()
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", engine)
    payload = modular_evaluation_payload(context.run_version, context.active_branch_id)
    payload["admission"] = admission

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/runs/{context.run_id}/evaluation", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "automatic_decision", "expected_decision"), [
    ("KEEP", "ADMIT", "ADMIT"),
    ("OVERRIDE_TO_ADMIT", "NOT_ADMIT", "ADMIT"),
    ("OVERRIDE_TO_NOT_ADMIT", "ADMIT", "NOT_ADMIT"),
])
async def test_modular_evaluation_auto_override_persists_resolved_decision_and_feedback(
    override, automatic_decision, expected_decision, tmp_path, monkeypatch,
):
    repository = SQLiteRepository(
        f"sqlite+aiosqlite:///{tmp_path / f'auto-{override}.db'}",
    )
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(), repository=repository,
    )
    engine = WorkflowEngine(registry=registry, repository=repository)
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", engine)
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY, admission_mode=AdmissionMode.AUTO,
        current_node="N16", current_state=RunState.RUNNING,
    )
    context.active_artifacts.update(automatic_admission_artifacts(automatic_decision))
    context.node_outputs.update(context.active_artifacts)
    engine.contexts[context.run_id] = context
    engine.buses[context.run_id] = EventBus()
    await repository.create_run(context)
    prior_outcomes = {
        "N13": "HAS_QUALIFIED", "N14": "SELECTED", "N15": "DRAFT_READY",
    }
    persisted_at = datetime.now(UTC)
    for node_key, outcome in prior_outcomes.items():
        await repository.persist_node(
            context,
            node_key,
            context.active_artifacts[node_key],
            outcome,
            started_at=persisted_at,
            ended_at=persisted_at,
        )
    engine._tasks[context.run_id] = asyncio.create_task(engine._run(context))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_id = context.run_id
        for _ in range(400):
            snapshot = (await client.get(f"/api/v1/runs/{run_id}")).json()
            if snapshot["state"] == "WAITING_HUMAN_EVALUATION":
                break
            await asyncio.sleep(0.005)
        assert snapshot["state"] == "WAITING_HUMAN_EVALUATION"
        assert engine.contexts[run_id].node_outputs["N16"]["failed_conditions"] == (
            [] if automatic_decision == "ADMIT" else ["N11_ACCURACY_BELOW_8"]
        )
        assert engine.contexts[run_id].node_outputs["N17"][
            "admission_decision"
        ] == automatic_decision
        assert engine.contexts[run_id].node_outputs["N17"]["reason"]
        payload = modular_evaluation_payload(
            snapshot["run_version"], snapshot["active_branch_id"],
        )
        payload["admission"] = {"override": override, "reason": "自动结论复核"}
        payload["overall_comment"] = "AUTO 模式完整反馈"

        submitted = await client.post(f"/api/v1/runs/{run_id}/evaluation", json=payload)
        assert submitted.status_code == 200
        for _ in range(400):
            record = (await client.get(f"/api/v1/runs/{run_id}/record")).json()
            if (record["evaluations"]
                    and record["run"]["admission_decision"] == expected_decision
                    and record["run"]["state"] == "COMPLETED"
                    and (expected_decision != "ADMIT"
                         or record["run"]["formal_meme_id"])):
                break
            await asyncio.sleep(0.005)

    evaluation = record["evaluations"][0]
    assert evaluation["admission"] == {
        "decision": None,
        "override": override,
        "reason": "自动结论复核",
    }
    assert evaluation["admission_decision"] == expected_decision
    assert evaluation["overall_comment"] == "AUTO 模式完整反馈"
    assert record["run"]["admission_decision"] == expected_decision
    persisted_n17 = next(
        node for node in record["nodes"] if node["node_key"] == "N17"
    )
    assert persisted_n17["output"]["admission_decision"] == automatic_decision
    persisted_n13 = next(
        node for node in record["nodes"] if node["node_key"] == "N13"
    )
    persisted_score = persisted_n13["output"]["llm"]["scores"][0]
    assert "action_affirmed" not in persisted_score
    assert "critical_failures" not in persisted_score
    assert persisted_score["problems"] == []
    async with repository.session() as session:
        formal_records = (await session.execute(select(MemeRecord))).scalars().all()
    await repository.engine.dispose()
    assert len(formal_records) == (1 if expected_decision == "ADMIT" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("admission_mode", "admission", "safety"), [
    (AdmissionMode.HUMAN, {"decision": "ADMIT"}, None),
    (AdmissionMode.HUMAN, {"decision": "ADMIT"}, "UNCERTAIN"),
    (AdmissionMode.HUMAN, {"decision": "ADMIT"}, "REJECT"),
    (AdmissionMode.AUTO, {"override": "OVERRIDE_TO_ADMIT"}, None),
    (AdmissionMode.AUTO, {"override": "OVERRIDE_TO_ADMIT"}, "UNCERTAIN"),
    (AdmissionMode.AUTO, {"override": "OVERRIDE_TO_ADMIT"}, "REJECT"),
])
async def test_modular_evaluation_cannot_force_admission_without_passed_safety(
    admission_mode, admission, safety, tmp_path, monkeypatch,
):
    repository = SQLiteRepository(
        f"sqlite+aiosqlite:///{tmp_path / f'safety-{admission_mode}-{safety}.db'}",
    )
    engine = WorkflowEngine(repository=repository)
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=admission_mode,
        current_node="N18",
        current_state=RunState.WAITING_HUMAN_EVALUATION,
    )
    n16 = {"failed_conditions": [], "decision_basis": "安全裁定测试"}
    if safety is not None:
        n16["safety"] = safety
    context.active_artifacts["N16"] = n16
    context.node_outputs["N16"] = n16
    if admission_mode is AdmissionMode.AUTO:
        n17 = {
            "admission_decision": "NOT_ADMIT",
            "reason": "内容安全未通过",
            "safety": safety or "UNCERTAIN",
        }
        context.active_artifacts["N17"] = n17
        context.node_outputs["N17"] = n17
    engine.contexts[context.run_id] = context
    engine.buses[context.run_id] = EventBus()
    await repository.create_run(context)
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", engine)
    payload = modular_evaluation_payload(
        context.run_version, context.active_branch_id,
    )
    payload["admission"] = admission

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{context.run_id}/evaluation", json=payload,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONTENT_SAFETY_NOT_PASS"
    assert (safety or "UNCERTAIN") in response.json()["error"]["message"]
    async with repository.session() as session:
        evaluations = (await session.execute(select(RunHumanEvaluation))).scalars().all()
        formal_records = (await session.execute(select(MemeRecord))).scalars().all()
    await repository.engine.dispose()
    assert evaluations == []
    assert formal_records == []


@pytest.mark.asyncio
async def test_generic_command_api_rejects_internal_evaluation_without_side_effects(
    tmp_path, monkeypatch,
):
    repository = SQLiteRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'internal-evaluation-command.db'}",
    )
    engine = WorkflowEngine(repository=repository)
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        current_node="N18",
        current_state=RunState.WAITING_HUMAN_EVALUATION,
    )
    n16 = {
        "score": 9,
        "threshold": 6,
        "safety": "REJECT",
        "failed_conditions": ["CONTENT_SAFETY_NOT_PASS"],
        "decision_basis": "内容安全结果为REJECT",
    }
    context.active_artifacts["N16"] = n16
    context.node_outputs["N16"] = n16
    engine.contexts[context.run_id] = context
    engine.buses[context.run_id] = EventBus()
    await repository.create_run(context)
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", engine)
    state_before = (
        context.current_state,
        context.current_node,
        context.run_version,
        context.pending_human_action,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/runs/{context.run_id}/commands",
            json={
                "command_id": str(uuid4()),
                "type": "EVALUATION_SUBMITTED",
                "expected_run_version": context.run_version,
                "payload": {
                    "admission_decision": "ADMIT",
                    "unvalidated": "arbitrary payload",
                },
            },
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "COMMAND_TYPE_NOT_ALLOWED"
    assert f"/runs/{context.run_id}/evaluation" in error["message"]
    assert error["details"] == {}
    assert error["request_id"]
    assert (
        context.current_state,
        context.current_node,
        context.run_version,
        context.pending_human_action,
    ) == state_before
    async with repository.session() as session:
        persisted_run = await session.get(RunRecord, context.run_id)
        evaluations = (await session.execute(select(RunHumanEvaluation))).scalars().all()
        formal_records = (await session.execute(select(MemeRecord))).scalars().all()
    await repository.engine.dispose()
    assert persisted_run is not None
    assert persisted_run.status == "WAITING_HUMAN_EVALUATION"
    assert persisted_run.admission_decision is None
    assert evaluations == []
    assert formal_records == []


@pytest.mark.asyncio
async def test_modular_evaluation_maps_engine_workflow_conflict_to_http_409(monkeypatch):
    context = RunContext(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN)
    context.current_state = RunState.RUNNING
    engine = WorkflowEngine()
    engine.contexts[context.run_id] = context
    api_router = importlib.import_module("app.api.router")
    monkeypatch.setattr(api_router, "_engine", engine)
    payload = modular_evaluation_payload(context.run_version, context.active_branch_id)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/runs/{context.run_id}/evaluation", json=payload)

    assert response.status_code == 409
