from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class AdmissionDecision:
    decision: str
    reason: str = ""
    safety: str = "UNCERTAIN"


class AdmissionService:
    """Deterministic N17 hard-threshold decision helper."""

    def decide(self, artifact: dict[str, Any], mode: str = "AUTO") -> AdmissionDecision:
        decision_basis = str(
            artifact.get("decision_basis", artifact.get("reason", "")),
        )
        safety_value = artifact.get("safety", artifact.get("content_safety"))
        if isinstance(safety_value, dict):
            safety_value = safety_value.get("status", safety_value.get("result"))
        safety = str(safety_value or "UNCERTAIN").strip().upper()
        if safety not in {"PASS", "REJECT", "UNCERTAIN"}:
            safety = "UNCERTAIN"
        if safety != "PASS":
            reason = decision_basis or f"内容安全结果为{safety}，不允许入库"
            return AdmissionDecision("NOT_ADMIT", reason, safety)

        failed_conditions = artifact.get("failed_conditions")
        if not isinstance(failed_conditions, list):
            failed_conditions = ["ADMISSION_CONTRACT_INVALID"]
        if failed_conditions:
            reason = decision_basis or (
                "自动准入硬条件未通过：" + "、".join(map(str, failed_conditions))
            )
            return AdmissionDecision("NOT_ADMIT", reason, safety)

        raw_score = artifact.get("score", artifact.get("overall_score"))
        raw_threshold = artifact.get("threshold", 6.0)
        if (not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool)
                or not isfinite(float(raw_score))
                or not 0 <= float(raw_score) <= 10):
            return AdmissionDecision(
                "NOT_ADMIT",
                decision_basis or "自动准入缺少有效的0-10综合质量分",
                safety,
            )
        if (not isinstance(raw_threshold, (int, float))
                or isinstance(raw_threshold, bool)
                or not isfinite(float(raw_threshold))
                or not 0 <= float(raw_threshold) <= 10):
            return AdmissionDecision(
                "NOT_ADMIT",
                decision_basis or "自动准入缺少有效的0-10质量门槛",
                safety,
            )
        score = float(raw_score)
        threshold = float(raw_threshold)
        decision = "ADMIT" if score >= threshold else "NOT_ADMIT"
        reason = decision_basis or (
            f"质量分{score:.2f}/10{'达到' if decision == 'ADMIT' else '低于'}"
            f"自动准入门槛{threshold:.2f}/10"
        )
        return AdmissionDecision(decision, reason, safety)
