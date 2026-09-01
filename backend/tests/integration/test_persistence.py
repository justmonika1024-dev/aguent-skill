import asyncio

import pytest
from sqlalchemy import select

from app.db.models import (
    MemeRecord,
    MemeSource,
    RunEvent,
    RunHumanEvaluation,
    RunNodeExecution,
    RunRecord,
    RunSourceEvidence,
    RunStrategyPatch,
    RunStrategyState,
    RunStrategyVersion,
)
from app.db.persistence import SQLiteRepository
from app.services.strategy import StrategyService, default_strategy
from app.workflow.context import AdmissionMode, RunContext, RunMode, RunState
from app.workflow.engine import WorkflowEngine
from app.workflow.events import Command
from app.workflow.registry import NodeRegistry


class FakeNode:
    def __init__(self, key, outcome): self.key, self.outcome = key, outcome
    async def execute(self, value, services): return {"outcome": self.outcome, "artifact": {"node": self.key}}


class FailOnceNode(FakeNode):
    def __init__(self, key, outcome):
        super().__init__(key, outcome)
        self.calls = 0

    async def execute(self, value, services):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("N12 must treat agu as the person receiving the action 凿")
        return await super().execute(value, services)


def test_strategy_defaults_are_isolated_and_patches_are_validated():
    first = default_strategy()
    second = default_strategy()
    first["search"]["variant_query_directives"].append("只影响本副本")
    assert second["search"]["variant_query_directives"] == []
    assert second["search"]["exclude_exact_reprints"] is True
    assert second["generation"]["reject_awkward_demonstrative_phrase"] is True
    assert second["evaluation"]["minimum_fluency"] == 6

    service = StrategyService()
    patched = service.apply(second, {"patch_operations": [
        {"op": "add", "path": "/search/variant_query_directives/-", "value": "优先 UGC"},
        {"op": "add", "path": "/search/variant_query_directives/-", "value": "优先 UGC"},
        {"op": "replace", "path": "/search/prefer_ugc_sources", "value": True},
        {"op": "replace", "path": "/search/minimum_template_coverage", "value": 0.8},
    ]})
    assert patched["search"]["variant_query_directives"] == ["优先 UGC"]
    assert patched["search"]["prefer_ugc_sources"] is True
    assert patched["search"]["minimum_template_coverage"] == 0.8

    invalid_operations = [
        {"op": "replace", "path": "/search/prefer_ugc_sources", "value": "true"},
        {"op": "replace", "path": "/search/minimum_template_coverage", "value": 1.1},
        {"op": "replace", "path": "/generation/candidate_count", "value": 6},
        {"op": "replace", "path": "/budgets/llm", "value": 1},
    ]
    for operation in invalid_operations:
        with pytest.raises(ValueError):
            service.apply(second, {"operations": [operation]})


@pytest.mark.asyncio
async def test_repository_versions_strategy_and_syncs_waiting_state(tmp_path):
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'strategy.db'}")
    version_id, strategy = await repo.ensure_active_strategy()
    assert strategy["search"]["minimum_template_coverage"] == 0.6
    after_id, after = await repo.apply_strategy_patch(
        source_run_id="run-1", evaluation_id="eval-1",
        before_version_id=version_id,
        patch={
            "feedback_summary": "变式转载过多",
            "affected_nodes": ["N07", "N09"],
            "patch_operations": [{
                "op": "add", "path": "/search/variant_query_directives/-",
                "value": "排除原句转载",
            }],
            "next_round_hypotheses": ["真实变式比例提升"],
        },
    )
    assert after_id != version_id
    assert after["search"]["variant_query_directives"] == ["排除原句转载"]

    async with repo.session() as session:
        versions = (await session.execute(
            select(RunStrategyVersion).order_by(RunStrategyVersion.version_number)
        )).scalars().all()
        state = await session.get(RunStrategyState, 1)
        persisted_patch = await session.scalar(select(RunStrategyPatch))
    assert [(row.id, row.version_number) for row in versions] == [
        (version_id, 1), (after_id, 2),
    ]
    assert state.active_strategy_version_id == after_id
    assert persisted_patch.before_version_id == version_id
    assert persisted_patch.after_version_id == after_id


