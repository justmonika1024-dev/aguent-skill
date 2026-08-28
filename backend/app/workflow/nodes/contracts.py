from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class SearchQuery(StrictModel):
    query_id: str; query: str; search_type: Literal["keyword", "auto"]; purpose: str; priority: int = 1; expected_anchors: list[str] = []; result_limit: int = 5
class N03SearchPlan(StrictModel): queries: list[SearchQuery] = Field(min_length=3, max_length=8)
class VariantEvidence(StrictModel):
    variant_text: str; classification: Literal["VALID_VARIANT", "ORIGINAL_REPOST", "IRRELEVANT", "INSUFFICIENT_CONTEXT", "DUPLICATE_VARIANT"]; source_id: str; quote: str; anchor: str = ""; url: str
class N09EvidenceEvaluation(StrictModel): items: list[VariantEvidence]; is_sufficient: bool = False
class N11Adaptability(StrictModel):
    direct_score: int = Field(ge=1, le=5); structure_score: int = Field(ge=1, le=5); route: Literal["DIRECT_SLOT_FILL", "STRUCTURE_PRESERVING_REWRITE", "ABANDON_ORIGINAL"]
class Candidate(StrictModel): candidate_id: str; text: str
class N12Candidates(StrictModel): route: Literal["DIRECT_SLOT_FILL", "STRUCTURE_PRESERVING_REWRITE"]; candidates: list[Candidate] = Field(min_length=5, max_length=5)
