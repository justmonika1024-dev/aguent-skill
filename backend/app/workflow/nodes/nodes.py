# mypy: disable-error-code=override
"""Small, deterministic node façade used by the workflow engine.

The façade keeps business checks in Python while delegating language work to a
provider supplied by the caller.  Full orchestration is intentionally owned by
Task 3.
"""
from dataclasses import dataclass
from typing import Any

from ...providers.base import NodeLLMRequest, SearchRequest
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
        # The default façade must not return the mutable artifact accumulator
        # itself.  Doing so makes the next engine assignment point the
        # accumulator back to itself, producing circular JSON and breaking the
        # human-readable node inspection endpoint.  Keep a compact, serializable
        # trace until provider-backed implementations replace this façade.
        if isinstance(value, dict):
            artifact: Any = {"input_node_keys": list(value.keys())}
        else:
            artifact = value
        return NodeResult(self.node_key, self.default_outcome, artifact)

class ProviderNode(Node):
    """LLM-backed node. Provider errors are deliberately surfaced to engine."""
    schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
    async def execute(self, value: Any, services: Any = None) -> NodeResult:
        if self.provider is None:
            return await super().execute(value, services)
        request = NodeLLMRequest(self.node_key, f"Execute {self.node_key} and return JSON only.", value, self.schema, self.node_key)
        result = await self.provider.generate(request)
        return NodeResult(self.node_key, self.default_outcome, result.parsed_json)

class N01(ProviderNode): node_key = "N01"
class N02(ProviderNode): node_key = "N02"
class N04(Node):
    node_key = "N04"
    async def execute(self, value: Any, services: Any = None) -> NodeResult:
        if self.provider is None: return await super().execute(value, services)
        return await _search_node(self, value, "original")
class N05(ProviderNode): node_key = "N05"
class N06(Node): node_key = "N06"
class N07(ProviderNode): node_key = "N07"
class N08(Node):
    node_key = "N08"
    async def execute(self, value: Any, services: Any = None) -> NodeResult:
        if self.provider is None: return await super().execute(value, services)
        return await _search_node(self, value, "variant")
class N10(ProviderNode): node_key = "N10"
class N14(ProviderNode):
    node_key = "N14"
    async def execute(self, value: Any, services: Any = None) -> NodeResult:
        result = await super().execute(value, services)
        if isinstance(result.output, dict) and "selected_candidate_id" in result.output:
            ids = {x.get("candidate_id") for x in value.get("candidates", [])} if isinstance(value, dict) else set()
            if result.output["selected_candidate_id"] not in ids: raise ValueError("N14 selected candidate does not exist")
        return result
class N15(ProviderNode):
    node_key = "N15"
    async def execute(self, value: Any, services: Any = None) -> NodeResult:
        result = await super().execute(value, services)
        if self.provider is not None and isinstance(value, dict) and isinstance(result.output, dict):
            selected = value.get("selected_text") or value.get("final_agu_text")
            final = result.output.get("final_agu_text")
            if selected is not None and final != selected: raise ValueError("N15 final_agu_text must equal selected candidate")
        return result
class N16(Node): node_key = "N16"
class N17(Node): node_key = "N17"
class N18(Node): node_key = "N18"
class N19(ProviderNode): node_key = "N19"
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
class N12(ProviderNode):
    node_key = "N12"
    async def execute(self, value: N12Candidates) -> NodeResult:
        if self.provider is not None:
            result = await ProviderNode.execute(self, value)
            checked = validate_n12_candidates(N12Candidates.model_validate(result.output))
            return NodeResult(self.node_key, "VALID_BATCH", checked)
        return NodeResult(self.node_key, "VALID_BATCH", validate_n12_candidates(value))
class N13(ProviderNode): node_key = "N13"

async def _search_node(node: Node, value: Any, mode: str) -> NodeResult:
    queries = value.get("queries", []) if isinstance(value, dict) else value
    merged: dict[str, Any] = {}
    failures = []
    for item in queries:
        query = item if isinstance(item, str) else item.get("query", "")
        query_id = None if isinstance(item, str) else item.get("query_id")
        try:
            batch = await node.provider.search(SearchRequest(query=query, search_type=(item.get("search_type", "auto") if isinstance(item, dict) else "auto"), num_results=5 if mode == "original" else 10, max_characters=1500 if mode == "original" else 1200, query_id=query_id))
            for result in batch.results:
                if result.canonical_url in merged:
                    merged[result.canonical_url].query_ids.extend(x for x in result.query_ids if x not in merged[result.canonical_url].query_ids)
                else: merged[result.canonical_url] = result
        except Exception as exc: failures.append({"query_id": query_id, "error": str(exc)})
    output = {"sources": list(merged.values()), "failures": failures}
    return NodeResult(node.node_key, "RESULTS_FOUND" if merged else ("ALL_QUERIES_FAILED" if failures and len(failures) == len(queries) else "NO_RESULTS"), output)