@pytest.mark.asyncio
async def test_engine_syncs_waiting_state_and_continuous_setting(tmp_path):
    outcomes = {"N01":"ACCEPTED", "N02":"PLANNED", "N03":"PLAN_READY", "N04":"RESULTS_FOUND", "N05":"SELECTED", "N06":"NOT_DUPLICATE", "N07":"PLAN_READY", "N08":"RESULTS_FOUND", "N09":"SUFFICIENT", "N10":"TEMPLATE_READY", "N11":"PASS", "N11.5":"DIRECT_SLOT_FILL", "N12":"VALID_BATCH", "N13":"HAS_QUALIFIED", "N14":"SELECTED", "N15":"DRAFT_READY", "N16":"NOT_DUPLICATE", "N17":"WAIT_HUMAN_DECISION", "N19":"PATCH_VALID", "N20":"COMPLETED"}
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'waiting.db'}")
    engine = WorkflowEngine(NodeRegistry({k: FakeNode(k, v) for k, v in outcomes.items()}), repository=repo)
    ctx = await engine.start_run(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        continuous_enabled=True,
    )
    assert ctx.strategy_version_id
    assert ctx.strategy_snapshot["search"]["minimum_template_coverage"] == 0.6
    assert engine.snapshot(ctx.run_id)["strategy_snapshot"] == ctx.strategy_snapshot
    for _ in range(500):
        if ctx.current_state is RunState.WAITING_HUMAN_EVALUATION:
            break
        await asyncio.sleep(.002)
    assert ctx.current_state is RunState.WAITING_HUMAN_EVALUATION

    await engine.command(ctx.run_id, Command(
        "SET_CONTINUOUS_EXECUTION",
        expected_run_version=ctx.run_version,
        payload={"enabled": False},
    ))
    async with repo.session() as session:
        run = await session.get(RunRecord, ctx.run_id)
    assert run.status == "WAITING_HUMAN_EVALUATION"
    assert run.continuous_enabled is ctx.continuous_enabled is False


@pytest.mark.asyncio
async def test_engine_persists_run_nodes_events_and_evaluation(tmp_path):
    outcomes = {"N01":"ACCEPTED", "N03":"PLAN_READY", "N04":"RESULTS_FOUND", "N05":"SELECTED", "N06":"NOT_DUPLICATE", "N07":"PLAN_READY", "N08":"RESULTS_FOUND", "N09":"SUFFICIENT", "N10":"TEMPLATE_READY", "N11":"PASS", "N11.5":"DIRECT_SLOT_FILL", "N12":"VALID_BATCH", "N13":"HAS_QUALIFIED", "N14":"SELECTED", "N15":"DRAFT_READY", "N16":"NOT_DUPLICATE", "N17":"WAIT_HUMAN_DECISION", "N19":"PATCH_VALID", "N20":"COMPLETED"}
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    await repo.init()
    engine = WorkflowEngine(NodeRegistry({k: FakeNode(k, v) for k, v in outcomes.items()}), repository=repo)
    ctx = await engine.start_run(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN, seed_text="x")
    for _ in range(500):
        if ctx.current_state is RunState.WAITING_HUMAN_EVALUATION: break
        await asyncio.sleep(.002)
    await engine.submit_evaluation(ctx.run_id, {"score": 5}, expected_run_version=ctx.run_version)
    for _ in range(500):
        if ctx.current_state is RunState.COMPLETED: break
        await asyncio.sleep(.002)
    run = None
    for _ in range(500):
        async with repo.session() as session:
            run = await session.scalar(select(RunRecord).where(RunRecord.id == ctx.run_id))
        if run.status == "COMPLETED":
            break
        await asyncio.sleep(.002)
    assert run.status == "COMPLETED"
    async with repo.session() as session:
        assert (await session.scalar(select(RunNodeExecution.id).where(RunNodeExecution.run_id == ctx.run_id)))
        assert (await session.scalar(select(RunEvent.id).where(RunEvent.run_id == ctx.run_id)))
        assert (await session.scalar(select(RunHumanEvaluation.id).where(RunHumanEvaluation.run_id == ctx.run_id)))


