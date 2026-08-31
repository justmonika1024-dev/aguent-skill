import importlib
from types import SimpleNamespace

import pytest

from app.db.persistence import SQLiteRepository
from app.workflow.context import AdmissionMode, RunContext, RunMode


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
    await repository.persist_evaluation(context, {
        "processing_chain": {"score": 5}, "admission_decision": "REJECT",
    })
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
    assert record["api_calls"][0]["provider"] == "exa"
