import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import RunEvent, RunNodeExecution
from app.db.persistence import SQLiteRepository
from app.main import app
from app.workflow.context import AdmissionMode, RunContext, RunMode, RunState
from app.workflow.engine import WorkflowConflict, WorkflowEngine
from app.workflow.events import Command, EventBus
from app.workflow.registry import NodeRegistry
from app.workflow.transitions import TransitionTable


class FakeNode:
    def __init__(self, key, outcome):
        self.key, self.outcome = key, outcome

    async def execute(self, node_input, services):
        return {"outcome": self.outcome, "artifact": {"ok": self.key}}


class StrategyAwareN07(FakeNode):
    async def execute(self, node_input, services):
        strategy = services.get("strategy_snapshot", {
            "search": {"variant_query_directives": []},
        })
        return {
            "outcome": self.outcome,
            "artifact": {
                "ok": self.key,
                "applied_directives": strategy["search"]["variant_query_directives"],
            },
        }


class FeedbackN19(FakeNode):
    async def execute(self, node_input, services):
        return {
            "outcome": self.outcome,
            "artifact": {
                "feedback_summary": "第一轮变式搜索结果基本都是原句转载",
                "affected_nodes": ["N07", "N09"],
                "patch_operations": [{
                    "op": "add",
                    "path": "/search/variant_query_directives/-",
                    "value": "排除原句转载，优先搜索网友槽位改编",
                }],
                "score_gaps": {"variant_search_results.real_variant_ratio": 3},
                "next_round_hypotheses": ["真实变式比例提升"],
            },
        }


class InvalidFeedbackN19(FakeNode):
    async def execute(self, node_input, services):
        return {
            "outcome": self.outcome,
            "artifact": {
                "feedback_summary": "尝试修改不可变预算",
                "affected_nodes": ["N07"],
                "patch_operations": [{
                    "op": "replace",
                    "path": "/budgets/max_cost",
                    "value": 999,
                }],
                "score_gaps": {},
                "next_round_hypotheses": [],
            },
        }


def complete_evaluation_payload(expected_run_version: int, branch_id: str) -> dict:
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


@pytest.mark.parametrize(("mode", "expected"), [
    (RunMode.AUTO_DISCOVERY, "N02"),
    (RunMode.MANUAL_SEED, "WAITING_HUMAN_INTERVENTION"),
])
def test_variant_search_limit_routes_auto_and_manual_differently(mode, expected):
    assert TransitionTable().next(
        "N09", "ABANDON_ORIGINAL", mode=mode.value,
    ) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("node_key", ["N09", "N11"])
async def test_node_completed_event_includes_persisted_fallback_audit_fields(
    node_key, tmp_path,
):
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
    )
    repository = SQLiteRepository(
        f"sqlite+aiosqlite:///{tmp_path / f'{node_key}-fallback-event.db'}",
    )
    await repository.create_run(context)
    engine = WorkflowEngine(repository=repository)
    engine.contexts[context.run_id] = context
    engine.buses[context.run_id] = EventBus()
    context.active_artifacts[node_key] = {
        "fallback": {
            "count": 2,
            "threshold": 2,
            "reason": f"{node_key}_MORE_VARIANT_EVIDENCE",
        },
    }
    async def read_live_sse():
        event = await anext(engine.buses[context.run_id].subscribe())
        return event.sse()

    live_sse_task = asyncio.create_task(read_live_sse())
    await asyncio.sleep(0)

    await engine._emit(context, "node.completed", {
        "node_key": node_key,
        "outcome": "ABANDON_ORIGINAL",
    })

    live_sse = await live_sse_task
    event = engine.events(context.run_id)[0][-1]
    assert event.payload["count"] == 2
    assert event.payload["threshold"] == 2
    assert event.payload["reason"] == f"{node_key}_MORE_VARIANT_EVIDENCE"
    assert '"count": 2' in live_sse
    async with repository.session() as session:
        persisted = await session.scalar(select(RunEvent).where(
            RunEvent.run_id == context.run_id,
            RunEvent.event_type == "node.completed",
        ))
    assert persisted is not None
    assert persisted.payload_json["count"] == 2
    assert persisted.payload_json["threshold"] == 2
    assert persisted.payload_json["reason"] == f"{node_key}_MORE_VARIANT_EVIDENCE"


