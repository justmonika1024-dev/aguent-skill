from __future__ import annotations

from typing import Any


class NodeResultValidator:
    """Small, provider-agnostic validator used by the engine boundary."""

    def validate(self, result: Any) -> Any:
        if result is None:
            raise ValueError("node returned no result")
        outcome = getattr(result, "outcome", None)
        if isinstance(result, dict):
            outcome = result.get("outcome", outcome)
        if not outcome:
            raise ValueError("node result must include outcome")
        return result

