from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from .config import Settings
from .database import SQLiteRepository
from .run_service import ActiveRunExists, RunService
from .runners.base import AgentRunner
from .runners.codex_cli import CodexCliRunner
from .schemas import RunAccepted, RunCreate
from .seed_data import CURATED_EXAMPLES


def create_app(settings: Settings, runner: AgentRunner | None = None) -> FastAPI:
    repository = SQLiteRepository(settings.database_url)
    selected_runner = runner or CodexCliRunner([settings.codex_command])
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

    return app


def _validate_environment(settings: Settings, *, check_codex_command: bool) -> None:
    if not (settings.skill_path / "SKILL.md").is_file():
        raise RuntimeError(f"SKILL_PATH does not contain SKILL.md: {settings.skill_path}")
    try:
        settings.run_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.run_root):
            pass
    except OSError as exc:
        raise RuntimeError(f"RUN_ROOT is not writable: {settings.run_root}") from exc
    if check_codex_command and shutil.which(settings.codex_command) is None:
        raise RuntimeError(f"CODEX_COMMAND is not executable: {settings.codex_command}")