@pytest.mark.asyncio
async def test_manual_run_waits_for_evaluation_and_accepts_idempotent_command():
    outcomes = {"N01": "ACCEPTED", "N03": "PLAN_READY", "N04": "RESULTS_FOUND",
                "N05": "SELECTED", "N06": "NOT_DUPLICATE", "N07": "PLAN_READY",
                "N08": "RESULTS_FOUND", "N09": "SUFFICIENT", "N10": "TEMPLATE_READY",
                "N11": "PASS", "N11.5": "DIRECT_SLOT_FILL", "N12": "VALID_BATCH",
                "N13": "HAS_QUALIFIED", "N14": "SELECTED", "N15": "DRAFT_READY",
                "N16": "NOT_DUPLICATE", "N17": "WAIT_HUMAN_DECISION", "N19": "PATCH_VALID",
                "N20": "COMPLETED"}
    engine = WorkflowEngine(NodeRegistry({k: FakeNode(k, v) for k, v in outcomes.items()}))
    ctx = await engine.start_run(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN, seed_text="x")
    for _ in range(100):
        if ctx.current_state is RunState.WAITING_HUMAN_EVALUATION:
            break
        await asyncio.sleep(0.001)
    assert ctx.current_state is RunState.WAITING_HUMAN_EVALUATION
    command = Command("EVALUATION_SUBMITTED", expected_run_version=ctx.run_version, payload={"score": 5})
    result = await engine.command(ctx.run_id, command)
    assert result["accepted"]
    assert await engine.command(ctx.run_id, command) == result


@pytest.mark.asyncio
async def test_next_round_strategy_is_applied_before_second_n07(tmp_path):
    outcomes = {
        "N01": "ACCEPTED", "N02": "PLANNED", "N03": "PLAN_READY",
        "N04": "RESULTS_FOUND", "N05": "SELECTED", "N06": "NOT_DUPLICATE",
        "N07": "PLAN_READY", "N08": "RESULTS_FOUND", "N09": "SUFFICIENT",
        "N10": "TEMPLATE_READY", "N11": "PASS",
        "N11.5": "DIRECT_SLOT_FILL", "N12": "VALID_BATCH",
        "N13": "HAS_QUALIFIED", "N14": "SELECTED", "N15": "DRAFT_READY",
        "N16": "NOT_DUPLICATE", "N17": "WAIT_HUMAN_DECISION",
        "N19": "PATCH_VALID", "N20": "COMPLETED",
    }
    nodes = {key: FakeNode(key, outcome) for key, outcome in outcomes.items()}
    nodes["N07"] = StrategyAwareN07("N07", "PLAN_READY")
    nodes["N19"] = FeedbackN19("N19", "PATCH_VALID")
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'next-round.db'}")
    engine = WorkflowEngine(NodeRegistry(nodes), repository=repository)
    context = await engine.start_run(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        continuous_enabled=True,
    )
    before_version_id = context.strategy_version_id

    for _ in range(500):
        if context.current_state is RunState.WAITING_HUMAN_EVALUATION:
            break
        await asyncio.sleep(0.002)
    assert context.current_state is RunState.WAITING_HUMAN_EVALUATION

    await engine.submit_evaluation(
        context.run_id,
        {"overall_comment": "第一轮变式搜索结果基本都是原句转载"},
        expected_run_version=context.run_version,
        branch_id=context.active_branch_id,
    )
    for _ in range(500):
        if (context.current_state is RunState.WAITING_HUMAN_EVALUATION
                and context.strategy_version_id != before_version_id):
            break
        await asyncio.sleep(0.002)

    assert context.current_state is RunState.WAITING_HUMAN_EVALUATION
    assert context.strategy_version_id != before_version_id
    assert context.node_outputs["N07"]["applied_directives"] == [
        "排除原句转载，优先搜索网友槽位改编",
    ]
    n19 = context.node_outputs["N19"]
    assert n19["before_strategy_version_id"] == before_version_id
    assert n19["after_strategy_version_id"] == context.strategy_version_id
    async with repository.session() as session:
        n07_executions = (await session.execute(
            select(RunNodeExecution)
            .where(RunNodeExecution.run_id == context.run_id)
            .where(RunNodeExecution.node_key == "N07")
            .order_by(RunNodeExecution.attempt_no)
        )).scalars().all()
        n19_execution = await session.scalar(
            select(RunNodeExecution)
            .where(RunNodeExecution.run_id == context.run_id)
            .where(RunNodeExecution.node_key == "N19")
        )
    assert len(n07_executions) == 2
    assert n07_executions[-1].strategy_version_id == context.strategy_version_id
    assert n07_executions[-1].output_json["applied_directives"] == [
        "排除原句转载，优先搜索网友槽位改编",
    ]
    assert n19_execution is not None
    assert n19_execution.strategy_version_id == before_version_id
    assert n19_execution.output_json["before_strategy_version_id"] == before_version_id
    assert n19_execution.output_json["after_strategy_version_id"] == context.strategy_version_id

    await engine.command(context.run_id, Command(
        "TERMINATE", expected_run_version=context.run_version,
    ))


