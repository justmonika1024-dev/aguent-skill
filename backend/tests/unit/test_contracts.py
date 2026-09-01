import pytest
from pydantic import ValidationError

from app.contracts.evaluation import HumanEvaluationRequest
from app.contracts.nodes import Candidate, N01Output, N12Output
from app.db import models  # noqa: F401
from app.db.base import Base


def test_node_contracts_are_strict_and_n12_has_five_fixed_candidates():
    candidate = Candidate(candidate_id="C1", text="大胆，我一眼就看出你不是 agu", target_semantics="person")
    output = N12Output(route_used="DIRECT_SLOT_FILL", candidates=[candidate] * 5,
                       diversity_summary="ok", human_summary="ok")
    assert output.candidates[0].candidate_id == "C1"
    with pytest.raises(ValidationError):
        N01Output(raw_seed="x", normalized_seed="x", core_expression="x",
                  possible_original_phrases=[], ambiguities=[], initial_query_concepts=[],
                  human_summary="x", unknown="bad")


def module_score(**values):
    return {**values, "comment": ""}


def valid_evaluation_payload():
    candidate = {
        "fluency": 4, "original_meme_recognition": 4,
        "agu_zao_naturalness": 4, "humor": 4, "template_logic": 4,
        "usability": "USABLE", "modification_advice": "",
    }
    return {
        "expected_run_version": 1, "branch_id": "b1",
        "original_search_plan": module_score(anchor_accuracy=4, query_coverage=4, plan_targeting=4),
        "selected_original_meme": module_score(popularity=4, applicability=4, adaptability=4, evidence_reliability=4),
        "variant_search_plan": module_score(slot_replacement_targeting=4, query_diversity=4, ugc_orientation=4, noise_avoidance=4),
        "variant_search_results": module_score(relevance=4, real_variant_ratio=4, independent_evidence_quality=4, variant_diversity=4),
        "template_extraction": module_score(accuracy=4, original_reconstruction=4, variant_coverage=4, slot_rationality=4),
        "candidate_generation": {
            "overall": module_score(effective_difference=4, natural_rewrite_coverage=4, overall_selectable_quality=4),
            "candidates": {f"C{i}": candidate for i in range(1, 6)},
        },
        "final_result": {
            "is_best_candidate": True, "better_candidate_id": None,
            "fluency": 4, "original_meme_recognition": 4, "agu_zao_fit": 4,
            "humor": 4, "overall_satisfaction": 4, "comment": "",
        },
        "main_problem_nodes": ["NO_OBVIOUS_PROBLEM"],
        "admission": {"decision": "ADMIT", "override": None, "reason": ""},
        "overall_comment": "",
    }


def test_evaluation_requires_all_seven_modules_but_allows_empty_text_feedback():
    request = HumanEvaluationRequest(**valid_evaluation_payload())
    assert request.variant_search_results.comment == ""
    assert request.candidate_generation.candidates["C1"].modification_advice == ""


@pytest.mark.parametrize("score", [0, 6])
def test_evaluation_rejects_scores_outside_one_to_five(score):
    payload = valid_evaluation_payload()
    payload["original_search_plan"]["anchor_accuracy"] = score
    with pytest.raises(ValidationError):
        HumanEvaluationRequest(**payload)


def test_evaluation_requires_exact_candidate_set():
    payload = valid_evaluation_payload()
    payload["candidate_generation"]["candidates"] = {"C1": payload["candidate_generation"]["candidates"]["C1"]}
    with pytest.raises(ValidationError):
        HumanEvaluationRequest(**payload)


def test_metadata_contains_run_and_meme_archive_tables():
    expected = {
        "run_records", "run_branches", "run_node_executions", "run_source_evidence",
        "run_search_batches", "run_evidence_query_hits", "run_human_evaluations",
        "run_strategy_versions", "run_strategy_patches", "run_strategy_state",
        "run_model_parameter_profiles", "run_audit_actions", "meme_records",
        "meme_sources", "meme_admission_history", "meme_status_history", "meme_revision_history",
    }
    assert expected <= set(Base.metadata.tables)
