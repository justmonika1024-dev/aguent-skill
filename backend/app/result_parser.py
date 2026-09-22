from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ResultError(Exception):
    def __init__(self, code: str, message: str, stop_reason: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stop_reason = stop_reason


class ParsedRunResult(BaseModel):
    raw: dict[str, Any]
    original_title: str
    original_text: str
    final_title: str
    final_text: str


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _stop_reason_list(value: Any) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ""
    return "; ".join(item for item in (_clean(entry) for entry in value) if item)


def _node_artifact(payload: Mapping[str, Any], node_key: str) -> Mapping[str, Any]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        return {}
    for node in nodes:
        item = _mapping(node)
        if item.get("node_key") == node_key:
            return _mapping(item.get("artifact"))
    return {}


def parse_run_result(workdir: Path) -> ParsedRunResult:
    path = workdir / "run-result.json"
    if not path.is_file():
        raise ResultError("OUTPUT_MISSING", "run-result.json is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResultError("OUTPUT_INVALID", f"cannot parse run-result.json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResultError("OUTPUT_INVALID", "run-result.json must contain an object")

    stop = _mapping(payload.get("stop"))
    execution = _mapping(payload.get("execution"))
    ledger = _mapping(payload.get("ledger"))
    final_state = _clean(
        payload.get("final_state")
        or payload.get("status")
        or payload.get("stop_status")
        or stop.get("status")
        or stop.get("state")
        or execution.get("status")
    )
    stop_node = _clean(
        payload.get("stop_node")
        or stop.get("node_key")
        or stop.get("node")
        or execution.get("stop_node")
    )
    if final_state != "WAITING_HUMAN_EVALUATION" or stop_node != "H02":
        stop_reason = _clean(
            payload.get("stop_reason")
            or payload.get("termination_reason")
            or stop.get("reason")
        ) or _stop_reason_list(payload.get("stop_reasons"))
        if not stop_reason:
            stop_reason = f"{stop_node or 'UNKNOWN'} {final_state or 'UNKNOWN'}"
        raise ResultError(
            "SKILL_STOPPED_WITHOUT_RESULT",
            f"Skill stopped at {stop_node or 'UNKNOWN'} with {final_state or 'UNKNOWN'}",
            stop_reason,
        )

    reference = _mapping(
        payload.get("complete_reference")
        or payload.get("complete_original")
        or ledger.get("complete_reference")
    )
    if not reference:
        reference = _mapping(_node_artifact(payload, "O05").get("complete_reference"))
    draft = _mapping(payload.get("final_draft") or ledger.get("final_draft"))
    if not draft:
        draft = _node_artifact(payload, "G06")

    original_text = _clean(
        reference.get("complete_reference_text")
        or reference.get("text")
        or payload.get("original_text")
    )
    final_text = _clean(
        draft.get("text") or draft.get("final_text") or payload.get("final_text")
    )
    if not original_text:
        raise ResultError("OUTPUT_INVALID", "complete original meme text is missing")
    if not final_text:
        raise ResultError("OUTPUT_INVALID", "final meme text is missing")

    original_title = _clean(reference.get("title") or reference.get("hook_text"))
    final_title = _clean(draft.get("title") or draft.get("final_title"))
    return ParsedRunResult(
        raw=payload,
        original_title=original_title or original_text[:80],
        original_text=original_text,
        final_title=final_title or final_text[:80],
        final_text=final_text,
    )


def extract_usage(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    usage: Mapping[str, Any] = {}
    for event in events:
        if event.get("type") == "compact.stage.completed" and isinstance(
            event.get("cumulative_usage"),
            Mapping,
        ):
            usage = event["cumulative_usage"]
        elif event.get("type") == "turn.completed" and isinstance(
            event.get("usage"),
            Mapping,
        ):
            usage = event["usage"]
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "reasoning_tokens": int(
            usage.get("reasoning_tokens", usage.get("reasoning_output_tokens", 0)) or 0
        ),
    }


def extract_compact_metrics(workdir: Path) -> dict[str, int]:
    path = workdir / "metrics.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResultError("METRICS_INVALID", f"cannot parse metrics.json: {exc}") from exc
    token_usage = _mapping(_mapping(payload).get("token_usage"))
    if payload.get("orchestrator_kind") != "PROGRAMMATIC_NO_LLM_PARENT":
        raise ResultError(
            "METRICS_INVALID",
            "metrics.json is not from the programmatic compact orchestrator",
        )
    return {
        "input_tokens": int(token_usage.get("raw_input_tokens", 0) or 0),
        "cached_input_tokens": int(token_usage.get("cached_input_tokens", 0) or 0),
        "output_tokens": int(token_usage.get("output_tokens", 0) or 0),
        "reasoning_tokens": int(token_usage.get("reasoning_output_tokens", 0) or 0),
    }
