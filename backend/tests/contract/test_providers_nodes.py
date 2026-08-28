
import pytest

from app.providers.base import NodeLLMRequest, ParameterProfile
from app.providers.exa import canonicalize_url
from app.providers.fake import FakeLLMProvider
from app.workflow.nodes.contracts import (
    N03SearchPlan,
    N09EvidenceEvaluation,
    N11Adaptability,
    N12Candidates,
)
from app.workflow.nodes.validation import (
    validate_n03_plan,
    validate_n09_evidence,
    validate_n11_5,
    validate_n12_candidates,
)


@pytest.mark.asyncio
async def test_fake_llm_returns_structured_payload_and_metadata_async():
    provider = FakeLLMProvider(responses=[{"answer": "ok"}])
    result = await provider.generate(NodeLLMRequest(
        node_key="N01", system_prompt="", user_payload={},
        output_schema={"type": "object"}, schema_name="N01", parameter_profile=ParameterProfile(),
    ))
    assert result.parsed_json == {"answer": "ok"}
    assert result.provider == "fake"


def test_exa_url_cleaning_and_n03_rules():
    assert canonicalize_url("HTTPS://Example.COM/a?utm_source=x&id=1#frag") == "https://example.com/a?id=1"
    plan = N03SearchPlan.model_validate({"queries": [
        {"query_id": "q1", "query": "你说的对", "search_type": "keyword", "purpose": "x", "priority": 1},
        {"query_id": "q2", "query": "你说的对", "search_type": "auto", "purpose": "x", "priority": 2},
        {"query_id": "q3", "query": "你说的对 梗", "search_type": "keyword", "purpose": "x", "priority": 3},
    ]})
    assert validate_n03_plan(plan) is plan


def test_n11_5_threshold_and_n12_five_candidates_contract():
    assert validate_n11_5(N11Adaptability(direct_score=3, structure_score=4, route="STRUCTURE_PRESERVING_REWRITE")).route == "STRUCTURE_PRESERVING_REWRITE"
    with pytest.raises(ValueError):
        validate_n11_5(N11Adaptability(direct_score=3, structure_score=4, route="DIRECT_SLOT_FILL"))
    payload = {"route": "DIRECT_SLOT_FILL", "candidates": [
        {"candidate_id": f"C{i}", "text": f"agu凿{i}"} for i in range(1, 6)
    ]}
    assert len(validate_n12_candidates(N12Candidates.model_validate(payload)).candidates) == 5


def test_n09_sufficiency_is_code_derived():
    evidence = N09EvidenceEvaluation.model_validate({"items": [
        {"variant_text": "a", "classification": "VALID_VARIANT", "source_id": "V1", "quote": "a", "anchor": "你说的对", "url": "https://a.test"},
        {"variant_text": "b", "classification": "VALID_VARIANT", "source_id": "V2", "quote": "b", "anchor": "你说的对", "url": "https://b.test"},
        {"variant_text": "c", "classification": "VALID_VARIANT", "source_id": "V3", "quote": "c", "anchor": "你说的对", "url": "https://c.test"},
    ], "is_sufficient": False})
    assert validate_n09_evidence(evidence).is_sufficient is True
