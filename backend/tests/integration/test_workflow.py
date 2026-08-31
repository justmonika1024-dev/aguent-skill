import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.workflow.context import AdmissionMode, RunMode, RunState
from app.workflow.engine import WorkflowConflict, WorkflowEngine
from app.workflow.events import Command
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
