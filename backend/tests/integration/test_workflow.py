import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.workflow.context import AdmissionMode, RunMode, RunState
from app.workflow.engine import WorkflowConflict, WorkflowEngine
from app.workflow.events import Command, EventBus
from app.workflow.registry import NodeRegistry


class FakeNode:
    def __init__(self, key, outcome):
        self.key, self.outcome = key, outcome

    async def execute(self, node_input, services):
        return {"outcome": self.outcome, "artifact": {"ok": self.key}}


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
        response = await client.post(f"/api/v1/runs/{run_id}/evaluation", json={
            "expected_run_version": snapshot["run_version"],
            "branch_id": snapshot["active_branch_id"],
            "score": 5,
        })
        assert response.status_code == 200
        for _ in range(200):
            final_snapshot = (await client.get(f"/api/v1/runs/{run_id}")).json()
            if final_snapshot["state"] in {"COMPLETED", "FAILED", "WAITING_HUMAN_INTERVENTION"}:
                break
            await asyncio.sleep(0.005)
        nodes = await client.get(f"/api/v1/runs/{run_id}/nodes")
        assert nodes.status_code == 200
        assert len(nodes.json()) == 21
