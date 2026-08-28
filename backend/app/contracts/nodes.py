from typing import Literal

from pydantic import Field

from .common import StrictModel


class N01Output(StrictModel):
    raw_seed: str; normalized_seed: str; core_expression: str
    possible_original_phrases: list[str]; ambiguities: list[str]
    initial_query_concepts: list[str]; human_summary: str


class Candidate(StrictModel):
    candidate_id: Literal["C1", "C2", "C3", "C4", "C5"]
    text: str; target_semantics: str
    preserved_features: list[str] = []; rewritten_features: list[str] = []
    slot_bindings: dict[str, str] | None = None
    generation_approach: str | None = None; length_note: str | None = None


class N12Output(StrictModel):
    route_used: Literal["DIRECT_SLOT_FILL", "STRUCTURE_PRESERVING_REWRITE"]
    candidates: list[Candidate] = Field(min_length=5, max_length=5)
    diversity_summary: str; human_summary: str

