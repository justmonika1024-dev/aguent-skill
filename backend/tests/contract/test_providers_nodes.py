
import httpx
import pytest

from app.providers.base import NodeLLMRequest, ParameterProfile
from app.providers.exa import canonicalize_url
from app.providers.fake import FakeLLMProvider
from app.providers.llm import DeepSeekChatProvider, _json_text
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


def test_llm_parser_accepts_markdown_json_fence():
    assert _json_text('```json\n{"ok": true}\n```') == {"ok": True}


@pytest.mark.asyncio
async def test_deepseek_http_error_includes_provider_response_message():
    async def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request, json={
            "error": {"code": "InvalidParameter", "message": "input is too long"},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(reject))
    provider = DeepSeekChatProvider("secret", "deepseek-v4-flash", client=client)
    request = NodeLLMRequest(
        node_key="N05", system_prompt="return json", user_payload={},
        output_schema={"type": "object"}, schema_name="N05",
    )

    try:
        with pytest.raises(httpx.HTTPStatusError, match="input is too long"):
            await provider.generate(request)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_deepseek_json_error_reports_safe_finish_diagnostics():
    raw = "not-json:" + ("x" * 400) + ":response-tail"

    async def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={
            "id": "response-id",
            "choices": [{
                "message": {"content": raw},
                "finish_reason": "length",
            }],
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(malformed))
    provider = DeepSeekChatProvider("super-secret-api-key", "deepseek-v4-flash", client=client)
    request = NodeLLMRequest(
        node_key="N09", system_prompt="return json", user_payload={},
        output_schema={"type": "object"}, schema_name="N09",
    )

    try:
        with pytest.raises(ValueError) as caught:
            await provider.generate(request)
    finally:
        await client.aclose()

    message = str(caught.value)
    assert "finish_reason=length" in message
    assert f"raw_response_chars={len(raw)}" in message
    assert "response-tail" in message
    assert "super-secret-api-key" not in message
    assert len(message) < 700


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
