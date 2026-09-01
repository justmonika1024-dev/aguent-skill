from typing import Literal

from pydantic import Field, model_validator

from .common import StrictModel

Score = Field(ge=1, le=5)


class OriginalSearchPlanScores(StrictModel):
    anchor_accuracy: int = Score; query_coverage: int = Score; plan_targeting: int = Score
    comment: str = ""


class SelectedOriginalMemeScores(StrictModel):
    popularity: int = Score; applicability: int = Score
    adaptability: int = Score; evidence_reliability: int = Score
    comment: str = ""


class VariantSearchPlanScores(StrictModel):
    slot_replacement_targeting: int = Score; query_diversity: int = Score
    ugc_orientation: int = Score; noise_avoidance: int = Score
    comment: str = ""


class VariantSearchResultsScores(StrictModel):
    relevance: int = Score; real_variant_ratio: int = Score
    independent_evidence_quality: int = Score; variant_diversity: int = Score
    comment: str = ""


class TemplateExtractionScores(StrictModel):
    accuracy: int = Score; original_reconstruction: int = Score
    variant_coverage: int = Score; slot_rationality: int = Score
    comment: str = ""


class CandidateScores(StrictModel):
    fluency: int = Score; original_meme_recognition: int = Score
    agu_zao_naturalness: int = Score; humor: int = Score; template_logic: int = Score
    usability: Literal["USABLE", "USABLE_AFTER_EDIT", "UNUSABLE"]
    modification_advice: str = ""


class CandidateSetScores(StrictModel):
    effective_difference: int = Score; natural_rewrite_coverage: int = Score
    overall_selectable_quality: int = Score; comment: str = ""


class CandidateGenerationScores(StrictModel):
    overall: CandidateSetScores
    candidates: dict[str, CandidateScores]

    @model_validator(mode="after")
    def validate_candidates(self):
        if set(self.candidates) != {"C1", "C2", "C3", "C4", "C5"}:
            raise ValueError("candidates must contain exactly C1..C5")
        return self


class FinalResultScores(StrictModel):
    is_best_candidate: bool; better_candidate_id: str | None
    fluency: int = Score; original_meme_recognition: int = Score; agu_zao_fit: int = Score
    humor: int = Score; overall_satisfaction: int = Score; comment: str = ""

    @model_validator(mode="after")
    def validate_non_best_result(self):
        if not self.is_best_candidate and not self.better_candidate_id and not self.comment.strip():
            raise ValueError("non-best result requires better candidate or explanation")
        return self


class Admission(StrictModel):
    decision: Literal["ADMIT", "NOT_ADMIT"] | None = None
    override: Literal["KEEP", "OVERRIDE_TO_ADMIT", "OVERRIDE_TO_NOT_ADMIT"] | None = None
    reason: str = ""


class HumanEvaluationRequest(StrictModel):
    expected_run_version: int = Field(ge=0)
    branch_id: str
    original_search_plan: OriginalSearchPlanScores
    selected_original_meme: SelectedOriginalMemeScores
    variant_search_plan: VariantSearchPlanScores
    variant_search_results: VariantSearchResultsScores
    template_extraction: TemplateExtractionScores
    candidate_generation: CandidateGenerationScores
    final_result: FinalResultScores
    main_problem_nodes: list[str]
    admission: Admission
    overall_comment: str = ""
