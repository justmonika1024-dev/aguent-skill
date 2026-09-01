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
        decision_basis = str(
            artifact.get("decision_basis", artifact.get("reason", "")),
        )
        safety_value = artifact.get("safety", artifact.get("content_safety", "PASS"))
        if isinstance(safety_value, dict):
            safety_value = safety_value.get("status", safety_value.get("result", "PASS"))
        safety = str(safety_value).upper()
        if safety != "PASS":
            reason = decision_basis or f"内容安全结果为{safety}，不允许入库"
            return AdmissionDecision("NOT_ADMIT", reason, safety)
        score = float(artifact.get("score", artifact.get("overall_score", 0)))
        threshold = float(artifact.get("threshold", 3.5))
        decision = "ADMIT" if score >= threshold else "NOT_ADMIT"
        reason = decision_basis or (
            f"质量分{score:.2f}{'达到' if decision == 'ADMIT' else '低于'}"
            f"自动准入门槛{threshold:.2f}"
        )
        return AdmissionDecision(decision, reason, safety)