@pytest.mark.asyncio
async def test_invalid_n19_patch_routes_to_intervention_with_specific_error(tmp_path):
    outcomes = {
        "N01": "ACCEPTED", "N02": "PLANNED", "N03": "PLAN_READY",
        "N04": "RESULTS_FOUND", "N05": "SELECTED", "N06": "NOT_DUPLICATE",
        "N07": "PLAN_READY", "N08": "RESULTS_FOUND", "N09": "SUFFICIENT",
        "N10": "TEMPLATE_READY", "N11": "PASS",
        "N11.5": "DIRECT_SLOT_FILL", "N12": "VALID_BATCH",
        "N13": "HAS_QUALIFIED", "N14": "SELECTED", "N15": "DRAFT_READY",
        "N16": "NOT_DUPLICATE", "N17": "WAIT_HUMAN_DECISION",
        "N19": "PATCH_VALID", "N20": "COMPLETED",
    }
    nodes = {key: FakeNode(key, outcome) for key, outcome in outcomes.items()}
    nodes["N19"] = InvalidFeedbackN19("N19", "PATCH_VALID")
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'invalid-patch.db'}")
    engine = WorkflowEngine(NodeRegistry(nodes), repository=repository)
    context = await engine.start_run(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        continuous_enabled=True,
    )
    before_version_id = context.strategy_version_id
    for _ in range(500):
        if context.current_state is RunState.WAITING_HUMAN_EVALUATION:
            break
        await asyncio.sleep(0.002)

    await engine.submit_evaluation(
        context.run_id,
        {"overall_comment": "不要修改预算"},
        expected_run_version=context.run_version,
        branch_id=context.active_branch_id,
    )
    for _ in range(500):
        if context.current_state is RunState.WAITING_HUMAN_INTERVENTION:
            break
        await asyncio.sleep(0.002)

    assert context.current_state is RunState.WAITING_HUMAN_INTERVENTION
    assert context.strategy_version_id == before_version_id
    artifact = context.node_outputs["N19"]
    assert artifact["before_strategy_version_id"] == before_version_id
    assert artifact["after_strategy_version_id"] == before_version_id
    assert "path not allowed: budgets" in artifact["patch_error"]

    await engine.command(context.run_id, Command(
        "TERMINATE", expected_run_version=context.run_version,
    ))


