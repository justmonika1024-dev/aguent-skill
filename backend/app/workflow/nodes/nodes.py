# mypy: disable-error-code=override
"""Small, deterministic node façade used by the workflow engine.

The façade keeps business checks in Python while delegating language work to a
provider supplied by the caller.  Full orchestration is intentionally owned by
Task 3.
"""
from dataclasses import dataclass
from typing import Any

from .contracts import (
    N03SearchPlan,
    N09EvidenceEvaluation,
    N11Adaptability,
    N12Candidates,
)
from .validation import (
    validate_n03_plan,
    validate_n09_evidence,
    validate_n11_5,
    validate_n12_candidates,
)


@dataclass
class NodeResult:
    node_key: str
    outcome: str
    output: Any

class Node:
    node_key: str
    def __init__(self, provider=None, key: str | None = None, default_outcome: str = "COMPLETED"):
        self.provider = provider
        if key is not None:
            self.node_key = key
        self.default_outcome = default_outcome
    @property
    def key(self) -> str:
        return self.node_key

    async def execute(self, value: Any, services: Any = None) -> NodeResult:
        return NodeResult(self.node_key, self.default_outcome, value)

class N01(Node): node_key = "N01"
class N02(Node): node_key = "N02"
class N04(Node): node_key = "N04"
class N05(Node): node_key = "N05"
class N06(Node): node_key = "N06"
class N07(Node): node_key = "N07"
class N08(Node): node_key = "N08"
class N10(Node): node_key = "N10"
class N14(Node): node_key = "N14"
class N15(Node): node_key = "N15"
class N16(Node): node_key = "N16"
class N17(Node): node_key = "N17"
class N18(Node): node_key = "N18"
class N19(Node): node_key = "N19"
class N20(Node): node_key = "N20"

class N03(Node):
    node_key = "N03"
    async def execute(self, value: N03SearchPlan) -> NodeResult:
        return NodeResult(self.node_key, "PLAN_READY", validate_n03_plan(value))
class N09(Node):
    node_key = "N09"
    async def execute(self, value: N09EvidenceEvaluation) -> NodeResult:
        checked = validate_n09_evidence(value)
        return NodeResult(self.node_key, "SUFFICIENT" if checked.is_sufficient else "INSUFFICIENT", checked)
class N11_5(Node):
    node_key = "N11.5"
    async def execute(self, value: N11Adaptability) -> NodeResult:
        checked = validate_n11_5(value)
        return NodeResult(self.node_key, checked.route, checked)
class N12(Node):
    node_key = "N12"
    async def execute(self, value: N12Candidates) -> NodeResult:
        return NodeResult(self.node_key, "VALID_BATCH", validate_n12_candidates(value))
class N13(Node): node_key = "N13"
