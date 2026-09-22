from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

LogSink = Callable[
    [str, str | None, dict[str, Any] | None, str | None],
    Awaitable[None],
]


@dataclass(frozen=True)
class RunnerResult:
    exit_code: int
    duration_seconds: float
    events: Sequence[dict[str, Any]]


@dataclass(frozen=True)
class RunInvocation:
    mode: str
    seed_text: str | None = None
    formal_titles: Sequence[str] = ()
    dynamic_examples: Sequence[dict[str, Any]] = ()


class AgentRunner(Protocol):
    async def run(
        self,
        invocation: RunInvocation,
        workdir: Path,
        log_sink: LogSink,
    ) -> RunnerResult: ...
