import asyncio

from app.workflow.context import AdmissionMode, RunMode, RunState
from app.workflow.engine import WorkflowEngine


def test_default_engine_registers_all_nodes_and_reaches_human_gate():
    async def run():
        engine = WorkflowEngine()
        ctx = await engine.start_run(
            mode=RunMode.MANUAL_SEED,
            admission_mode=AdmissionMode.HUMAN,
            seed_text="你说的对，但是",
        )
        for _ in range(200):
            if ctx.current_state is RunState.WAITING_HUMAN_EVALUATION:
                return ctx
            await asyncio.sleep(0.001)
        return ctx

    context = asyncio.run(run())

    assert context.current_state is RunState.WAITING_HUMAN_EVALUATION
    assert "admission_decision" not in context.node_outputs["N17"]