@pytest.mark.asyncio
async def test_failed_node_is_persisted_and_retry_reexecutes_the_same_node(tmp_path):
    outcomes = {"N01":"ACCEPTED", "N03":"PLAN_READY", "N04":"RESULTS_FOUND", "N05":"SELECTED", "N06":"NOT_DUPLICATE", "N07":"PLAN_READY", "N08":"RESULTS_FOUND", "N09":"SUFFICIENT", "N10":"TEMPLATE_READY", "N11":"PASS", "N11.5":"DIRECT_SLOT_FILL", "N12":"VALID_BATCH", "N13":"HAS_QUALIFIED", "N14":"SELECTED", "N15":"DRAFT_READY", "N16":"NOT_DUPLICATE", "N17":"WAIT_HUMAN_DECISION", "N19":"PATCH_VALID", "N20":"COMPLETED"}
    nodes = {key: FakeNode(key, outcome) for key, outcome in outcomes.items()}
    nodes["N12"] = FailOnceNode("N12", "VALID_BATCH")
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
    engine = WorkflowEngine(NodeRegistry(nodes), repository=repo)
    ctx = await engine.start_run(
        mode=RunMode.MANUAL_SEED,
        admission_mode=AdmissionMode.HUMAN,
        seed_text="没有未来的未来不是我想要的未来",
    )

    for _ in range(500):
        if ctx.current_state is RunState.FAILED:
            break
        await asyncio.sleep(.002)
    assert ctx.current_state is RunState.FAILED

    async with repo.session() as session:
        failed = (await session.execute(select(RunNodeExecution).where(
            RunNodeExecution.run_id == ctx.run_id,
            RunNodeExecution.node_key == "N12",
        ))).scalars().all()
        assert len(failed) == 1
        assert failed[0].status == "FAILED"
        assert failed[0].attempt_no == 1
        assert failed[0].error_code == "NODE_OUTPUT_VALIDATION_FAILED"
        assert failed[0].error_message == "N12 must treat agu as the person receiving the action 凿"

    await engine.command(ctx.run_id, Command(
        "RETRY_NODE",
        expected_run_version=ctx.run_version,
        payload={"node_key": "N12"},
    ))
    for _ in range(500):
        if ctx.current_state is RunState.WAITING_HUMAN_EVALUATION:
            break
        await asyncio.sleep(.002)
    assert ctx.current_state is RunState.WAITING_HUMAN_EVALUATION

    async with repo.session() as session:
        attempts = (await session.execute(select(RunNodeExecution).where(
            RunNodeExecution.run_id == ctx.run_id,
            RunNodeExecution.node_key == "N12",
        ).order_by(RunNodeExecution.attempt_no))).scalars().all()
        assert [(row.attempt_no, row.status) for row in attempts] == [
            (1, "FAILED"),
            (2, "SUCCEEDED"),
        ]
        assert all(row.started_at is not None and row.ended_at is not None for row in attempts)
        assert attempts[0].started_at < attempts[1].started_at


