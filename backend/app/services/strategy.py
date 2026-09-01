from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

ALLOWED_PATHS = {"search", "generation", "evaluation", "admission"}
IMMUTABLE_PATHS = {"budgets", "safety", "candidate_count", "routes"}
DEFAULT_STRATEGY: dict[str, Any] = {
    "search": {
        "discovery_directives": [],
        "variant_query_directives": [],
        "prefer_ugc_sources": False,
        "exclude_exact_reprints": True,
        "require_slot_replacement": True,
        "max_variant_search_retries": 2,
        "minimum_valid_variants": 3,
        "minimum_independent_variant_sources": 2,
        "minimum_template_coverage": 0.6,
    },
    "generation": {
        "directives": [],
        "prefer_minimal_replacement": True,
        "reject_awkward_demonstrative_phrase": True,
    },
    "evaluation": {
        "directives": [],
        "minimum_fluency": 6,
        "minimum_recognition": 6,
        "minimum_agu_fit": 6,
    },
    "admission": {"directives": []},
}

_INTEGER_RANGES = {
    "max_variant_search_retries": (0, 10),
    "minimum_valid_variants": (1, 8),
    "minimum_independent_variant_sources": (1, 8),
    "minimum_fluency": (0, 10),
    "minimum_recognition": (0, 10),
    "minimum_agu_fit": (0, 10),
}


def default_strategy() -> dict[str, Any]:
    return deepcopy(DEFAULT_STRATEGY)


@dataclass(frozen=True)
class StrategyPatch:
    operations: list[dict[str, Any]]
    feedback_summary: str = ""
    affected_nodes: list[str] | None = None


class StrategyService:
    @staticmethod
    def _operations(patch: StrategyPatch | dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(patch, StrategyPatch):
            return patch.operations
        return patch.get("operations", patch.get("patch_operations", []))

    @staticmethod
    def _path(raw_path: Any) -> list[str]:
        path = str(raw_path)
        if not path.startswith("/"):
            raise ValueError("patch path must start with '/'")
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        if not parts or not parts[0] or any(not part for part in parts):
            raise ValueError("patch path must identify a field")
        if parts[0] not in ALLOWED_PATHS:
            raise ValueError(f"path not allowed: {parts[0]}")
        if any(part in IMMUTABLE_PATHS for part in parts):
            raise ValueError(f"immutable path: {'/'.join(parts)}")
        return parts

    @staticmethod
    def _validate_value(parts: list[str], value: Any) -> None:
        field = parts[-1]
        if field == "-":
            return
        if field.startswith(("prefer_", "exclude_", "require_", "reject_")):
            if type(value) is not bool:
                raise ValueError(f"{field} must be a boolean")
        if field == "minimum_template_coverage":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError("minimum_template_coverage must be between 0 and 1")
        if field in _INTEGER_RANGES:
            lower, upper = _INTEGER_RANGES[field]
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{field} must be an integer between {lower} and {upper}")

    def validate_patch(self, patch: StrategyPatch | dict[str, Any]) -> tuple[bool, str]:
        operations = self._operations(patch)
        if not isinstance(operations, list):
            return False, "operations must be a list"
        try:
            for op in operations:
                if not isinstance(op, dict):
                    raise ValueError("operation must be an object")
                if op.get("op") not in {"replace", "add"}:
                    raise ValueError("operation not allowed")
                parts = self._path(op.get("path", ""))
                if "value" not in op:
                    raise ValueError("operation value is required")
                self._validate_value(parts, op["value"])
        except ValueError as exc:
            return False, str(exc)
        return True, ""

    def apply(self, strategy: dict[str, Any], patch: StrategyPatch | dict[str, Any]) -> dict[str, Any]:
        ok, reason = self.validate_patch(patch)
        if not ok:
            raise ValueError(reason)
        result = deepcopy(strategy)
        operations = self._operations(patch)
        for op in operations:
            parts = self._path(op["path"])
            target: Any = result
            for part in parts[:-1]:
                if not isinstance(target, dict) or part not in target:
                    raise ValueError(f"patch parent does not exist: {part}")
                target = target[part]
            field = parts[-1]
            if isinstance(target, list):
                if op["op"] != "add" or field != "-":
                    raise ValueError("arrays only support add at '/-'")
                if op["value"] not in target:
                    target.append(deepcopy(op["value"]))
                continue
            if not isinstance(target, dict):
                raise ValueError("patch target parent must be an object")
            if field == "-":
                raise ValueError("'/-' requires an array target")
            if op["op"] == "replace" and field not in target:
                raise ValueError(f"replace target does not exist: {field}")
            target[field] = deepcopy(op["value"])
        return result
