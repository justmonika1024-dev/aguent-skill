from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .models import Base, FormalMeme, RunLog, RunRecord


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _formal_fields(result: Mapping[str, Any]) -> tuple[str, str, str, str]:
    reference = result.get("complete_reference", {})
    if not isinstance(reference, Mapping):
        reference = {}
    draft = result.get("final_draft", {})
    if not isinstance(draft, Mapping):
        draft = {}
    original_text = _text(
        reference.get("complete_reference_text")
        or reference.get("text")
        or result.get("original_text")
    )
    final_text = _text(draft.get("text") or result.get("final_text"))
    original_title = _text(reference.get("title")) or original_text[:80]
    final_title = _text(draft.get("title")) or final_text[:80]
    return original_title, original_text, final_title, final_text


class SQLiteRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._initialized = False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        async with self._sessions() as session:
            yield session

    async def init(self) -> None:
        if self._initialized:
            return
        database = self.engine.url.database
        if database and database != ":memory:":
            Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self._initialized = True

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def create_run(
        self,
        mode: str,
        seed_text: str | None,
        workdir: str,
        *,
        run_id: str | None = None,
    ) -> RunRecord:
        await self.init()
        values = {
            "mode": mode,
            "seed_text": seed_text,
            "workdir": workdir,
            "status": "PENDING",
        }
        if run_id is not None:
            values["id"] = run_id
        row = RunRecord(**values)
        async with self.session() as session, session.begin():
            session.add(row)
        return row

    async def get_run(self, run_id: str) -> RunRecord | None:
        await self.init()
        async with self.session() as session:
            return await session.get(RunRecord, run_id)

    async def mark_running(self, run_id: str, started_at: datetime) -> None:
        async with self.session() as session, session.begin():
            row = await session.get(RunRecord, run_id)
            if row is None:
                raise KeyError(run_id)
            row.status = "RUNNING"
            row.started_at = started_at

    async def append_log(
        self,
        run_id: str,
        sequence: int,
        stream: str,
        event_type: str | None,
        payload: dict[str, Any] | None,
        raw_text: str | None,
        created_at: datetime | None = None,
    ) -> RunLog:
        row = RunLog(
            run_id=run_id,
            sequence=sequence,
            stream=stream,
            event_type=event_type,
            payload_json=payload,
            raw_text=raw_text,
            created_at=created_at or datetime.now(UTC),
        )
        async with self.session() as session, session.begin():
            session.add(row)
        return row

    async def list_logs(self, run_id: str) -> list[RunLog]:
        async with self.session() as session:
            result = await session.execute(
                select(RunLog)
                .where(RunLog.run_id == run_id)
                .order_by(RunLog.sequence),
            )
            return list(result.scalars())

    async def get_formal_meme_by_run(self, run_id: str) -> FormalMeme | None:
        async with self.session() as session:
            return await session.scalar(
                select(FormalMeme).where(FormalMeme.source_run_id == run_id),
            )

    async def list_formal_titles(self) -> list[str]:
        async with self.session() as session:
            result = await session.scalars(
                select(FormalMeme.final_title).order_by(
                    FormalMeme.created_at, FormalMeme.id,
                ),
            )
            return list(result)

    async def sample_dynamic_examples(self, limit: int) -> list[FormalMeme]:
        if limit <= 0:
            return []
        async with self.session() as session:
            result = await session.execute(
                select(FormalMeme)
                .where(FormalMeme.dynamic_example_eligible.is_(True))
                .order_by(func.random())
                .limit(limit),
            )
            return list(result.scalars())

    async def complete_success(
        self,
        run_id: str,
        result: Mapping[str, Any],
        usage: Mapping[str, int],
        duration_seconds: int,
        exit_code: int,
    ) -> FormalMeme:
        original_title, original_text, final_title, final_text = _formal_fields(result)
        async with self.session() as session, session.begin():
            run = await session.get(RunRecord, run_id)
            if run is None:
                raise KeyError(run_id)
            meme = FormalMeme(
                source_run_id=run_id,
                original_title=original_title,
                original_text=original_text,
                final_title=final_title,
                final_text=final_text,
                evaluation_status="PENDING",
                dynamic_example_eligible=False,
            )
            session.add(meme)
            await session.flush()
            run.status = "WAITING_HUMAN_EVALUATION"
            run.finished_at = datetime.now(UTC)
            run.duration_seconds = duration_seconds
            run.codex_exit_code = exit_code
            run.input_tokens = int(usage.get("input_tokens", 0))
            run.cached_input_tokens = int(usage.get("cached_input_tokens", 0))
            run.output_tokens = int(usage.get("output_tokens", 0))
            run.reasoning_tokens = int(usage.get("reasoning_tokens", 0))
            run.result_json = dict(result)
            run.formal_meme_id = meme.id
        return meme

    async def complete_failure(
        self,
        run_id: str,
        error_code: str,
        error_message: str,
        stop_reason: str | None,
        duration_seconds: int,
        exit_code: int | None,
    ) -> None:
        async with self.session() as session, session.begin():
            run = await session.get(RunRecord, run_id)
            if run is None:
                raise KeyError(run_id)
            run.status = "FAILED"
            run.finished_at = datetime.now(UTC)
            run.duration_seconds = duration_seconds
            run.codex_exit_code = exit_code
            run.error_code = error_code
            run.error_message = error_message
            run.skill_stop_reason = stop_reason
