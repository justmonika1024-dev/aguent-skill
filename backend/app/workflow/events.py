from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class Event:
    type: str
    run_id: str
    run_version: int
    state: str
    payload: dict[str, Any] = field(default_factory=dict)
    branch_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    sequence: int = 0
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["occurred_at"] = self.occurred_at.isoformat()
        d["human_message"] = d["payload"].get("human_message")
        return d

    def sse(self) -> str:
        return f"id: {self.sequence}\nevent: {self.type}\ndata: {json.dumps(self.as_dict(), ensure_ascii=False)}\n\n"


class EventBus:
    def __init__(self, max_events: int = 1000) -> None:
        self.events: deque[Event] = deque(maxlen=max_events)
        self._sequence = 0
        self._wake = asyncio.Condition()

    async def publish(self, event: Event) -> Event:
        async with self._wake:
            self._sequence += 1
            event.sequence = self._sequence
            self.events.append(event)
            self._wake.notify_all()
        return event

    def since(self, sequence: int = 0) -> tuple[list[Event], bool]:
        events = list(self.events)
        if not events:
            return [], False
        reset = sequence < events[0].sequence - 1
        return [e for e in events if e.sequence > sequence], reset

    async def subscribe(self, last_event_id: int = 0) -> AsyncIterator[Event]:
        cursor = last_event_id
        while True:
            batch, reset = self.since(cursor)
            if reset:
                events = list(self.events)
                yield Event("stream.reset", events[0].run_id if events else "", 0, "", {"reason": "buffer_exceeded"})
                cursor = self.events[-1].sequence if self.events else cursor
            for event in batch:
                cursor = event.sequence
                yield event
            async with self._wake:
                await self._wake.wait()


@dataclass(slots=True)
class Command:
    type: str
    command_id: str = field(default_factory=lambda: str(uuid4()))
    expected_run_version: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class CommandQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Command] = asyncio.Queue()
        self._seen: dict[str, Any] = {}

    async def put(self, command: Command) -> Any:
        if command.command_id in self._seen:
            return self._seen[command.command_id]
        await self._queue.put(command)
        return None

    async def get(self) -> Command:
        return await self._queue.get()

    def remember(self, command_id: str, result: Any) -> None:
        self._seen[command_id] = result
