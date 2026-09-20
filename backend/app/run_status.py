from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import RunLog, RunRecord
from .schemas import RunArtifact, RunError, RunStatus, RunTokenUsage


TERMINAL_STATUSES = {"WAITING_HUMAN_EVALUATION", "FAILED"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _artifact(value: Any, *, text_keys: tuple[str, ...]) -> RunArtifact | None:
    payload = _mapping(value)
    text = next((_text(payload.get(key)) for key in text_keys if _text(payload.get(key))), "")
    if not text:
        return None
    title = _text(payload.get("title")) or text[:80]
    return RunArtifact(title=title, text=text)


def _template(result: Mapping[str, Any]) -> str | None:
    direct = _text(result.get("template"))
    if direct:
        return direct
    for package_key in (
        "template_package",
        "template_hypothesis",
        "long_form_package",
        "adaptation_blueprint",
    ):
        package = _mapping(result.get(package_key))
        for field in ("template", "skeleton", "macro_skeleton", "structure_template"):
            value = _text(package.get(field))
            if value:
                return value
    return None


def _read_progress(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _elapsed_seconds(run: RunRecord, now: datetime) -> int:
    if run.duration_seconds is not None and run.status in TERMINAL_STATUSES:
        return max(0, run.duration_seconds)
    started = run.started_at or run.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0, round((now - started).total_seconds()))


def _latest_agent_message(logs: list[RunLog]) -> str:
    for log in reversed(logs):
        payload = _mapping(log.payload_json)
        item = _mapping(payload.get("item"))
        if item.get("type") == "agent_message":
            message = _text(item.get("text"))
            if message:
                return message
    return ""


async def build_run_status(run: RunRecord, logs: list[RunLog]) -> RunStatus:
    progress = await asyncio.to_thread(
        _read_progress,
        Path(run.workdir) / "progress.json",
    )
    result = _mapping(run.result_json)

    original = _artifact(
        progress.get("original_meme"),
        text_keys=("text", "complete_reference_text"),
    ) or _artifact(
        result.get("complete_reference"),
        text_keys=("complete_reference_text", "text"),
    )
    formal = _artifact(
        progress.get("formal_meme"),
        text_keys=("text", "final_text"),
    ) or _artifact(
        result.get("final_draft"),
        text_keys=("text", "final_text"),
    )
    template = _text(progress.get("template")) or _template(result)

    if run.status == "WAITING_HUMAN_EVALUATION":
        latest_activity = "任务已到达人工评价阶段。"
    elif run.status == "FAILED":
        latest_activity = "任务执行失败。"
    else:
        latest_activity = (
            _latest_agent_message(logs)
            or _text(progress.get("latest_activity"))
            or ("任务等待执行。" if run.status == "PENDING" else "任务正在启动。")
        )

    usage = RunTokenUsage(
        input_tokens=run.input_tokens,
        cached_input_tokens=run.cached_input_tokens,
        output_tokens=run.output_tokens,
        reasoning_tokens=run.reasoning_tokens,
        total_tokens=run.input_tokens + run.output_tokens,
        finalized=run.status in TERMINAL_STATUSES,
    )
    error = None
    if run.error_code and run.error_message:
        error = RunError(code=run.error_code, message=run.error_message)

    return RunStatus(
        run_id=run.id,
        mode=run.mode,
        status=run.status,
        elapsed_seconds=_elapsed_seconds(run, datetime.now(UTC)),
        started_at=run.started_at,
        finished_at=run.finished_at,
        latest_activity=latest_activity,
        token_usage=usage,
        original_meme=original,
        template=template,
        formal_meme=formal,
        error=error,
        stop_reason=run.skill_stop_reason,
    )
