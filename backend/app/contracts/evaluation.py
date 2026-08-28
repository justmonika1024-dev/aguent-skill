from typing import Literal

from pydantic import Field, model_validator

from .common import StrictModel

Score = Field(ge=1, le=5)


class ProcessingChainScores(StrictModel):
    original_meme_popularity: int = Score; original_meme_applicability: int = Score
    search_result_relevance: int = Score; variant_evidence_quality: int = Score
    template_extraction_accuracy: int = Score; overall_chain_reasonableness: int = Score
    comment: str


class CandidateScores(StrictModel):
    fluency: int = Score; original_meme_recognition: int = Score
    agu_zao_naturalness: int = Score; humor: int = Score; template_logic: int = Score
    usability: Literal["USABLE", "USABLE_AFTER_EDIT", "UNUSABLE"]
    modification_advice: str


class CandidateSetScores(StrictModel):
    effective_difference: int = Score; natural_rewrite_coverage: int = Score
    overall_selectable_quality: int = Score; comment: str


class FinalResultScores(StrictModel):
    is_best_candidate: bool; better_candidate_id: str | None
    fluency: int = Score; original_meme_recognition: int = Score; agu_zao_fit: int = Score
    humor: int = Score; overall_satisfaction: int = Score; comment: str


class Admission(StrictModel):
    decision: Literal["ADMIT", "NOT_ADMIT"] | None = None
    override: Literal["KEEP", "OVERRIDE_TO_ADMIT", "OVERRIDE_TO_NOT_ADMIT"] | None = None
    reason: str


class HumanEvaluationRequest(StrictModel):
    expected_run_version: int = Field(ge=0)
    branch_id: str
    processing_chain: ProcessingChainScores
    candidate_set: CandidateSetScores
    candidates: dict[str, CandidateScores]
    final_result: FinalResultScores
    main_problem_nodes: list[str]
    admission: Admission
    overall_comment: str

    @model_validator(mode="after")
    def validate_candidates(self):
        if set(self.candidates) != {"C1", "C2", "C3", "C4", "C5"}:
            raise ValueError("candidates must contain exactly C1..C5")
        if not self.final_result.is_best_candidate and not self.final_result.better_candidate_id and not self.final_result.comment.strip():
            raise ValueError("non-best result requires better candidate or explanation")
        return self
