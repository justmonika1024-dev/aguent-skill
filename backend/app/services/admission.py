from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdmissionDecision:
    decision: str
    reason: str = ""
    safety: str = "PASS"


class AdmissionService:
    """Deterministic N17 hard-threshold decision helper."""

    def decide(self, artifact: dict[str, Any], mode: str = "AUTO") -> AdmissionDecision:
        safety_value = artifact.get("safety", artifact.get("content_safety", "PASS"))
        if isinstance(safety_value, dict):
            safety_value = safety_value.get("status", safety_value.get("result", "PASS"))
        safety = str(safety_value).upper()
        if safety != "PASS":
            return AdmissionDecision("NOT_ADMIT", "content safety is not PASS", safety)
        score = float(artifact.get("score", artifact.get("overall_score", 0)))
        threshold = float(artifact.get("threshold", 3.5))
        return AdmissionDecision("ADMIT" if score >= threshold else "NOT_ADMIT", "", safety)
