from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from .base import LogSink, RunInvocation, RunnerResult


SUBPROCESS_STREAM_LIMIT = 8 * 1024 * 1024


class CompactRoundRunner:
    def __init__(
        self,
        skill_path: Path,
        codex_command: str,
        *,
        python_command: str | None = None,
    ) -> None:
        self.skill_path = skill_path.resolve()
        self.codex_command = codex_command
        self.python_command = python_command or sys.executable

    def build_command(
        self,
        invocation: RunInvocation,
        workdir: Path,
        examples_path: Path | None,
    ) -> list[str]:
        command = [
            self.python_command,
            str(self.skill_path / "scripts" / "compact_round_runner.py"),
            "--mode",
            invocation.mode,
            "--workdir",
            str(workdir),
            "--skill-root",
            str(self.skill_path),
            "--codex-command",
            self.codex_command,
        ]
        if invocation.seed_text is not None:
            command.extend(["--seed", invocation.seed_text])
        for title in invocation.formal_titles:
            command.extend(["--formal-title", title])
        if examples_path is not None:
            command.extend(["--dynamic-examples-json", str(examples_path)])
        return command

    async def run(
        self,
        invocation: RunInvocation,
        workdir: Path,
        log_sink: LogSink,
    ) -> RunnerResult:
        started = time.monotonic()
        resolved_workdir = workdir.resolve()
        examples_path = None
        if invocation.dynamic_examples:
            examples_path = resolved_workdir / "dynamic-examples.json"
            examples_path.write_text(
                json.dumps(
                    list(invocation.dynamic_examples),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        process = await asyncio.create_subprocess_exec(
            *self.build_command(invocation, resolved_workdir, examples_path),
            cwd=resolved_workdir,
            limit=SUBPROCESS_STREAM_LIMIT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        events: list[dict[str, Any]] = []

        async def consume(stream: asyncio.StreamReader, stream_name: str) -> None:
            while line_bytes := await stream.readline():
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                if stream_name == "STDOUT":
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        events.append(payload)
                        event_type = payload.get("type")
                        await log_sink(
                            stream_name,
                            event_type if isinstance(event_type, str) else None,
                            payload,
                            None,
                        )
                        continue
                await log_sink(stream_name, None, None, line)

        await asyncio.gather(
            consume(process.stdout, "STDOUT"),
            consume(process.stderr, "STDERR"),
        )
        exit_code = await process.wait()
        return RunnerResult(
            exit_code=exit_code,
            duration_seconds=time.monotonic() - started,
            events=events,
        )
