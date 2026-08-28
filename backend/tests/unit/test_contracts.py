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


def test_evaluation_requires_exact_candidate_set_and_valid_scores():
    base = dict(fluency=4, original_meme_recognition=4, agu_zao_naturalness=4,
                humor=4, template_logic=4, usability="USABLE", modification_advice="")
    payload = dict(expected_run_version=1, branch_id="b", processing_chain={
        "original_meme_popularity": 4, "original_meme_applicability": 4,
        "search_result_relevance": 4, "variant_evidence_quality": 4,
        "template_extraction_accuracy": 4, "overall_chain_reasonableness": 4, "comment": ""},
        candidate_set={"effective_difference": 4, "natural_rewrite_coverage": 4,
                       "overall_selectable_quality": 4, "comment": ""},
        candidates={f"C{i}": base for i in range(1, 6)},
        final_result={"is_best_candidate": True, "better_candidate_id": None, "fluency": 4,
                      "original_meme_recognition": 4, "agu_zao_fit": 4, "humor": 4,
                      "overall_satisfaction": 4, "comment": ""},
        main_problem_nodes=["NO_OBVIOUS_PROBLEM"],
        admission={"decision": "ADMIT", "override": None, "reason": "ok"}, overall_comment="")
    request = HumanEvaluationRequest(**payload)
    assert set(request.candidates) == {"C1", "C2", "C3", "C4", "C5"}
    with pytest.raises(ValidationError):
        HumanEvaluationRequest(**{**payload, "candidates": {"C1": base}})


def test_metadata_contains_run_and_meme_archive_tables():
    expected = {
        "run_records", "run_branches", "run_node_executions", "run_source_evidence",
        "run_search_batches", "run_evidence_query_hits", "run_human_evaluations",
        "run_strategy_versions", "run_strategy_patches", "run_strategy_state",
        "run_model_parameter_profiles", "run_audit_actions", "meme_records",
        "meme_sources", "meme_admission_history", "meme_status_history", "meme_revision_history",
    }
    assert expected <= set(Base.metadata.tables)