@pytest.mark.asyncio
async def test_persistence_distinguishes_search_results_and_validated_variants(tmp_path):
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}")
    ctx = RunContext(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN)
    await repo.create_run(ctx)
    original_source = {
        "source_id": "O001", "title": "原梗来源", "url": "https://example.com/original",
        "canonical_url": "https://example.com/original", "text": "原始梗正文",
    }
    variant_source = {
        "source_id": "V001", "title": "变式来源", "url": "https://example.com/variant",
        "canonical_url": "https://example.com/variant", "text": "网友改编：你说的对，但是新版本。",
    }
    await repo.persist_node(ctx, "N04", {"queries": [], "sources": [original_source]}, "RESULTS_FOUND")
    await repo.persist_node(ctx, "N08", {"queries": [], "sources": [variant_source]}, "RESULTS_FOUND")
    await repo.persist_node(ctx, "N09", {"llm": {"variants": [{
        "variant_text": "你说的对，但是新版本。", "source_id": "V001",
        "source_url": "https://example.com/variant",
        "evidence_quote": "你说的对，但是新版本。", "shared_anchor": "你说的对，但是",
    }]}}, "SUFFICIENT")

    async with repo.session() as session:
        rows = (await session.execute(select(RunSourceEvidence).where(
            RunSourceEvidence.run_id == ctx.run_id
        ))).scalars().all()
        assert [row.evidence_type for row in rows] == [
            "ORIGINAL_SEARCH_RESULT", "VARIANT_SEARCH_RESULT", "VALIDATED_VARIANT",
        ]
        assert rows[-1].source_id == "V001"
        assert rows[-1].text == "你说的对，但是新版本。"


@pytest.mark.asyncio
async def test_admitted_run_archives_exact_original_template_final_and_sources(tmp_path):
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'formal.db'}")
    ctx = RunContext(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN)
    await repo.create_run(ctx)
    ctx.node_outputs.update({
        "N05": {"llm": {
            "title": "原神介绍体", "original_text": "你说的对，但是《原神》是由米哈游自主研发的一款开放世界冒险游戏。",
            "source_id": "O001", "source_url": "https://example.com/original", "evidence_quote": "原梗证据",
        }},
        "N09": {"llm": {"variants": [{
            "variant_text": "你说的对，但是《星际战甲》是由DE自主研发的一款科幻冒险游戏。",
            "source_id": "V001", "source_url": "https://example.com/variant", "evidence_quote": "变式证据",
        }]}},
        "N10": {"llm": {"canonical_template_text": "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"}},
        "N15": {"llm": {"title": "凿具介绍体", "final_agu_text": "你说的对，但是铁凿是由老王自主研发的一款趁手工具，他正在凿agu。"}},
    })
    ctx.node_outputs["N14"] = {"llm": {"selected_candidate_id": "C3"}}
    await repo.record_api_call(
        ctx.run_id,
        api_type="llm",
        provider="fake",
        input_tokens=120,
        output_tokens=80,
        total_tokens=200,
        cost_usd=0.02,
    )
    await repo.record_api_call(
        ctx.run_id,
        api_type="search",
        provider="fake-search",
        cost_usd=0.01,
    )
    await repo.persist_evaluation(ctx, {"admission_decision": "ADMIT"})
    ctx.current_state = RunState.COMPLETED
    await repo.archive_run(ctx)

    async with repo.session() as session:
        run = await session.get(RunRecord, ctx.run_id)
        assert run.selected_original_title == "原神介绍体"
        assert run.selected_original_text.startswith("你说的对，但是《原神》")
        assert run.selected_candidate_id == "C3"
        assert run.final_agu_text.endswith("他正在凿agu。")
        assert run.total_llm_input_tokens == 120
        assert run.total_llm_output_tokens == 80
        assert float(run.total_llm_cost_usd) == pytest.approx(0.02)
        assert float(run.total_search_cost_usd) == pytest.approx(0.01)
        meme = await session.scalar(select(MemeRecord).where(MemeRecord.source_run_id == ctx.run_id))
        assert meme is not None
        assert meme.original_meme_text.startswith("你说的对，但是《原神》")
        assert meme.canonical_template_text == "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"
        assert meme.final_agu_text.endswith("他正在凿agu。")
        sources = (await session.execute(select(MemeSource).where(
            MemeSource.meme_id == meme.id
        ).order_by(MemeSource.sort_order))).scalars().all()
        assert [(source.source_role, source.source_id) for source in sources] == [
            ("ORIGINAL", "O001"), ("VARIANT", "V001"),
        ]
