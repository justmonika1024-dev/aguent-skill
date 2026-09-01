from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    node: str
    outcome: str
    next_node: str | None


class TransitionTable:
    """Deterministic routing table; nodes never choose the next state."""

    _fixed = {
        ("START", "MANUAL_SEED"): "N01", ("START", "AUTO_DISCOVERY"): "N02",
        ("N01", "ACCEPTED"): "N03", ("N02", "PLANNED"): "N03",
        ("N03", "PLAN_READY"): "N04", ("N04", "RESULTS_FOUND"): "N05",
        ("N05", "SELECTED"): "N06", ("N06", "NOT_DUPLICATE"): "N07",
        ("N07", "PLAN_READY"): "N08", ("N08", "RESULTS_FOUND"): "N09",
        ("N09", "SUFFICIENT"): "N10", ("N10", "TEMPLATE_READY"): "N11",
        ("N11", "PASS"): "N11.5", ("N11.5", "DIRECT_SLOT_FILL"): "N12",
        ("N11.5", "STRUCTURE_PRESERVING_REWRITE"): "N12", ("N12", "VALID_BATCH"): "N13",
        ("N13", "HAS_QUALIFIED"): "N14", ("N14", "SELECTED"): "N15",
        ("N15", "DRAFT_READY"): "N16", ("N16", "NOT_DUPLICATE"): "N17",
        ("N17", "AUTO_DECIDED"): "N18", ("N17", "WAIT_HUMAN_DECISION"): "N18",
        ("N18", "EVALUATION_SUBMITTED"): "N19", ("N19", "PATCH_VALID"): "N20",
    }

    def next(self, node: str, outcome: str, *, mode: str = "MANUAL_SEED",
             has_budget: bool = True, continuous: bool = False) -> str | None:
        if node in {"N04", "N05", "N08", "N09", "N10", "N11", "N13"} and not has_budget:
            return "N02" if mode == "AUTO_DISCOVERY" else "WAITING_HUMAN_INTERVENTION"
        if (node, outcome) in self._fixed:
            return self._fixed[(node, outcome)]
        if outcome in {"ALL_QUERIES_FAILED", "HUMAN_REVIEW_REQUIRED", "DUPLICATE"}:
            if outcome == "DUPLICATE":
                return "N02" if mode == "AUTO_DISCOVERY" else "N03"
            return "WAITING_HUMAN_INTERVENTION"
        if outcome == "NO_RESULTS" and has_budget:
            return "N03" if node == "N04" else "N07"
        if outcome == "NO_QUALIFIED_CANDIDATE" and has_budget:
            return "N03"
        if outcome in {"INSUFFICIENT", "REEXTRACT", "MORE_EVIDENCE", "ALL_UNQUALIFIED"} and has_budget:
            return "N07" if node in {"N09", "N11"} else "N12"
        if node == "N19" and outcome == "PATCH_INVALID":
            return "WAITING_HUMAN_INTERVENTION"
        if node == "N20":
            return "N02" if continuous else None
        if outcome == "ABANDON_ORIGINAL":
            if mode == "AUTO_DISCOVERY":
                return "N02"
            return "WAITING_HUMAN_INTERVENTION" if node in {"N09", "N11"} else "N03"
        return None

    calculate_next = next
