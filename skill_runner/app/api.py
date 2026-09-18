from __future__ import annotations

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


def create_app(settings: Settings, runner: AgentRunner | None = None) -> FastAPI:
    repository = SQLiteRepository(settings.database_url)
    selected_runner = runner or CodexCliRunner([settings.codex_command])
    service = RunService(settings, repository, selected_runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await repository.init()
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
