from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        def __str__(self) -> str:
            return self.value
from typing import Any
from uuid import uuid4


class RunMode(StrEnum):
    MANUAL_SEED = "MANUAL_SEED"
    AUTO_DISCOVERY = "AUTO_DISCOVERY"


class AdmissionMode(StrEnum):
    HUMAN = "HUMAN"
    AUTO = "AUTO"


class RunState(StrEnum):
    WAITING_START = "WAITING_START"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    WAITING_HUMAN_EVALUATION = "WAITING_HUMAN_EVALUATION"
    WAITING_HUMAN_INTERVENTION = "WAITING_HUMAN_INTERVENTION"
    ARCHIVING = "ARCHIVING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


def utcnow() -> datetime:
    return datetime.now(UTC)


class RuntimeStrategySnapshot(dict[str, Any]):
    """Strategy data plus run-local state that must not enter persisted JSON."""

    def __init__(
        self,
        value: dict[str, Any],
        loop_counters: dict[str, int],
        exhausted_originals: list[str],
    ) -> None:
        super().__init__(value)
        self.loop_counters = loop_counters
        self.exhausted_originals = exhausted_originals

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return deepcopy(dict(self), memo)


@dataclass
class RunContext:
    run_id: str = field(default_factory=lambda: str(uuid4()))
    mode: RunMode = RunMode.MANUAL_SEED
    admission_mode: AdmissionMode = AdmissionMode.HUMAN
    seed_text: str | None = None
    continuous_enabled: bool = False
    current_node: str = "START"
    current_state: RunState = RunState.WAITING_START
    suspended_state: RunState | None = None
    run_version: int = 0
    active_branch_id: str = field(default_factory=lambda: str(uuid4()))
    branches: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_artifacts: dict[str, Any] = field(default_factory=dict)
    strategy_version_id: str | None = None
    strategy_snapshot: dict[str, Any] = field(default_factory=dict)
    loop_counters: dict[str, int] = field(default_factory=dict)
    exhausted_originals: list[str] = field(default_factory=list)
    pause_requested: bool = False
    terminate_requested: bool = False
    retry_available: bool = False
    pending_human_action: Any = None
    event_buffer: list[Any] = field(default_factory=list)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        self.strategy_snapshot = RuntimeStrategySnapshot(
            self.strategy_snapshot, self.loop_counters, self.exhausted_originals,
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if (name == "strategy_snapshot" and isinstance(value, dict)
                and not isinstance(value, RuntimeStrategySnapshot)
                and "loop_counters" in self.__dict__
                and "exhausted_originals" in self.__dict__):
            value = RuntimeStrategySnapshot(
                value, self.loop_counters, self.exhausted_originals,
            )
        super().__setattr__(name, value)

    @property
    def state(self) -> RunState:
        return self.current_state

    @state.setter
    def state(self, value: RunState | str) -> None:
        self.current_state = RunState(value)

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "run_version": self.run_version,
            "mode": self.mode.value, "admission_mode": self.admission_mode.value,
            "seed_text": self.seed_text, "continuous_enabled": self.continuous_enabled,
            "current_node": self.current_node, "state": self.current_state.value,
            "active_branch_id": self.active_branch_id,
            "strategy_version_id": self.strategy_version_id,
            "strategy_snapshot": deepcopy(self.strategy_snapshot),
            "loop_counters": deepcopy(self.loop_counters),
            "exhausted_originals": deepcopy(self.exhausted_originals),
            "retry_available": self.retry_available,
        }

    to_snapshot = snapshot
