from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .base import LogSink, RunnerResult


class CodexCliRunner:
    def __init__(self, command: Sequence[str] | None = None) -> None:
        self.command = list(command or ["codex"])

    def build_command(self, workdir: Path) -> list[str]:
        return [
            *self.command,
            "exec",
            "--ephemeral",
            "--disable",
            "memories",
            "--approve-for-me",
            "--json",
            "-C",
            str(workdir),
            "-c",
            'mcp_servers.playwright.command="npx"',
            "-c",
            'mcp_servers.playwright.args=["-y","@playwright/mcp@latest","--isolated"]',
            "-c",
            'mcp_servers.playwright.default_tools_approval_mode="approve"',
            "-",
        ]

    async def run(self, prompt: str, workdir: Path, log_sink: LogSink) -> RunnerResult:
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *self.build_command(workdir),
            cwd=workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

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
