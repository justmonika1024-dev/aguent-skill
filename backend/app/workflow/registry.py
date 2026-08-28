from __future__ import annotations

from typing import Any, Protocol


class WorkflowNode(Protocol):
    key: str
    async def execute(self, node_input: Any, services: Any) -> Any: ...


class NodeRegistry:
    def __init__(self, nodes: dict[str, WorkflowNode] | None = None) -> None:
        self._nodes = dict(nodes or {})
        if nodes is None:
            self._register_default_nodes()

    def _register_default_nodes(self) -> None:
        """Install a deterministic local pipeline for source-only startup.

        Provider-backed nodes can be injected by constructing ``NodeRegistry``
        with an explicit mapping; the defaults keep the API usable before keys
        are configured and provide a predictable development smoke path.
        """
        from .nodes.nodes import Node

        outcomes = {
            "N01": "ACCEPTED", "N02": "PLANNED", "N03": "PLAN_READY",
            "N04": "RESULTS_FOUND", "N05": "SELECTED", "N06": "NOT_DUPLICATE",
            "N07": "PLAN_READY", "N08": "RESULTS_FOUND", "N09": "SUFFICIENT",
            "N10": "TEMPLATE_READY", "N11": "PASS", "N11.5": "STRUCTURE_PRESERVING_REWRITE",
            "N12": "VALID_BATCH", "N13": "HAS_QUALIFIED", "N14": "SELECTED",
            "N15": "DRAFT_READY", "N16": "NOT_DUPLICATE", "N17": "WAIT_HUMAN_DECISION",
            "N19": "PATCH_VALID", "N20": "COMPLETED",
        }
        for key, outcome in outcomes.items():
            self._nodes[key] = Node(key=key, default_outcome=outcome)  # type: ignore[assignment]

    def register(self, node: WorkflowNode) -> None:
        key = getattr(node, "key", getattr(node, "node_key", None))
        if not key:
            raise ValueError("workflow node must define key or node_key")
        self._nodes[str(key)] = node

    def get(self, key: str) -> WorkflowNode:
        if key not in self._nodes:
            raise KeyError(f"workflow node not registered: {key}")
        return self._nodes[key]
