import asyncio

import pytest

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

