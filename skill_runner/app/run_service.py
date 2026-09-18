from __future__ import annotations

import asyncio
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .database import SQLiteRepository
from .models import RunRecord
from .prompt_builder import build_prompt
from .result_parser import ResultError, extract_usage, parse_run_result
from .runners.base import AgentRunner
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
                    )
                    for row in rows
                ]
            prompt = build_prompt(request, titles, examples)
            (workdir / "prompt.md").write_text(prompt, encoding="utf-8")
            run = await self.repository.create_run(
                request.mode.value,
                request.seed_text,
                str(workdir),
                run_id=run_id,
            )
            self._active_task = asyncio.create_task(
                self._execute(run_id, prompt, workdir),
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
        skill_destination = workdir / ".agents/skills/zao-agugent-supervisor"
        workdir.mkdir(parents=True, exist_ok=False)
        await asyncio.to_thread(
            shutil.copytree,
            self.settings.skill_path,
            skill_destination,
            ignore=shutil.ignore_patterns(".git"),
        )
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

    async def _execute(self, run_id: str, prompt: str, workdir: Path) -> None:
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
            runner_result = await self.runner.run(prompt, workdir, log_sink)
            exit_code = runner_result.exit_code
            duration_seconds = max(0, round(runner_result.duration_seconds))
            if exit_code != 0:
                raise ResultError(
                    "CLI_EXIT_NON_ZERO",
                    f"Codex CLI exited with status {exit_code}",
                )

            parsed = parse_run_result(workdir)
            result = self._normalized_result(parsed.raw, parsed)
            usage = extract_usage(runner_result.events)
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
