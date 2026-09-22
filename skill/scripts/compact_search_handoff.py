#!/usr/bin/env python3
"""Build a bounded search handoff and total Codex child-session usage."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


MAX_VARIANTS = 5
MAX_PACKAGE_BYTES = 16 * 1024
PUNCTUATION_RE = re.compile(r"[\s，。！？；：、,.!?;:‘’“”'\"（）()《》〈〉【】\[\]—…·]+")


class HandoffError(ValueError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"expected JSON object: {path}")
    return value


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    return PUNCTUATION_RE.sub("", normalized)


def require_text(record: dict[str, Any], field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{label}.{field} must be non-empty text")
    return value.strip()


def compact_query(record: dict[str, Any]) -> dict[str, str]:
    return {
        "query": require_text(record, "query", "query"),
        "purpose": str(record.get("purpose") or "").strip(),
        "outcome": str(record.get("outcome") or "").strip(),
    }


def source_from_variant(record: dict[str, Any], label: str) -> dict[str, str]:
    return {
        "url": require_text(record, "source_url", label),
        "title": require_text(record, "source_title", label),
        "locator": require_text(record, "locator", label),
        "content_group": require_text(record, "content_group", label),
    }


def normalized_source_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def canonicalize_content_groups(variant_sets: list[list[dict[str, Any]]]) -> None:
    """Merge model-reported groups that resolve to the same source page."""

    parents: dict[str, str] = {}

    def find(node: str) -> str:
        parents.setdefault(node, node)
        while parents[node] != node:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    sources = [
        source
        for variants in variant_sets
        for variant in variants
        for source in variant["sources"]
    ]
    for source in sources:
        union(f"group:{source['content_group']}", f"url:{normalized_source_url(source['url'])}")

    canonical_by_root: dict[str, str] = {}
    for source in sources:
        reported = source["content_group"]
        root = find(f"group:{reported}")
        canonical = canonical_by_root.setdefault(root, f"CG{len(canonical_by_root) + 1:02d}")
        source["reported_content_group"] = reported
        source["content_group"] = canonical


def calculate_difference_coverage(original: str, variants: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[int, int, str], dict[str, Any]] = {}
    for variant in variants:
        text = variant["verbatim_text"]
        matcher = difflib.SequenceMatcher(a=original, b=text, autojunk=False)
        for tag, a_start, a_end, b_start, b_end in matcher.get_opcodes():
            if tag == "equal":
                continue
            original_text = original[a_start:a_end]
            observed_value = text[b_start:b_end]
            key = (a_start, a_end, original_text)
            entry = grouped.setdefault(
                key,
                {
                    "original_start": a_start,
                    "original_end": a_end,
                    "original_text": original_text,
                    "observed_values": [],
                    "variant_refs": [],
                },
            )
            if observed_value not in entry["observed_values"]:
                entry["observed_values"].append(observed_value)
            entry["variant_refs"].append(variant["variant_id"])
    spans = sorted(grouped.values(), key=lambda item: (item["original_start"], item["original_end"]))
    return {
        "method": "PROGRAMMATIC_SEQUENCE_DIFF",
        "observed_change_spans": spans,
        "requires_supervisor_value_review": True,
        "review_question": "这些真实变化是否覆盖了对凿agu生成最有价值的动作、事件、角色或判断位置？",
        "warning": "差异覆盖只描述观察事实，不是模板，也不证明未变化文字不可成为槽位。",
    }


def compact_versions(
    boundary: dict[str, Any],
    original: str,
    original_source: dict[str, str],
) -> tuple[list[dict[str, Any]], str]:
    records = boundary.get("versions")
    selected_ref = str(boundary.get("selected_version_ref") or "").strip()
    if not isinstance(records, list) or not records:
        return [
            {
                "version_ref": "SELECTED",
                "text": original,
                "relationship": "WORDING_VARIANT",
                "closure_reason": str(boundary.get("closure_reason") or "").strip(),
                "source": {
                    "title": original_source["title"],
                    "url": original_source["url"],
                    "locator": original_source["locator"],
                },
            }
        ], "SELECTED"

    compacted: list[dict[str, Any]] = []
    for index, record in enumerate(records[:3]):
        if not isinstance(record, dict):
            raise HandoffError(f"boundary.versions[{index}] must be an object")
        source = record.get("source")
        if not isinstance(source, dict):
            raise HandoffError(f"boundary.versions[{index}].source must be an object")
        compacted.append(
            {
                "version_ref": require_text(record, "version_ref", f"boundary.versions[{index}]"),
                "text": require_text(record, "text", f"boundary.versions[{index}]"),
                "relationship": require_text(record, "relationship", f"boundary.versions[{index}]"),
                "closure_reason": str(record.get("closure_reason") or "").strip(),
                "source": {
                    "title": require_text(source, "title", f"boundary.versions[{index}].source"),
                    "url": require_text(source, "url", f"boundary.versions[{index}].source"),
                    "locator": require_text(source, "locator", f"boundary.versions[{index}].source"),
                },
            }
        )
    selected = next((item for item in compacted if item["version_ref"] == selected_ref), None)
    if selected is None:
        raise HandoffError("boundary.selected_version_ref must reference boundary.versions")
    if selected["text"] != original:
        raise HandoffError("boundary.complete_reference_text must equal selected version text")
    if normalized_source_url(selected["source"]["url"]) != normalized_source_url(
        original_source["url"]
    ):
        raise HandoffError("selected version source must match boundary.source")
    return compacted, selected_ref


def build_package(boundary: dict[str, Any], workers: list[dict[str, Any]]) -> dict[str, Any]:
    if boundary.get("status") != "VERIFIED":
        raise HandoffError("boundary.status must be VERIFIED")
    original = require_text(boundary, "complete_reference_text", "boundary")
    boundary_source = boundary.get("source")
    if not isinstance(boundary_source, dict):
        raise HandoffError("boundary.source must be an object")
    original_source = {
        "title": require_text(boundary_source, "title", "boundary.source"),
        "url": require_text(boundary_source, "url", "boundary.source"),
        "locator": require_text(boundary_source, "locator", "boundary.source"),
        "verbatim_text": original,
    }
    versions, selected_version_ref = compact_versions(boundary, original, original_source)

    by_normalized: dict[str, dict[str, Any]] = {}
    rhythm_by_normalized: dict[str, dict[str, Any]] = {}
    queries: list[dict[str, str]] = []
    rejected_counts: dict[str, int] = {}
    for worker_index, worker in enumerate(workers):
        if worker.get("status") != "EVIDENCE_FOUND":
            raise HandoffError(f"worker[{worker_index}].status must be EVIDENCE_FOUND")
        worker_reference = require_text(
            worker,
            "complete_reference_text",
            f"worker[{worker_index}]",
        )
        if worker_reference != original:
            raise HandoffError(
                f"worker[{worker_index}].complete_reference_text must match boundary"
            )
        integrity = worker.get("integrity")
        if not isinstance(integrity, dict) or integrity.get("source_body_verified") is not True:
            raise HandoffError(
                f"worker[{worker_index}].integrity.source_body_verified must be true"
            )
        for query in worker.get("queries", []):
            if isinstance(query, dict) and query.get("query"):
                queries.append(compact_query(query))
        for key, count in (worker.get("rejected_counts") or {}).items():
            if isinstance(count, int):
                rejected_counts[str(key)] = rejected_counts.get(str(key), 0) + count
        accepted = worker.get("accepted_variants") or []
        if not isinstance(accepted, list):
            raise HandoffError(f"worker[{worker_index}].accepted_variants must be a list")
        for variant_index, record in enumerate(accepted):
            if not isinstance(record, dict):
                raise HandoffError(f"worker[{worker_index}].accepted_variants[{variant_index}] must be an object")
            label = f"worker[{worker_index}].accepted_variants[{variant_index}]"
            text = require_text(record, "verbatim_text", label)
            normalized = normalize_text(text)
            if normalized == normalize_text(original):
                rejected_counts["ORIGINAL_REPOST"] = rejected_counts.get("ORIGINAL_REPOST", 0) + 1
                continue
            source = source_from_variant(record, label)
            existing = by_normalized.get(normalized)
            if existing:
                if source not in existing["sources"]:
                    existing["sources"].append(source)
                continue
            by_normalized[normalized] = {
                "variant_id": f"V{len(by_normalized) + 1:02d}",
                "verbatim_text": text,
                "sources": [source],
                "acceptance_reason": str(record.get("acceptance_reason") or "").strip(),
                "evidence_kind": "SOURCE_BODY_VERBATIM",
            }

        rhythm = worker.get("rhythm_variants") or []
        if not isinstance(rhythm, list):
            raise HandoffError(f"worker[{worker_index}].rhythm_variants must be a list")
        for variant_index, record in enumerate(rhythm):
            if not isinstance(record, dict):
                raise HandoffError(f"worker[{worker_index}].rhythm_variants[{variant_index}] must be an object")
            label = f"worker[{worker_index}].rhythm_variants[{variant_index}]"
            text = require_text(record, "verbatim_text", label)
            normalized = normalize_text(text)
            if normalized == normalize_text(original) or normalized in by_normalized:
                continue
            source = source_from_variant(record, label)
            existing = rhythm_by_normalized.get(normalized)
            if existing:
                if source not in existing["sources"]:
                    existing["sources"].append(source)
                continue
            rhythm_by_normalized[normalized] = {
                "variant_id": f"R{len(rhythm_by_normalized) + 1:02d}",
                "verbatim_text": text,
                "sources": [source],
                "acceptance_reason": str(record.get("acceptance_reason") or "").strip(),
                "evidence_kind": "SOURCE_BODY_VERBATIM_RHYTHM",
            }

    variants = list(by_normalized.values())[:MAX_VARIANTS]
    rhythm_variants = list(rhythm_by_normalized.values())[:MAX_VARIANTS]
    canonicalize_content_groups([variants, rhythm_variants])
    package = {
        "schema_version": "compact-search-handoff-v1",
        "status": "READY_FOR_SUPERVISOR" if variants or rhythm_variants else "INSUFFICIENT",
        "complete_reference": {
            "hook_text": str(boundary.get("hook_text") or "").strip(),
            "complete_reference_text": original,
            "boundary_start": str(boundary.get("boundary_start") or "").strip(),
            "boundary_end": str(boundary.get("boundary_end") or "").strip(),
            "closure_reason": str(boundary.get("closure_reason") or "").strip(),
            "source": original_source,
            "versions": versions,
            "selected_version_ref": selected_version_ref,
        },
        "accepted_variants": variants,
        "rhythm_variants": rhythm_variants,
        "difference_coverage": calculate_difference_coverage(original, variants),
        "queries": queries,
        "evidence_totals": {
            "non_duplicate_variants": len(variants),
            "content_groups": len(
                {source["content_group"] for variant in variants for source in variant["sources"]}
            ),
            "source_records": sum(len(variant["sources"]) for variant in variants),
            "rhythm_variants": len(rhythm_variants),
            "rhythm_content_groups": len(
                {source["content_group"] for variant in rhythm_variants for source in variant["sources"]}
            ),
            "rhythm_source_records": sum(len(variant["sources"]) for variant in rhythm_variants),
        },
        "rejected_counts": rejected_counts,
        "integrity": {
            "search_snippets_are_evidence": False,
            "retrieval_hypotheses_are_evidence": False,
            "page_bodies_included": False,
            "supervisor_must_recheck_variant_classification": True,
        },
    }
    encoded = json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_PACKAGE_BYTES:
        raise HandoffError(f"compact package exceeds {MAX_PACKAGE_BYTES} bytes")
    return package


def usage_from_jsonl(path: Path) -> dict[str, int]:
    final_usage: dict[str, int] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise HandoffError(f"cannot read JSONL {path}: {exc}") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if event.get("type") == "turn.completed" and isinstance(usage, dict):
            final_usage = {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "reasoning_output_tokens": int(usage.get("reasoning_output_tokens") or 0),
            }
    if final_usage is None:
        raise HandoffError(f"no turn.completed usage found in {path}")
    return final_usage


def build_metrics(paths: list[Path]) -> dict[str, Any]:
    sessions = []
    for path in paths:
        usage = usage_from_jsonl(path)
        sessions.append({"path": str(path), **usage})
    raw_input = sum(item["input_tokens"] for item in sessions)
    cached = sum(item["cached_input_tokens"] for item in sessions)
    return {
        "session_count": len(sessions),
        "raw_input_tokens": raw_input,
        "cached_input_tokens": cached,
        "non_cached_input_tokens": raw_input - cached,
        "output_tokens": sum(item["output_tokens"] for item in sessions),
        "reasoning_output_tokens": sum(item["reasoning_output_tokens"] for item in sessions),
        "sessions": sessions,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--boundary", type=Path, required=True)
    build.add_argument("--worker", type=Path, action="append", default=[])
    build.add_argument("--output", type=Path, required=True)
    metrics = subparsers.add_parser("metrics")
    metrics.add_argument("--jsonl", type=Path, action="append", required=True)
    metrics.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        if args.command == "build":
            result = build_package(read_object(args.boundary), [read_object(path) for path in args.worker])
        else:
            result = build_metrics(args.jsonl)
        write_json(args.output, result)
    except HandoffError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
