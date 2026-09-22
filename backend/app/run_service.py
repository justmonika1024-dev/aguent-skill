from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .database import SQLiteRepository
from .models import RunRecord
from .result_parser import (
    ResultError,
    extract_compact_metrics,
    extract_usage,
    parse_run_result,
)
from .runners.base import AgentRunner, RunInvocation
from .schemas import DynamicExample, RunCreate, RunMode


class ActiveRunExists(Exception):
    pass


class RunService:
    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository,
        runner: AgentRunner,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.runner = runner
        self._active_lock = asyncio.Lock()
        self._active_task: asyncio.Task[None] | None = None

    async def start(self, request: RunCreate) -> RunRecord:
        if self._active_lock.locked():
            raise ActiveRunExists("another run is already active")
        await self._active_lock.acquire()
        try:
            run_id = str(uuid4())
            workdir = self.settings.run_root / run_id
            await self._prepare_workdir(workdir)

            titles = await self.repository.list_formal_titles()
            examples = []
            if request.mode is RunMode.AUTO:
                rows = await self.repository.sample_dynamic_examples(
                    self.settings.dynamic_example_count,
                )
                examples = [
                    DynamicExample(
                        original_title=row.original_title,
                        original_text=row.original_text,
                        final_title=row.final_title,
                        final_text=row.final_text,
                        score=row.score,
                    )
                    for row in rows
                ]
            invocation = RunInvocation(
                mode=request.mode.value,
                seed_text=request.seed_text,
                formal_titles=tuple(titles),
                dynamic_examples=tuple(example.model_dump() for example in examples),
            )
            (workdir / "run-input.json").write_text(
                json.dumps(
                    {
                        "mode": invocation.mode,
                        "seed_text": invocation.seed_text,
                        "formal_titles": list(invocation.formal_titles),
                        "dynamic_examples": list(invocation.dynamic_examples),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            run = await self.repository.create_run(
                request.mode.value,
                request.seed_text,
                str(workdir),
                run_id=run_id,
            )
            self._active_task = asyncio.create_task(
                self._execute(run_id, invocation, workdir),
                name=f"skill-run-{run_id}",
            )
            return run
        except BaseException:
            self._active_lock.release()
            raise

    async def wait_for_idle(self) -> None:
        task = self._active_task
        if task is not None:
            await asyncio.shield(task)

    async def _prepare_workdir(self, workdir: Path) -> None:
        workdir.mkdir(parents=True, exist_ok=False)
        process = await asyncio.create_subprocess_exec(
            "git",
            "init",
            "-q",
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"cannot initialize run repository: {message}")

    async def _execute(
        self,
        run_id: str,
        invocation: RunInvocation,
        workdir: Path,
    ) -> None:
        sequence = 0
        sequence_lock = asyncio.Lock()

        async def log_sink(
            stream: str,
            event_type: str | None,
            payload: dict | None,
            raw_text: str | None,
        ) -> None:
            nonlocal sequence
            async with sequence_lock:
                if event_type == "turn.completed" and payload is not None:
                    await self.repository.update_usage(run_id, extract_usage([payload]))
                elif event_type == "compact.stage.completed" and payload is not None:
                    cumulative = payload.get("cumulative_usage")
                    if isinstance(cumulative, dict):
                        await self.repository.update_usage(run_id, cumulative)
                sequence += 1
                await self.repository.append_log(
                    run_id,
                    sequence,
                    stream,
                    event_type,
                    payload,
                    raw_text,
                )

        exit_code: int | None = None
        duration_seconds = 0
        try:
            await self.repository.mark_running(run_id, datetime.now(UTC))
            await log_sink("SYSTEM", "run.started", {"run_id": run_id}, None)
            runner_result = await self.runner.run(invocation, workdir, log_sink)
            exit_code = runner_result.exit_code
            duration_seconds = max(0, round(runner_result.duration_seconds))
            usage = (
                extract_compact_metrics(workdir)
                if (workdir / "metrics.json").is_file()
                else extract_usage(runner_result.events)
            )
            await self.repository.update_usage(run_id, usage)
            parsed = (
                parse_run_result(workdir)
                if (workdir / "run-result.json").is_file()
                else None
            )
            if exit_code != 0:
                raise ResultError(
                    "CLI_EXIT_NON_ZERO",
                    f"Codex CLI exited with status {exit_code}",
                )

            parsed = parsed or parse_run_result(workdir)
            result = self._normalized_result(parsed.raw, parsed)
            await self.repository.complete_success(
                run_id,
                result,
                usage,
                duration_seconds,
                exit_code,
            )
            await log_sink(
                "SYSTEM",
                "run.waiting_human_evaluation",
                {"run_id": run_id, "stop_node": "H02"},
                None,
            )
        except ResultError as exc:
            await self.repository.complete_failure(
                run_id,
                exc.code,
                exc.message,
                exc.stop_reason,
                duration_seconds,
                exit_code,
            )
            await log_sink(
                "SYSTEM",
                "run.failed",
                {"error_code": exc.code, "message": exc.message},
                None,
            )
        except Exception as exc:
            await self.repository.complete_failure(
                run_id,
                "INTERNAL_ERROR",
                str(exc),
                None,
                duration_seconds,
                exit_code,
            )
            await log_sink(
                "SYSTEM",
                "run.failed",
                {"error_code": "INTERNAL_ERROR", "message": str(exc)},
                None,
            )
        finally:
            self._active_task = None
            self._active_lock.release()

    @staticmethod
    def _normalized_result(raw: dict, parsed) -> dict:
        result = deepcopy(raw)
        reference = result.get("complete_reference")
        if not isinstance(reference, dict):
            reference = {}
        reference.update(
            title=parsed.original_title,
            complete_reference_text=parsed.original_text,
        )
        result["complete_reference"] = reference

        draft = result.get("final_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft.update(title=parsed.final_title, text=parsed.final_text)
        result["final_draft"] = draft
        return result