@pytest.mark.asyncio
async def test_second_active_run_and_stale_version_are_rejected():
    engine = WorkflowEngine()
    ctx = await engine.start_run(mode=RunMode.AUTO_DISCOVERY, admission_mode=AdmissionMode.AUTO)
    with pytest.raises(WorkflowConflict):
        await engine.start_run(mode=RunMode.AUTO_DISCOVERY, admission_mode=AdmissionMode.AUTO)
    with pytest.raises(WorkflowConflict):
        await engine.command(ctx.run_id, Command("PAUSE", expected_run_version=999))


def failed_context(node_key: str = "N20"):
    from app.workflow.context import RunContext

    context = RunContext(mode=RunMode.MANUAL_SEED, admission_mode=AdmissionMode.HUMAN)
    context.current_node = node_key
    context.current_state = RunState.FAILED
    context.retry_available = True
    return context


@pytest.mark.asyncio
async def test_concurrent_retry_commands_start_only_one_workflow():
    context = failed_context()
    engine = WorkflowEngine(NodeRegistry({"N20": FakeNode("N20", "COMPLETED")}))
    engine.contexts[context.run_id] = context
    engine.buses[context.run_id] = EventBus()
    prior_can_finish = asyncio.Event()

    async def finishing_failed_attempt():
        await prior_can_finish.wait()

    engine._tasks[context.run_id] = asyncio.create_task(finishing_failed_attempt())

    retry_tasks = [
        asyncio.create_task(engine.command(context.run_id, Command(
            "RETRY_NODE", expected_run_version=0, payload={"node_key": "N20"},
        ))),
        asyncio.create_task(engine.command(context.run_id, Command(
            "RETRY_NODE", expected_run_version=0, payload={"node_key": "N20"},
        ))),
    ]
    await asyncio.sleep(0)
    prior_can_finish.set()
    results = await asyncio.gather(*retry_tasks, return_exceptions=True)

    assert sum(isinstance(result, dict) and result.get("accepted") is True for result in results) == 1
    assert sum(isinstance(result, WorkflowConflict) for result in results) == 1


@pytest.mark.asyncio
async def test_failed_run_cannot_retry_while_another_run_is_active():
    failed = failed_context()
    active = failed_context("N12")
    active.current_state = RunState.RUNNING
    active.retry_available = False
    engine = WorkflowEngine(NodeRegistry({"N20": FakeNode("N20", "COMPLETED")}))
    for context in (failed, active):
        engine.contexts[context.run_id] = context
        engine.buses[context.run_id] = EventBus()

    with pytest.raises(WorkflowConflict, match="ACTIVE_RUN_EXISTS"):
        await engine.command(failed.run_id, Command(
            "RETRY_NODE", expected_run_version=0, payload={"node_key": "N20"},
        ))


@pytest.mark.asyncio
async def test_default_run_nodes_are_json_serializable_after_evaluation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/runs", json={
            "mode": "MANUAL_SEED", "admission_mode": "HUMAN", "seed_text": "x",
            "continuous_enabled": False,
        })
        assert created.status_code == 201
        run_id = created.json()["run_id"]
        for _ in range(200):
            snapshot = (await client.get(f"/api/v1/runs/{run_id}")).json()
            if snapshot["state"] == "WAITING_HUMAN_EVALUATION":
                break
            await asyncio.sleep(0.001)
        response = await client.post(
            f"/api/v1/runs/{run_id}/evaluation",
            json=complete_evaluation_payload(
                snapshot["run_version"], snapshot["active_branch_id"],
            ),
        )
        assert response.status_code == 200
        for _ in range(200):
            final_snapshot = (await client.get(f"/api/v1/runs/{run_id}")).json()
            if final_snapshot["state"] in {"COMPLETED", "FAILED", "WAITING_HUMAN_INTERVENTION"}:
                break
            await asyncio.sleep(0.005)
        nodes = await client.get(f"/api/v1/runs/{run_id}/nodes")
        assert nodes.status_code == 200
        assert len(nodes.json()) == 21
