from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UnboundedInteger(TypeDecorator):
    """Persist Python integers as decimal text without SQLite's 64-bit limit."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: int | None, dialect: Any) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> int | None:
        return None if value is None else int(value)


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    seed_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    workdir: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    codex_exit_code: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    skill_stop_reason: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    formal_meme_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )


class RunLog(Base):
    __tablename__ = "run_logs"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stream: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FormalMeme(Base):
    __tablename__ = "formal_memes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id"), nullable=False, unique=True, index=True,
    )
    original_title: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_title: Mapped[str] = mapped_column(Text, nullable=False)
    final_text: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING",
    )
    evaluation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    score: Mapped[int] = mapped_column(
        UnboundedInteger(), nullable=False, default=0, server_default="0",
    )
    dynamic_example_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
