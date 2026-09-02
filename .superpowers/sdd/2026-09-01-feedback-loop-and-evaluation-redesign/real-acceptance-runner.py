#!/usr/bin/env python3
"""Drive the authorized real Task 9 acceptance without reading provider secrets.

The backend must already be running with the repository root ``.env`` and the
isolated SQLite URL documented in real-acceptance-instructions.md. This runner
talks only to the local HTTP API, submits complete seven-module evaluations,
and verifies the resulting SQLite audit trail.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

DEFAULT_BASE_URL = "http://127.0.0.1:8765/api/v1"
DEFAULT_DATABASE = Path(
    "/private/tmp/task9-real-acceptance.Eurv7g/acceptance-fixed.db",
)
DEFAULT_RESULT = Path(__file__).with_name("real-acceptance-results.json")
DEFAULT_MANUAL_SEED = (
    "你说的对，但是《原神》是由米哈游自主研发的一款全新开放世界冒险游戏。"
)
TERMINAL_FAILURES = {"FAILED", "TERMINATED", "WAITING_HUMAN_INTERVENTION"}


class AcceptanceError(RuntimeError):
    """Acceptance boundary failed with a sanitized, non-secret message."""


class LocalAPI:
    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = (
            None
            if payload is None
            else json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body else {},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise AcceptanceError(
                f"local API {method} {path} returned HTTP {exc.code}: {detail}",
            ) from exc
        except URLError as exc:
            raise AcceptanceError(
                f"cannot reach the authorized local API at {self.base_url}: {exc.reason}",
            ) from exc
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self.request(path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request(path, method="POST", payload=payload)


def unwrap(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    artifact = value.get("artifact", value)
    if isinstance(artifact, dict) and isinstance(artifact.get("llm"), dict):
        return artifact["llm"]
    return artifact if isinstance(artifact, dict) else {}


def node_output(node: dict[str, Any]) -> dict[str, Any]:
    output = node.get("output")
    return output if isinstance(output, dict) else {}


def latest_node(
    record: dict[str, Any],
    node_key: str,
    *,
    after_order: int = -1,
) -> dict[str, Any]:
    matches = [
        node
        for node in record.get("nodes", [])
        if node.get("node_key") == node_key
        and node.get("status") == "SUCCEEDED"
        and int(node.get("execution_order", -1)) > after_order
    ]
    if not matches:
        raise AcceptanceError(
            f"run record has no successful {node_key} after execution order {after_order}",
        )
    return max(matches, key=lambda node: int(node.get("execution_order", -1)))


def compact_failure(record: dict[str, Any]) -> dict[str, Any]:
    failed = [
        {
            "node_key": node.get("node_key"),
            "error_code": node.get("error_code"),
            "error_message": str(node.get("error_message") or "")[:500],
        }
        for node in record.get("nodes", [])
        if node.get("status") == "FAILED" or node.get("error_message")
    ]
    latest = record.get("nodes", [])[-5:]
    return {
        "run": record.get("run"),
        "failed_nodes": failed[-3:],
        "latest_nodes": [
            {
                "node_key": node.get("node_key"),
                "attempt_no": node.get("attempt_no"),
                "status": node.get("status"),
            }
            for node in latest
        ],
    }


def terminate_if_active(api: LocalAPI, snapshot: dict[str, Any]) -> None:
    if snapshot.get("state") in {
        "COMPLETED",
        "FAILED",
        "TERMINATED",
        "WAITING_HUMAN_INTERVENTION",
    }:
        return
    api.post(
        f"/runs/{snapshot['run_id']}/commands",
        {
            "command_id": str(uuid4()),
            "type": "TERMINATE",
            "expected_run_version": snapshot.get("run_version"),
            "payload": {},
        },
    )


def wait_for_state(
    api: LocalAPI,
    run_id: str,
    wanted: set[str],
    *,
    timeout_seconds: float,
    label: str,
    predicate: Any = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_marker: tuple[Any, Any, Any] | None = None
    snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = api.get(f"/runs/{run_id}")
        marker = (
            snapshot.get("state"),
            snapshot.get("current_node"),
            snapshot.get("run_version"),
        )
        if marker != last_marker:
            print(
                f"[{label}] state={marker[0]} node={marker[1]} version={marker[2]}",
                flush=True,
            )
            last_marker = marker
        state = str(snapshot.get("state"))
        if state in TERMINAL_FAILURES and state not in wanted:
            record = api.get(f"/runs/{run_id}/record")
            raise AcceptanceError(
                json.dumps(
                    compact_failure(record),
                    ensure_ascii=False,
                )
            )
        if state in wanted and (predicate is None or predicate(snapshot)):
            return snapshot
        time.sleep(3)
    if snapshot:
        terminate_if_active(api, snapshot)
    raise AcceptanceError(f"{label} timed out after {timeout_seconds:.0f}s")


def normalized_meme(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:\"'《》()（）]", "", text).lower()


def score_10_to_5(value: Any, default: int = 4) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return max(1, min(5, round(float(value) / 2)))


def safety_status(record: dict[str, Any], *, after_order: int = -1) -> str:
    n16 = unwrap(node_output(latest_node(record, "N16", after_order=after_order)))
    safety: Any = n16.get("content_safety", n16.get("safety"))
    if isinstance(safety, dict):
        safety = safety.get("status", safety.get("result"))
    return str(safety or "UNCERTAIN").upper()


def round_quality(
    record: dict[str, Any],
    *,
    after_order: int = -1,
) -> dict[str, Any]:
    n05_node = latest_node(record, "N05", after_order=after_order)
    n07_node = latest_node(record, "N07", after_order=after_order)
    n09_node = latest_node(record, "N09", after_order=after_order)
    n11_node = latest_node(record, "N11", after_order=after_order)
    n12_node = latest_node(record, "N12", after_order=after_order)
    n13_node = latest_node(record, "N13", after_order=after_order)
    n14_node = latest_node(record, "N14", after_order=after_order)
    n15_node = latest_node(record, "N15", after_order=after_order)
    n05 = unwrap(node_output(n05_node))
    n07 = node_output(n07_node)
    n09 = unwrap(node_output(n09_node))
    n11 = unwrap(node_output(n11_node))
    n12 = unwrap(node_output(n12_node))
    n13_artifact = node_output(n13_node)
    n13 = unwrap(n13_artifact)
    n14 = unwrap(node_output(n14_node))
    n15 = unwrap(node_output(n15_node))

    original = str(n05.get("original_text", ""))
    variants = n09.get("variants", [])
    if n09.get("is_sufficient") is not True:
        raise AcceptanceError("N09 did not mark strict variant evidence sufficient")
    if not isinstance(variants, list) or len(variants) < 3:
        raise AcceptanceError("N09 persisted fewer than three strict variants")
    source_urls: set[str] = set()
    for variant in variants:
        if not isinstance(variant, dict):
            raise AcceptanceError("N09 contains a non-object variant")
        text = str(variant.get("variant_text", ""))
        quote = str(variant.get("evidence_quote", ""))
        url = str(variant.get("source_url", ""))
        if not text or text not in quote or not url or not variant.get("shared_anchor"):
            raise AcceptanceError(
                "N09 variant lacks text, exact quote, URL, or shared anchor"
            )
        if normalized_meme(text) == normalized_meme(original):
            raise AcceptanceError("N09 accepted an exact original reprint as a variant")
        source_urls.add(url)
    if len(source_urls) < 2:
        raise AcceptanceError("N09 variants do not span two independent source URLs")

    coverage = n11.get("coverage")
    if n11.get("decision") != "PASS" or not isinstance(coverage, (int, float)):
        raise AcceptanceError(f"N11 did not pass: {n11}")
    if float(coverage) < 0.8 or float(n11.get("accuracy", 0)) < 4:
        raise AcceptanceError(
            f"N11 quality below gate: coverage={coverage}, accuracy={n11.get('accuracy')}",
        )

    candidates = n12.get("candidates", [])
    candidate_by_id = {
        str(item.get("candidate_id")): item
        for item in candidates
        if isinstance(item, dict)
    }
    if set(candidate_by_id) != {"C1", "C2", "C3", "C4", "C5"}:
        raise AcceptanceError("N12 does not contain exactly C1..C5")
    score_by_id = {
        str(item.get("candidate_id")): item
        for item in n13.get("scores", [])
        if isinstance(item, dict)
    }
    selected_id = str(n14.get("selected_candidate_id", ""))
    selected_score = score_by_id.get(selected_id, {})
    thresholds = n13_artifact.get("minimum_thresholds", {})
    if selected_id not in set(n13.get("qualified_candidate_ids", [])):
        raise AcceptanceError("N14 selected a candidate outside N13 qualified IDs")
    if (
        selected_score.get("qualified") is not True
        or selected_score.get("problems") != []
    ):
        raise AcceptanceError("N13 selected score is unqualified or still has problems")
    for field in (
        "fluency",
        "recognition",
        "agu_fit",
        "humor",
        "rhythm",
        "adaptation_restraint",
        "minimal_replacement_effect",
    ):
        minimum = thresholds.get(field) if isinstance(thresholds, dict) else None
        if minimum is not None and float(selected_score.get(field, -1)) < float(minimum):
            raise AcceptanceError(
                f"N13 selected {field}={selected_score.get(field)} below {minimum}",
            )

    final_text = str(n15.get("final_agu_text", ""))
    selected_text = str(candidate_by_id[selected_id].get("text", ""))
    safety = n15.get("content_safety", n15.get("safety"))
    if isinstance(safety, dict):
        safety = safety.get("status", safety.get("result"))
    if final_text != selected_text:
        raise AcceptanceError("N15 changed the candidate selected by N14")
    if not final_text or "凿" not in final_text or "agu" not in final_text.lower():
        raise AcceptanceError(
            "N15 final text lacks the audited 凿-on-agu action tokens"
        )
    if str(safety or "UNCERTAIN").upper() != "PASS":
        raise AcceptanceError(f"N15 safety is not PASS: {safety}")

    return {
        "after_execution_order": after_order,
        "n07_execution_order": n07_node["execution_order"],
        "n07_strategy_version_id": n07_node.get("strategy_version_id"),
        "n07_applied_directives": n07.get("applied_directives", []),
        "original_text": original,
        "n09_variant_count": len(variants),
        "n09_independent_source_count": len(source_urls),
        "n11_coverage": float(coverage),
        "n11_accuracy": float(n11["accuracy"]),
        "n13_selected_candidate_id": selected_id,
        "n13_selected_score": selected_score,
        "n13_minimum_thresholds": thresholds,
        "n15_title": str(n15.get("title", "")),
        "n15_final_agu_text": final_text,
        "n15_safety": str(safety).upper(),
        "candidate_by_id": candidate_by_id,
        "score_by_id": score_by_id,
    }


def human_evaluation(
    snapshot: dict[str, Any],
    record: dict[str, Any],
    quality: dict[str, Any],
    *,
    low_variant_feedback: bool,
) -> dict[str, Any]:
    score_by_id = quality["score_by_id"]
    candidates: dict[str, dict[str, Any]] = {}
    for candidate_id in ("C1", "C2", "C3", "C4", "C5"):
        score = score_by_id.get(candidate_id, {})
        qualified = score.get("qualified") is True and not score.get("problems")
        candidates[candidate_id] = {
            "fluency": score_10_to_5(score.get("fluency")),
            "original_meme_recognition": score_10_to_5(score.get("recognition")),
            "agu_zao_naturalness": score_10_to_5(score.get("agu_fit")),
            "humor": score_10_to_5(score.get("humor")),
            "template_logic": score_10_to_5(score.get("adaptation_restraint")),
            "usability": "USABLE" if qualified else "USABLE_AFTER_EDIT",
            "modification_advice": "" if qualified else "按 N13 problems 做最小修改",
        }

    selected = quality["n13_selected_score"]
    selected_id = quality["n13_selected_candidate_id"]
    variant_plan = {
        "slot_replacement_targeting": 2 if low_variant_feedback else 4,
        "query_diversity": 3 if low_variant_feedback else 4,
        "ugc_orientation": 2 if low_variant_feedback else 4,
        "noise_avoidance": 2 if low_variant_feedback else 4,
        "comment": (
            "需要排除原句转载，并优先搜索网友真实槽位改编"
            if low_variant_feedback
            else "查询计划已围绕固定锚点和槽位替换"
        ),
    }
    variant_results = {
        "relevance": 3 if low_variant_feedback else 4,
        "real_variant_ratio": 1 if low_variant_feedback else 4,
        "independent_evidence_quality": 2 if low_variant_feedback else 4,
        "variant_diversity": 2 if low_variant_feedback else 4,
        "comment": (
            "第一轮反馈用于验证策略闭环：提高真实变式比例和独立来源质量"
            if low_variant_feedback
            else "严格变式、逐字引文和独立来源满足验收"
        ),
    }
    if snapshot["admission_mode"] == "HUMAN":
        admission = {
            "decision": "ADMIT",
            "reason": "N09/N11/N13/N15 与内容安全均通过真实验收",
        }
    else:
        admission = {
            "override": "OVERRIDE_TO_NOT_ADMIT" if low_variant_feedback else "KEEP",
            "reason": (
                "第一轮保留为策略反馈样本，不正式入库"
                if low_variant_feedback
                else "第二轮沿用 N17 自动准入结论"
            ),
        }
    return {
        "expected_run_version": snapshot["run_version"],
        "branch_id": snapshot["active_branch_id"],
        "original_search_plan": {
            "anchor_accuracy": 4,
            "query_coverage": 4,
            "plan_targeting": 4,
            "comment": "真实 Exa 搜索能定位原句及出处",
        },
        "selected_original_meme": {
            "popularity": 4,
            "applicability": 4,
            "adaptability": 4,
            "evidence_reliability": 4,
            "comment": "原梗有逐字证据且适合结构化改编",
        },
        "variant_search_plan": variant_plan,
        "variant_search_results": variant_results,
        "template_extraction": {
            "accuracy": score_10_to_5(quality["n11_accuracy"] * 2),
            "original_reconstruction": 5,
            "variant_coverage": score_10_to_5(quality["n11_coverage"] * 10),
            "slot_rationality": 4,
            "comment": "N11 确认模板可重建原句并覆盖真实变式",
        },
        "candidate_generation": {
            "overall": {
                "effective_difference": 4,
                "natural_rewrite_coverage": 4,
                "overall_selectable_quality": 4,
                "comment": "五条候选均按统一量表复核",
            },
            "candidates": candidates,
        },
        "final_result": {
            "is_best_candidate": True,
            "better_candidate_id": None,
            "fluency": score_10_to_5(selected.get("fluency")),
            "original_meme_recognition": score_10_to_5(selected.get("recognition")),
            "agu_zao_fit": score_10_to_5(selected.get("agu_fit")),
            "humor": score_10_to_5(selected.get("humor")),
            "overall_satisfaction": 4,
            "comment": f"{selected_id} 保持原梗辨识度且满足凿agu动作受事约束",
        },
        "main_problem_nodes": ["N07", "N09"]
        if low_variant_feedback
        else [
            "NO_OBVIOUS_PROBLEM",
        ],
        "admission": admission,
        "overall_comment": (
            "第一轮低变式评价：形成搜索策略补丁并由下一轮 N07 消费"
            if low_variant_feedback
            else "七模块真实验收完成"
        ),
    }


def submit_evaluation(
    api: LocalAPI,
    snapshot: dict[str, Any],
    record: dict[str, Any],
    quality: dict[str, Any],
    *,
    low_variant_feedback: bool,
) -> dict[str, Any]:
    payload = human_evaluation(
        snapshot,
        record,
        quality,
        low_variant_feedback=low_variant_feedback,
    )
    return api.post(f"/runs/{snapshot['run_id']}/evaluation", payload)


def create_run(
    api: LocalAPI,
    *,
    mode: str,
    admission_mode: str,
    seed_text: str | None,
    continuous: bool,
) -> dict[str, Any]:
    return api.post(
        "/runs",
        {
            "mode": mode,
            "admission_mode": admission_mode,
            "seed_text": seed_text,
            "continuous_enabled": continuous,
        },
    )


def disable_continuous(api: LocalAPI, snapshot: dict[str, Any]) -> dict[str, Any]:
    return api.post(
        f"/runs/{snapshot['run_id']}/commands",
        {
            "command_id": str(uuid4()),
            "type": "SET_CONTINUOUS_EXECUTION",
            "expected_run_version": snapshot["run_version"],
            "payload": {"enabled": False},
        },
    )


def sqlite_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def verify_sqlite(
    database: Path,
    *,
    manual: dict[str, Any],
    auto: dict[str, Any],
) -> dict[str, Any]:
    if not database.is_file():
        raise AcceptanceError(f"SQLite database does not exist: {database}")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        runs = {
            row["id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM run_records WHERE id IN (?, ?)",
                (manual["run_id"], auto["run_id"]),
            )
        }
        if set(runs) != {manual["run_id"], auto["run_id"]}:
            raise AcceptanceError("SQLite is missing a requested run_records row")
        if runs[manual["run_id"]]["status"] != "COMPLETED":
            raise AcceptanceError("MANUAL run main record is not COMPLETED")
        if runs[auto["run_id"]]["status"] != "COMPLETED":
            raise AcceptanceError("AUTO run main record is not COMPLETED")
        if bool(runs[auto["run_id"]]["continuous_enabled"]):
            raise AcceptanceError(
                "AUTO main record did not persist continuous_enabled=false"
            )

        evaluation_counts = {
            row["run_id"]: row["count"]
            for row in connection.execute(
                "SELECT run_id, COUNT(*) AS count FROM run_human_evaluations "
                "WHERE run_id IN (?, ?) GROUP BY run_id",
                (manual["run_id"], auto["run_id"]),
            )
        }
        if evaluation_counts.get(manual["run_id"]) != 1:
            raise AcceptanceError("MANUAL SQLite evaluation count is not 1")
        if evaluation_counts.get(auto["run_id"]) != 2:
            raise AcceptanceError("AUTO SQLite evaluation count is not 2")

        patch_count = connection.execute(
            "SELECT COUNT(*) FROM run_strategy_patches WHERE source_run_id = ?",
            (auto["run_id"],),
        ).fetchone()[0]
        if patch_count != 2:
            raise AcceptanceError(
                f"AUTO SQLite strategy patch count is {patch_count}, not 2"
            )

        latest_n07 = connection.execute(
            "SELECT strategy_version_id, output_json FROM run_node_executions "
            "WHERE run_id = ? AND node_key = 'N07' AND status = 'SUCCEEDED' "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (auto["run_id"],),
        ).fetchone()
        if latest_n07 is None:
            raise AcceptanceError("SQLite is missing AUTO second-round N07")
        n07_output = sqlite_json(latest_n07["output_json"])
        if latest_n07["strategy_version_id"] != auto["feedback_strategy_version_id"]:
            raise AcceptanceError(
                "SQLite N07 strategy_version_id is not the feedback version"
            )
        if not n07_output.get("applied_directives"):
            raise AcceptanceError("SQLite second-round N07 has no applied_directives")

        validated_sources = connection.execute(
            "SELECT COUNT(*) FROM run_source_evidence "
            "WHERE run_id = ? AND evidence_type = 'VALIDATED_VARIANT'",
            (auto["run_id"],),
        ).fetchone()[0]
        if validated_sources < 6:
            raise AcceptanceError(
                "SQLite contains too few validated variants across AUTO rounds"
            )

        api_counts = {
            row["api_type"]: row["count"]
            for row in connection.execute(
                "SELECT api_type, COUNT(*) AS count FROM run_api_calls "
                "WHERE run_id IN (?, ?) GROUP BY api_type",
                (manual["run_id"], auto["run_id"]),
            )
        }
        if api_counts.get("llm", 0) <= 0 or api_counts.get("search", 0) <= 0:
            raise AcceptanceError("SQLite lacks real LLM or Exa API usage rows")

        formal_meme_id = runs[manual["run_id"]]["formal_meme_id"]
        if not formal_meme_id:
            raise AcceptanceError("MANUAL run did not persist a formal meme ID")
        meme = connection.execute(
            "SELECT id, title, final_agu_text, source_run_id FROM meme_records WHERE id = ?",
            (formal_meme_id,),
        ).fetchone()
        if meme is None or meme["source_run_id"] != manual["run_id"]:
            raise AcceptanceError(
                "formal meme row is missing or linked to the wrong run"
            )

        strategy_versions = [
            dict(row)
            for row in connection.execute(
                "SELECT id, version_number, parent_version_id, source_run_id, "
                "source_evaluation_id FROM run_strategy_versions ORDER BY version_number",
            )
        ]
        return {
            "run_statuses": {
                manual["run_id"]: runs[manual["run_id"]]["status"],
                auto["run_id"]: runs[auto["run_id"]]["status"],
            },
            "evaluation_counts": evaluation_counts,
            "auto_patch_count": patch_count,
            "validated_variant_rows": validated_sources,
            "api_call_counts": api_counts,
            "formal_meme": dict(meme),
            "strategy_versions": strategy_versions,
        }
    finally:
        connection.close()


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    api = LocalAPI(args.base_url, timeout=args.request_timeout)
    config = api.get("/system/config")
    safe_config = {
        "llm_provider": config.get("llm_provider"),
        "llm_model": config.get("llm_model"),
        "api_key_configured": bool(config.get("api_key_configured")),
        "search_api_key_configured": bool(config.get("search_api_key_configured")),
    }
    if safe_config["llm_provider"] == "fake" or not safe_config["api_key_configured"]:
        raise AcceptanceError("backend is not configured with a real LLM provider")
    if not safe_config["search_api_key_configured"]:
        raise AcceptanceError("backend has no configured Exa key")
    llm_connection = api.post("/system/connection-tests/llm", {})
    search_connection = api.post("/system/connection-tests/search", {})
    if llm_connection.get("ok") is not True or search_connection.get("ok") is not True:
        raise AcceptanceError("real provider connection test failed")
    print(
        json.dumps(
            {
                "safe_config": safe_config,
                "llm_connection_ok": True,
                "search_connection_ok": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    active_snapshot: dict[str, Any] | None = None
    try:
        manual_created = create_run(
            api,
            mode="MANUAL_SEED",
            admission_mode="HUMAN",
            seed_text=args.manual_seed,
            continuous=False,
        )
        active_snapshot = manual_created
        manual_waiting = wait_for_state(
            api,
            manual_created["run_id"],
            {"WAITING_HUMAN_EVALUATION"},
            timeout_seconds=args.run_timeout,
            label="manual",
        )
        active_snapshot = manual_waiting
        manual_record = api.get(f"/runs/{manual_created['run_id']}/record")
        manual_quality = round_quality(manual_record)
        if safety_status(manual_record) != "PASS":
            raise AcceptanceError("MANUAL N16 safety is not PASS")
        submit_evaluation(
            api,
            manual_waiting,
            manual_record,
            manual_quality,
            low_variant_feedback=False,
        )
        manual_completed = wait_for_state(
            api,
            manual_created["run_id"],
            {"COMPLETED"},
            timeout_seconds=args.run_timeout,
            label="manual-final",
        )
        active_snapshot = None
        manual_final_record = api.get(f"/runs/{manual_created['run_id']}/record")
        manual_usage = api.get(f"/runs/{manual_created['run_id']}/usage")
        if len(manual_final_record.get("evaluations", [])) != 1:
            raise AcceptanceError("MANUAL history API evaluation count is not 1")
        if not manual_final_record["run"].get("formal_meme_id"):
            raise AcceptanceError("MANUAL history API has no formal_meme_id")

        auto_created = create_run(
            api,
            mode="AUTO_DISCOVERY",
            admission_mode="AUTO",
            seed_text=None,
            continuous=True,
        )
        active_snapshot = auto_created
        auto_initial_strategy = auto_created["strategy_version_id"]
        auto_first = wait_for_state(
            api,
            auto_created["run_id"],
            {"WAITING_HUMAN_EVALUATION"},
            timeout_seconds=args.run_timeout,
            label="auto-round-1",
        )
        active_snapshot = auto_first
        auto_first_record = api.get(f"/runs/{auto_created['run_id']}/record")
        auto_first_quality = round_quality(auto_first_record)
        first_round_end_order = max(
            int(node.get("execution_order", -1))
            for node in auto_first_record.get("nodes", [])
        )
        submit_evaluation(
            api,
            auto_first,
            auto_first_record,
            auto_first_quality,
            low_variant_feedback=True,
        )
        auto_second = wait_for_state(
            api,
            auto_created["run_id"],
            {"WAITING_HUMAN_EVALUATION"},
            timeout_seconds=args.run_timeout,
            label="auto-round-2",
            predicate=lambda snapshot: (
                snapshot.get("strategy_version_id") != auto_initial_strategy
            ),
        )
        active_snapshot = auto_second
        feedback_strategy = auto_second["strategy_version_id"]
        auto_second_record = api.get(f"/runs/{auto_created['run_id']}/record")
        auto_second_quality = round_quality(
            auto_second_record,
            after_order=first_round_end_order,
        )
        if auto_second_quality["n07_strategy_version_id"] != feedback_strategy:
            raise AcceptanceError(
                "second-round N07 did not persist feedback strategy ID"
            )
        if not auto_second_quality["n07_applied_directives"]:
            raise AcceptanceError("second-round N07 did not consume applied_directives")
        first_evaluation_id = auto_second_record["evaluations"][0]["evaluation_id"]
        strategy_detail = api.get(f"/strategies/{feedback_strategy}")
        if strategy_detail.get("source_evaluation_id") != first_evaluation_id:
            raise AcceptanceError(
                "feedback strategy does not point to first AUTO evaluation"
            )
        if not strategy_detail.get("patch_operations"):
            raise AcceptanceError("feedback strategy has no persisted patch operations")

        disable_continuous(api, auto_second)
        auto_second = api.get(f"/runs/{auto_created['run_id']}")
        active_snapshot = auto_second
        if auto_second.get("continuous_enabled") is not False:
            raise AcceptanceError(
                "continuous execution was not disabled before round 2 evaluation"
            )
        submit_evaluation(
            api,
            auto_second,
            auto_second_record,
            auto_second_quality,
            low_variant_feedback=False,
        )
        auto_completed = wait_for_state(
            api,
            auto_created["run_id"],
            {"COMPLETED"},
            timeout_seconds=args.run_timeout,
            label="auto-final",
        )
        active_snapshot = None
        auto_final_record = api.get(f"/runs/{auto_created['run_id']}/record")
        auto_usage = api.get(f"/runs/{auto_created['run_id']}/usage")
        if len(auto_final_record.get("evaluations", [])) != 2:
            raise AcceptanceError("AUTO history API evaluation count is not 2")
        if (
            len(
                [
                    node
                    for node in auto_final_record.get("nodes", [])
                    if node.get("node_key") == "N19"
                    and node.get("status") == "SUCCEEDED"
                ]
            )
            != 2
        ):
            raise AcceptanceError(
                "AUTO history API does not contain exactly two N19 nodes"
            )

        manual_summary = {
            "run_id": manual_created["run_id"],
            "state": manual_completed["state"],
            "initial_strategy_version_id": manual_created["strategy_version_id"],
            "final_strategy_version_id": api.get(
                f"/runs/{manual_created['run_id']}",
            ).get("strategy_version_id"),
            "formal_meme_id": manual_final_record["run"]["formal_meme_id"],
            "final_agu_text": manual_quality["n15_final_agu_text"],
            "quality": {
                key: value
                for key, value in manual_quality.items()
                if key not in {"candidate_by_id", "score_by_id"}
            },
            "usage": manual_usage,
        }
        auto_summary = {
            "run_id": auto_created["run_id"],
            "state": auto_completed["state"],
            "initial_strategy_version_id": auto_initial_strategy,
            "feedback_strategy_version_id": feedback_strategy,
            "final_strategy_version_id": auto_completed.get("strategy_version_id"),
            "first_round_final_agu_text": auto_first_quality["n15_final_agu_text"],
            "second_round_final_agu_text": auto_second_quality["n15_final_agu_text"],
            "second_round_quality": {
                key: value
                for key, value in auto_second_quality.items()
                if key not in {"candidate_by_id", "score_by_id"}
            },
            "first_feedback_strategy": {
                "version_number": strategy_detail.get("version_number"),
                "parent_version_id": strategy_detail.get("parent_version_id"),
                "source_evaluation_id": strategy_detail.get("source_evaluation_id"),
                "affected_nodes": strategy_detail.get("affected_nodes"),
                "patch_operations": strategy_detail.get("patch_operations"),
            },
            "usage": auto_usage,
        }
        sqlite_assertions = verify_sqlite(
            args.database,
            manual=manual_summary,
            auto=auto_summary,
        )
        return {
            "safe_config": safe_config,
            "manual": manual_summary,
            "auto": auto_summary,
            "sqlite_assertions": sqlite_assertions,
        }
    except Exception:
        if active_snapshot:
            try:
                latest = api.get(f"/runs/{active_snapshot['run_id']}")
                terminate_if_active(api, latest)
            except Exception as terminate_error:  # noqa: BLE001
                print(
                    f"warning: could not terminate active run: {terminate_error}",
                    file=sys.stderr,
                )
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--manual-seed", default=DEFAULT_MANUAL_SEED)
    parser.add_argument("--run-timeout", type=float, default=1800.0)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_acceptance(args)
    except AcceptanceError as exc:
        print(f"REAL_ACCEPTANCE_FAILED: {exc}", file=sys.stderr)
        return 1
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"REAL_ACCEPTANCE_PASSED result={args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
