from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, status
from fastapi.responses import JSONResponse

from .config import Settings
from .database import SQLiteRepository
from .run_status import build_run_status
from .run_service import ActiveRunExists, RunService
from .runners.base import AgentRunner
from .runners.compact_round import CompactRoundRunner
from .schemas import (
    EvaluationCreate,
    EvaluationResult,
    FormalMemeItem,
    FormalMemePage,
    Pagination,
    RunAccepted,
    RunCreate,
    RunStatus,
)
from .seed_data import CURATED_EXAMPLES


def create_app(settings: Settings, runner: AgentRunner | None = None) -> FastAPI:
    repository = SQLiteRepository(settings.database_url)
    selected_runner = runner or CompactRoundRunner(
        settings.skill_path,
        settings.codex_command,
    )
    service = RunService(settings, repository, selected_runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _validate_environment(settings, check_codex_command=runner is None)
        await repository.init()
        await repository.seed_completed_runs(CURATED_EXAMPLES, settings.run_root)
        try:
            yield
        finally:
            await service.wait_for_idle()
            await repository.dispose()

    app = FastAPI(title="凿agugent Skill Runner", lifespan=lifespan)
    app.state.repository = repository
    app.state.run_service = service

    @app.post(
        "/api/runs",
        response_model=RunAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_run(request: RunCreate) -> RunAccepted | JSONResponse:
        try:
            run = await service.start(request)
        except ActiveRunExists:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": {
                        "code": "ACTIVE_RUN_EXISTS",
                        "message": "another run is active",
                    },
                },
            )
        return RunAccepted(run_id=run.id, status=run.status)

    @app.get("/api/runs/{run_id}", response_model=RunStatus)
    async def get_run_status(run_id: str) -> RunStatus | JSONResponse:
        run = await repository.get_run(run_id)
        if run is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": {
                        "code": "RUN_NOT_FOUND",
                        "message": "run was not found",
                    },
                },
            )
        logs = await repository.list_logs(run_id)
        return await build_run_status(run, logs)

    @app.post(
        "/api/runs/{run_id}/evaluation",
        response_model=EvaluationResult,
    )
    async def evaluate_run(
        run_id: str,
        request: EvaluationCreate,
    ) -> EvaluationResult | JSONResponse:
        run = await repository.get_run(run_id)
        if run is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": {
                        "code": "RUN_NOT_FOUND",
                        "message": "run was not found",
                    },
                },
            )
        meme = await repository.score_formal_meme(run_id, request.score)
        if meme is None:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": {
                        "code": "FORMAL_MEME_NOT_READY",
                        "message": "run has no formal meme to evaluate",
                    },
                },
            )
        return EvaluationResult(
            run_id=run_id,
            score=meme.score,
            evaluation_status=meme.evaluation_status,
            dynamic_example_eligible=meme.dynamic_example_eligible,
        )

    @app.get("/api/formal-memes", response_model=FormalMemePage)
    async def list_formal_memes(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> FormalMemePage:
        rows, total = await repository.list_formal_memes_page(page, page_size)
        return FormalMemePage(
            items=[FormalMemeItem.model_validate(row) for row in rows],
            pagination=Pagination(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=(total + page_size - 1) // page_size,
            ),
        )

    return app


def _validate_environment(settings: Settings, *, check_codex_command: bool) -> None:
    if not (settings.skill_path / "SKILL.md").is_file():
        raise RuntimeError(f"SKILL_PATH does not contain SKILL.md: {settings.skill_path}")
    if check_codex_command and not (
        settings.skill_path / "scripts" / "compact_round_runner.py"
    ).is_file():
        raise RuntimeError(
            "SKILL_PATH does not contain scripts/compact_round_runner.py: "
            f"{settings.skill_path}"
        )
    try:
        settings.run_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.run_root):
            pass
    except OSError as exc:
        raise RuntimeError(f"RUN_ROOT is not writable: {settings.run_root}") from exc
    if check_codex_command and shutil.which(settings.codex_command) is None:
        raise RuntimeError(f"CODEX_COMMAND is not executable: {settings.codex_command}")
