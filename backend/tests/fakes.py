import json
from pathlib import Path

import anyio

from app.runners.base import RunnerResult


class FakeRunner:
    def __init__(
        self,
        result_payload=None,
        *,
        exit_code=0,
        blocked=False,
        compact_usage=False,
    ):
        self.result_payload = result_payload
        self.exit_code = exit_code
        self.blocked = blocked
        self.compact_usage = compact_usage
        self.started = anyio.Event()
        self.release = anyio.Event()
        self.calls = []

    async def run(self, invocation, workdir: Path, log_sink):
        self.calls.append((invocation, workdir))
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
        if self.compact_usage:
            compact_event = {
                "type": "compact.stage.completed",
                "stage": "FINAL",
                "cumulative_usage": {
                    "input_tokens": 484842,
                    "cached_input_tokens": 390272,
                    "output_tokens": 8412,
                    "reasoning_tokens": 2103,
                },
            }
            await log_sink(
                "STDOUT",
                "compact.stage.completed",
                compact_event,
                None,
            )
            (workdir / "metrics.json").write_text(
                json.dumps(
                    {
                        "orchestrator_kind": "PROGRAMMATIC_NO_LLM_PARENT",
                        "token_usage": {
                            "raw_input_tokens": 484842,
                            "cached_input_tokens": 390272,
                            "output_tokens": 8412,
                            "reasoning_output_tokens": 2103,
                        },
                    }
                ),
                encoding="utf-8",
            )
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
