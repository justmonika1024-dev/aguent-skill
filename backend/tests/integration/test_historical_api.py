import asyncio
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import RunHumanEvaluation, RunStrategyPatch
from app.db.persistence import SQLiteRepository
from app.main import app
from app.providers.fake import FakeLLMProvider, FakeSearchProvider
from app.workflow.context import AdmissionMode, RunContext, RunMode, RunState
from app.workflow.engine import WorkflowEngine
from app.workflow.events import EventBus
from app.workflow.real_registry import build_real_registry


def automatic_admission_artifacts(automatic_decision: str) -> dict:
    accuracy = 5 if automatic_decision == "ADMIT" else 3
    selected_score = {
        "candidate_id": "C1",
        "fluency": 5,
        "recognition": 5,
        "agu_fit": 5,
        "humor": 4,
        "rhythm": 4,
        "adaptation_restraint": 5,
        "qualified": True,
        "action_affirmed": True,
        "critical_failures": [],
    }
    return {
        "N09": {"llm": {"is_sufficient": True, "variants": [{}, {}, {}]}},
        "N11": {"llm": {
            "decision": "PASS", "accuracy": accuracy, "coverage": 0.9,
        }},
        "N11.5": {"llm": {"route": "STRUCTURE_PRESERVING_REWRITE"}},
        "N13": {"llm": {
            "scores": [selected_score], "qualified_candidate_ids": ["C1"],
        }},
        "N14": {"llm": {"selected_candidate_id": "C1"}},
        "N15": {"llm": {
            "final_agu_text": "他正在凿agu。", "content_safety": "PASS",
        }},
    }


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
        "admission": {"decision": "ADMIT"},
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
        payload["admission"]["reason"] = "人工确认质量达标"
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
        "decision": "ADMIT",
        "override": None,
        "reason": "人工确认质量达标",
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
            [] if automatic_decision == "ADMIT" else ["N11_ACCURACY_BELOW_4"]
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
                    and record["run"]["admission_decision"] == expected_decision):
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
