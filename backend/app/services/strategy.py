from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

ALLOWED_PATHS = {"search", "generation", "evaluation", "admission"}
IMMUTABLE_PATHS = {"budgets", "safety", "candidate_count", "routes"}


@dataclass(frozen=True)
class StrategyPatch:
    operations: list[dict[str, Any]]
    feedback_summary: str = ""
    affected_nodes: list[str] | None = None


class StrategyService:
    def validate_patch(self, patch: StrategyPatch | dict[str, Any]) -> tuple[bool, str]:
        operations = patch.operations if isinstance(patch, StrategyPatch) else patch.get("operations", patch.get("patch_operations", []))
        for op in operations:
            full_path = str(op.get("path", "")).lstrip("/")
            path = full_path.split("/")[0]
            if path not in ALLOWED_PATHS:
                return False, f"path not allowed: {path}"
            if any(part in IMMUTABLE_PATHS for part in full_path.split("/")):
                return False, f"immutable path: {full_path}"
            if op.get("op") not in {"replace", "add"}:
                return False, "operation not allowed"
        return True, ""

    def apply(self, strategy: dict[str, Any], patch: StrategyPatch | dict[str, Any]) -> dict[str, Any]:
        ok, reason = self.validate_patch(patch)
        if not ok:
            raise ValueError(reason)
        result = deepcopy(strategy)
        operations = patch.operations if isinstance(patch, StrategyPatch) else patch.get("operations", patch.get("patch_operations", []))
        for op in operations:
            path = str(op["path"]).strip("/").split("/")
            target = result
            for part in path[:-1]:
                target = target.setdefault(part, {})
            target[path[-1]] = op.get("value")
        return result
