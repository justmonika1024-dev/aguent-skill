import json
from pathlib import Path

import anyio

from app.runners.base import RunnerResult


class FakeRunner:
    def __init__(self, result_payload=None, *, exit_code=0, blocked=False):
        self.result_payload = result_payload
        self.exit_code = exit_code
        self.blocked = blocked
        self.started = anyio.Event()
        self.release = anyio.Event()
        self.calls = []

    async def run(self, prompt, workdir: Path, log_sink):
        self.calls.append((prompt, workdir))
        self.started.set()
        if self.blocked:
            await self.release.wait()
        event = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 8,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
            },
        }
        await log_sink("STDOUT", "turn.completed", event, None)
        await log_sink("STDERR", None, None, "fixture stderr")
        if self.result_payload is not None:
            (workdir / "run-result.json").write_text(
                json.dumps(self.result_payload, ensure_ascii=False), encoding="utf-8",
            )
        return RunnerResult(exit_code=self.exit_code, duration_seconds=2.4, events=[event])


VALID_RESULT = {
    "final_state": "WAITING_HUMAN_EVALUATION",
    "stop_node": "H02",
    "complete_reference": {
        "title": "何以解忧",
        "complete_reference_text": "何以解忧？唯有杜康。",
    },
    "template_package": {
        "template": "何以{S1}？唯有{S2}。",
    },
    "final_draft": {
        "title": "何以解忧？唯有凿agu。",
        "text": "何以解忧？唯有凿agu。",
    },
}
