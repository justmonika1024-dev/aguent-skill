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
from app.workflow.context import AdmissionMode, RunContext, RunMode
from app.workflow.engine import WorkflowEngine


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

        submitted = await client.post(
            f"/api/v1/runs/{run_id}/evaluation",
            json=modular_evaluation_payload(
                snapshot["run_version"], snapshot["active_branch_id"],
            ),
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
    assert patch is not None
    assert patch.evaluation_id == evaluation["evaluation_id"]
