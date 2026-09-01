import json

import pytest

from app.providers.base import SearchBatch, SearchResult
from app.providers.fake import FakeLLMProvider, FakeSearchProvider
from app.workflow import real_registry
from app.workflow.context import AdmissionMode, RunContext, RunMode
from app.workflow.real_registry import (
    _compact_artifacts,
    build_real_registry,
    derive_required_patch_operations,
)
from app.workflow.transitions import TransitionTable


class FailingLLM:
    model = "failing-model"

    async def generate(self, request):
        raise ValueError("empty model JSON")


class FormalMemeRepositoryStub:
    def __init__(self):
        self.detail_requests = []

    async def list_formal_meme_titles(self):
        return [{
            "id": "existing-1",
            "title": "凿agu版·小孩才做选择，我全都要是什么梗",
        }]

    async def get_formal_meme_summary(self, meme_id):
        self.detail_requests.append(meme_id)
        return {
            "id": meme_id,
            "title": "凿agu版·小孩才做选择，我全都要是什么梗",
            "original_meme_text": "小孩才做选择，我全都要",
            "final_agu_text": "小孩才做选择，agu全都要凿",
            "source_run_id": "existing-run",
        }

    async def record_api_call(self, *args, **kwargs):
        return None


class UsageRepositoryStub:
    def __init__(self):
        self.api_calls = []

    async def record_api_call(self, *args, **kwargs):
        self.api_calls.append({"args": args, "kwargs": kwargs})


class EmptyFormalMemeRepositoryStub:
    async def list_formal_meme_titles(self):
        return []

    async def get_formal_meme_summary(self, meme_id):
        raise AssertionError(f"unexpected formal meme detail request: {meme_id}")


def automatic_admission_artifacts(
    *, template_accuracy: int = 5, safety: str | None = "PASS",
) -> dict:
    selected_score = {
        "candidate_id": "C1",
        "fluency": 8,
        "recognition": 9,
        "agu_fit": 9,
        "humor": 7,
        "rhythm": 7,
        "adaptation_restraint": 8,
        "minimal_replacement_effect": 8,
        "qualified": True,
        "problems": [],
    }
    artifacts = {
        "N09": {"llm": {"is_sufficient": True, "variants": [{}, {}, {}]}},
        "N11": {"llm": {
            "decision": "PASS", "accuracy": template_accuracy, "coverage": 0.9,
        }},
        "N11.5": {"llm": {"route": "STRUCTURE_PRESERVING_REWRITE"}},
        "N13": {"llm": {
            "scores": [selected_score], "qualified_candidate_ids": ["C1"],
        }, "minimum_thresholds": {
            "fluency": 6, "recognition": 6, "agu_fit": 6,
        }},
        "N14": {"llm": {"selected_candidate_id": "C1"}},
        "N15": {"llm": {
            "title": "凿agu版·新梗",
            "normalized_title": "凿agu版·新梗",
            "final_agu_text": "他正在凿agu。",
        }},
    }
    if safety is not None:
        artifacts["N15"]["llm"]["content_safety"] = {
            "status": safety,
            "method": "DETERMINISTIC_RULESET",
            "policy_version": "content-safety-v1",
            "checks": [],
        }
    return artifacts


@pytest.mark.asyncio
async def test_real_registry_n16_and_n17_admit_high_quality_artifacts():
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
        repository=EmptyFormalMemeRepositoryStub(),
    )

    n16 = await registry.get("N16").execute(automatic_admission_artifacts(), None)
    n17 = await registry.get("N17").execute(
        {"N16": n16["artifact"]}, {"admission_mode": "AUTO"},
    )

    assert n16["outcome"] == "NOT_DUPLICATE"
    assert n16["artifact"]["checked_formal_title_count"] == 0
    assert n16["artifact"]["score"] == pytest.approx(9.0)
    assert n16["artifact"]["threshold"] == 6.0
    assert n16["artifact"]["failed_conditions"] == []
    assert n16["artifact"]["quality_components"]["scale"] == "0-10"
    assert n16["artifact"]["quality_components"]["template_accuracy"] == 10.0
    assert n16["artifact"]["quality_components"]["template_coverage"] == 9.0
    assert "综合质量分9.00/10" in n16["artifact"]["decision_basis"]
    assert n17.outcome == "AUTO_DECIDED"
    assert n17.output["admission_decision"] == "ADMIT"
    assert n17.output["reason"] == n16["artifact"]["decision_basis"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("artifacts", "failed_condition", "safety"), [
    (automatic_admission_artifacts(template_accuracy=3), "N11_ACCURACY_BELOW_8", "PASS"),
    (automatic_admission_artifacts(safety=None), "CONTENT_SAFETY_MISSING", "UNCERTAIN"),
    (automatic_admission_artifacts(safety="UNCERTAIN"), "CONTENT_SAFETY_NOT_PASS", "UNCERTAIN"),
    (automatic_admission_artifacts(safety="REJECT"), "CONTENT_SAFETY_NOT_PASS", "REJECT"),
])
async def test_real_registry_n16_and_n17_reject_low_quality_or_unsafe_artifacts(
    artifacts, failed_condition, safety,
):
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
        repository=EmptyFormalMemeRepositoryStub(),
    )

    n16 = await registry.get("N16").execute(artifacts, None)
    n17 = await registry.get("N17").execute(
        {"N16": n16["artifact"]}, {"admission_mode": "AUTO"},
    )

    assert failed_condition in n16["artifact"]["failed_conditions"]
    assert n16["artifact"]["safety"] == safety
    assert n17.outcome == "AUTO_DECIDED"
    assert n17.output["admission_decision"] == "NOT_ADMIT"
    assert n17.output["reason"]


@pytest.mark.asyncio
async def test_real_registry_n16_rejects_duplicate_formal_title_before_admission():
    repository = FormalMemeRepositoryStub()
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(), repository=repository,
    )
    artifacts = automatic_admission_artifacts()
    artifacts["N15"]["llm"].update({
        "title": "凿agu版·小孩才做选择，我全都要是什么梗",
        "normalized_title": "凿agu版·小孩才做选择，我全都要是什么梗",
    })

    n16 = await registry.get("N16").execute(
        artifacts, {"run_id": "new-run"},
    )

    assert n16["outcome"] == "DUPLICATE"
    assert n16["artifact"]["suspected_meme_id"] == "existing-1"
    assert n16["artifact"]["existing_title"].startswith("凿agu版")
    assert n16["artifact"]["duplicate_basis"] == "TITLE"
    assert "score" not in n16["artifact"]


@pytest.mark.asyncio
async def test_real_registry_n16_fails_closed_when_selected_score_contract_is_incomplete():
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
        repository=EmptyFormalMemeRepositoryStub(),
    )
    artifacts = automatic_admission_artifacts()
    del artifacts["N13"]["llm"]["scores"][0]["humor"]

    n16 = await registry.get("N16").execute(artifacts, None)
    n17 = await registry.get("N17").execute(
        {"N16": n16["artifact"]}, {"admission_mode": "AUTO"},
    )

    assert "N13_HUMOR_MISSING" in n16["artifact"]["failed_conditions"]
    assert "缺少humor评分" in n16["artifact"]["decision_basis"]
    assert n17.output["admission_decision"] == "NOT_ADMIT"


@pytest.mark.asyncio
async def test_real_registry_n17_rejects_quality_score_outside_zero_to_ten_scale():
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
        repository=EmptyFormalMemeRepositoryStub(),
    )

    n17 = await registry.get("N17").execute({
        "N16": {
            "score": 11,
            "threshold": 6,
            "safety": "PASS",
            "failed_conditions": [],
        },
    }, {"admission_mode": "AUTO"})

    assert n17.output["admission_decision"] == "NOT_ADMIT"
    assert "0-10" in n17.output["reason"]


def test_low_variant_scores_force_search_quality_patch():
    evaluation = {
        "variant_search_plan": {
            "slot_replacement_targeting": 2,
            "query_diversity": 3,
            "ugc_orientation": 2,
            "noise_avoidance": 2,
            "comment": "结果基本都是原句转载",
        },
        "variant_search_results": {
            "relevance": 3,
            "real_variant_ratio": 1,
            "independent_evidence_quality": 2,
            "variant_diversity": 2,
            "comment": "没有网友槽位改编",
        },
    }

    operations = derive_required_patch_operations(evaluation, [])

    assert {op["path"] for op in operations} >= {
        "/search/prefer_ugc_sources",
        "/search/exclude_exact_reprints",
        "/search/require_slot_replacement",
    }
    assert any("原句转载" in str(op["value"]) for op in operations)


@pytest.mark.asyncio
async def test_n19_patch_recursively_scores_full_candidate_generation_module():
    evaluation = {
        "original_search_plan": {
            "anchor_accuracy": 5, "query_coverage": 5, "plan_targeting": 5,
            "comment": "",
        },
        "selected_original_meme": {
            "popularity": 5, "applicability": 5, "adaptability": 5,
            "evidence_reliability": 5, "comment": "",
        },
        "variant_search_plan": {
            "slot_replacement_targeting": 5, "query_diversity": 5,
            "ugc_orientation": 5, "noise_avoidance": 5, "comment": "",
        },
        "variant_search_results": {
            "relevance": 5, "real_variant_ratio": 5,
            "independent_evidence_quality": 5, "variant_diversity": 5,
            "comment": "",
        },
        "template_extraction": {
            "accuracy": 5, "original_reconstruction": 5,
            "variant_coverage": 5, "slot_rationality": 5, "comment": "",
        },
        "candidate_generation": {
            "overall": {
                "effective_difference": 3, "natural_rewrite_coverage": 5,
                "overall_selectable_quality": 5, "comment": "候选差异不足",
            },
            "candidates": {
                "C1": {
                    "fluency": 2, "original_meme_recognition": 5,
                    "agu_zao_naturalness": 5, "humor": 5, "template_logic": 5,
                    "usability": "USABLE_AFTER_EDIT", "modification_advice": "改善语序",
                },
                "C2": {
                    "fluency": 5, "original_meme_recognition": 5,
                    "agu_zao_naturalness": 5, "humor": 5, "template_logic": 5,
                    "usability": "USABLE", "modification_advice": "",
                },
                "C3": {
                    "fluency": 5, "original_meme_recognition": 5,
                    "agu_zao_naturalness": 5, "humor": 5, "template_logic": 5,
                    "usability": "USABLE", "modification_advice": "",
                },
                "C4": {
                    "fluency": 5, "original_meme_recognition": 5,
                    "agu_zao_naturalness": 5, "humor": 5, "template_logic": 5,
                    "usability": "USABLE", "modification_advice": "",
                },
                "C5": {
                    "fluency": 5, "original_meme_recognition": 5,
                    "agu_zao_naturalness": 5, "humor": 5, "template_logic": 5,
                    "usability": "USABLE", "modification_advice": "",
                },
            },
        },
        "final_result": {
            "is_best_candidate": True, "better_candidate_id": None,
            "fluency": 5, "original_meme_recognition": 5, "agu_zao_fit": 5,
            "humor": 5, "overall_satisfaction": 5, "comment": "",
        },
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "feedback_summary": "候选质量需改进",
            "affected_nodes": [],
            "patch_operations": [],
            "score_gaps": {},
            "next_round_hypotheses": [],
        }]),
        search=FakeSearchProvider(),
    )

    result = await registry.get("N19").execute({"N18": evaluation}, None)
    artifact = result["artifact"]

    assert artifact["score_gaps"] == {
        "candidate_generation.overall.effective_difference": 1,
        "candidate_generation.candidates.C1.fluency": 2,
    }
    assert artifact["affected_nodes"] == ["N12", "N13", "N14"]


def test_patch_operations_merge_llm_advice_with_whitelist_deduplication_and_text_limit():
    long_advice = "优先网友槽位改编" * 100
    evaluation = {
        "variant_search_plan": {
            "slot_replacement_targeting": 5,
            "query_diversity": 5,
            "ugc_orientation": 5,
            "noise_avoidance": 5,
            "comment": "",
        },
        "variant_search_results": {
            "relevance": 5,
            "real_variant_ratio": 5,
            "independent_evidence_quality": 5,
            "variant_diversity": 5,
            "comment": "",
        },
        "template_extraction": {
            "accuracy": 3,
            "original_reconstruction": 5,
            "variant_coverage": 5,
            "slot_rationality": 5,
            "comment": "模板覆盖不足",
        },
    }
    llm_patch = [
        {"op": "add", "path": "/search/variant_query_directives/-", "value": long_advice},
        {"op": "add", "path": "/search/variant_query_directives/-", "value": long_advice},
        {"op": "replace", "path": "/budgets/max_cost", "value": 999},
        {"op": "remove", "path": "/search/prefer_ugc_sources"},
    ]

    operations = derive_required_patch_operations(evaluation, llm_patch)

    assert all(op["path"] != "/budgets/max_cost" for op in operations)
    assert all(op["op"] in {"add", "replace"} for op in operations)
    llm_directives = [
        op["value"] for op in operations
        if op["path"] == "/search/variant_query_directives/-"
        and str(op["value"]).startswith("优先网友槽位改编")
    ]
    assert len(llm_directives) == 1
    assert len(llm_directives[0]) == 300
    assert any(
        op["path"] == "/search/variant_query_directives/-"
        and "模板覆盖不足" in str(op["value"])
        for op in operations
    )


def test_llm_patch_cannot_relax_quality_thresholds_or_protection_switches():
    llm_patch = [
        {"op": "replace", "path": "/search/minimum_valid_variants", "value": 1},
        {"op": "replace", "path": "/search/minimum_template_coverage", "value": 0},
        {"op": "replace", "path": "/search/max_variant_search_retries", "value": 10},
        {"op": "replace", "path": "/search/exclude_exact_reprints", "value": False},
        {"op": "replace", "path": "/search/require_slot_replacement", "value": False},
        {"op": "replace", "path": "/generation/prefer_minimal_replacement", "value": False},
        {
            "op": "add",
            "path": "/search/variant_query_directives/-",
            "value": "优先独立网友槽位改编",
        },
    ]

    operations = derive_required_patch_operations({}, llm_patch)

    assert operations == [{
        "op": "add",
        "path": "/search/variant_query_directives/-",
        "value": "优先独立网友槽位改编",
    }]


@pytest.mark.asyncio
async def test_n19_patch_artifact_contains_required_feedback_translation_fields():
    evaluation = {
        "variant_search_plan": {
            "slot_replacement_targeting": 2,
            "query_diversity": 3,
            "ugc_orientation": 2,
            "noise_avoidance": 2,
            "comment": "结果基本都是原句转载",
        },
        "variant_search_results": {
            "relevance": 3,
            "real_variant_ratio": 1,
            "independent_evidence_quality": 2,
            "variant_diversity": 2,
            "comment": "没有网友槽位改编",
        },
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "feedback_summary": "需要提高变式搜索质量",
            "affected_nodes": ["N07", "N09", "NOT_A_NODE"],
            "patch_operations": [{
                "op": "add",
                "path": "/search/variant_query_directives/-",
                "value": "优先搜索独立网友改编",
            }, {
                "op": "replace",
                "path": "/safety/allow_unsafe",
                "value": True,
            }],
            "score_gaps": {"untrusted": 99},
            "next_round_hypotheses": ["真实变式比例提升"],
        }]),
        search=FakeSearchProvider(),
    )

    result = await registry.get("N19").execute({"N18": evaluation}, None)
    artifact = result["artifact"]

    assert set(artifact) >= {
        "feedback_summary", "affected_nodes", "patch_operations", "score_gaps",
        "next_round_hypotheses", "before_strategy_version_id",
        "after_strategy_version_id",
    }
    assert artifact["score_gaps"]["variant_search_results.real_variant_ratio"] == 3
    assert "untrusted" not in artifact["score_gaps"]
    assert "NOT_A_NODE" not in artifact["affected_nodes"]
    assert all(op["path"] != "/safety/allow_unsafe" for op in artifact["patch_operations"])


def test_n05_compacts_search_pages_without_dropping_seed_evidence():
    seed = "你们干什么？我是来开会的！"
    exact_evidence = "我是来开会的，你们要干什么？"
    sources = [{
        "source_id": f"O{index:03d}",
        "url": f"https://example.com/{index}",
        "title": f"搜索结果{index}",
        "text": ("无关正文" * 700) + (exact_evidence if index == 12 else "无关结尾"),
        "status": "VALID",
        "evidence_type": "EXTRACTED_TEXT",
    } for index in range(1, 13)]

    compact = _compact_artifacts("N05", {
        "START": {"mode": "MANUAL_SEED", "seed_text": seed},
        "N04": {"sources": sources, "results": sources},
    })

    serialized = json.dumps(compact, ensure_ascii=False)
    assert len(serialized) <= 12_000
    assert any(exact_evidence in source["text"] for source in compact["N04"]["sources"])


@pytest.mark.asyncio
async def test_real_registry_nodes_call_configured_providers():
    llm = FakeLLMProvider(responses=[{"ok": True}])
    search = FakeSearchProvider(batches=[SearchBatch(results=[SearchResult(
        url="https://example.com", canonical_url="https://example.com", title="source", text="text",
    )])])
    registry = build_real_registry(llm=llm, search=search)
    n01 = await registry.get("N03").execute({
        "START": {"seed_text": "大胆妖孽，我一眼就看出你不是人"},
    }, None)
    n04 = await registry.get("N04").execute({"seed_text": "x"}, None)
    assert n01["outcome"] == "PLAN_READY"
    assert n04["outcome"] == "RESULTS_FOUND"
    assert len(llm.requests) == 1
    assert len(search.requests) == 1


@pytest.mark.asyncio
async def test_n02_allocates_enough_output_budget_for_reasoning_model_json():
    llm = FakeLLMProvider(responses=[{
        "discovery_hypothesis": "寻找可替换结构的流行台词",
        "keywords": ["台词梗"],
        "known_example_phrases": ["小孩子才做选择，我全都要"],
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    await registry.get("N02").execute({"START": {"mode": "AUTO_DISCOVERY"}}, None)

    assert llm.requests[0].parameter_profile.max_output_tokens >= 4000

@pytest.mark.asyncio
async def test_real_registry_enforces_candidate_and_draft_contracts():
    texts = [
        "你说的对，但是凿具是由老王自主研发的一款趁手工具，他正用它凿agu。",
        "你说的对，但是凿法是由老李自主研发的一款独门手艺，他已经凿了agu。",
        "你说的对，但是铁凿是由师傅自主研发的一款坚固工具，大家正拿它凿agu。",
        "你说的对，但是凿术是由工匠自主研发的一款实用技术，我正在用它凿agu。",
        "你说的对，但是石凿是由阿强自主研发的一款专业器具，他刚刚凿了agu。",
    ]
    llm = FakeLLMProvider(responses=[
        {"route_used": "STRUCTURE_PRESERVING_REWRITE", "candidates": [
            {"candidate_id": f"C{i}", "text": text} for i, text in enumerate(texts, 1)
        ]},
        {"selected_candidate_id": "C3", "ranked_candidate_ids": ["C3", "C2"]},
        {"title": "测试梗", "final_agu_text": "改写内容"},
    ])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    n12 = await registry.get("N12").execute({
        "N11.5": {
            "route": "STRUCTURE_PRESERVING_REWRITE",
            "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
        }
    }, None)
    candidates = n12["artifact"]["llm"]["candidates"]
    n14 = await registry.get("N14").execute({
        "N12": {"llm": {"candidates": candidates}},
        "N13": {"llm": {"qualified_candidate_ids": ["C2", "C3"]}},
    }, None)
    assert n14["artifact"]["llm"]["selected_candidate_id"] == "C3"
    n15 = await registry.get("N15").execute({
        "N05": {"title": "原梗", "original_text": "原始梗"},
        "N10": {"canonical_template_text": "模板"},
        "N12": {"llm": {"candidates": candidates}},
        "N14": n14["artifact"],
    }, None)
    assert n15["artifact"]["llm"]["final_agu_text"] == candidates[2]["text"]


@pytest.mark.asyncio
async def test_n12_normalizes_lowercase_candidate_ids_before_contract_validation():
    texts = [
        f"你这是在玩火，他们正在凿agu，第{i}次。" for i in range(1, 6)
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "route_used": "STRUCTURE_PRESERVING_REWRITE",
            "candidates": [
                {"candidate_id": f"c{i}", "text": text}
                for i, text in enumerate(texts, 1)
            ],
        }]),
        search=FakeSearchProvider(),
    )
    result = await registry.get("N12").execute({
        "N11.5": {
            "route": "STRUCTURE_PRESERVING_REWRITE",
            "must_preserve": ["你这是在玩火"],
        },
    }, None)
    assert [item["candidate_id"] for item in result["artifact"]["llm"]["candidates"]] == [
        "C1", "C2", "C3", "C4", "C5",
    ]


@pytest.mark.asyncio
async def test_variant_search_uses_selected_original_meme_anchor():
    search = FakeSearchProvider(batches=[SearchBatch(results=[])])
    registry = build_real_registry(llm=FakeLLMProvider(), search=search)
    artifacts = {"N05": {"original_text": "大胆妖孽，我一眼就看出你不是人", "fixed_anchors": ["大胆", "我一眼就看出"]}}
    await registry.get("N08").execute(artifacts, None)
    assert search.requests
    assert "大胆妖孽" in search.requests[0].query


@pytest.mark.asyncio
async def test_invalid_n12_never_fabricates_duplicate_candidates():
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{"route_used": "STRUCTURE_PRESERVING_REWRITE", "candidates": []}]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="exactly five"):
        await registry.get("N12").execute({"N11.5": {"route": "STRUCTURE_PRESERVING_REWRITE"}}, None)


@pytest.mark.asyncio
async def test_n12_rejects_candidates_that_only_contain_tokens_without_action_semantics():
    invalid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [{"candidate_id": f"C{i}", "text": f"agu凿{i}"} for i in range(1, 6)],
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[invalid, invalid, invalid]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="receiving the action"):
        await registry.get("N12").execute({"N11.5": {"route": "STRUCTURE_PRESERVING_REWRITE"}}, None)


@pytest.mark.asyncio
async def test_n12_retries_two_invalid_batches_and_records_every_llm_call():
    invalid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": f"agu凿{i}"}
            for i in range(1, 6)
        ],
    }
    valid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": f"他们正在凿agu，这是第{i}次。"}
            for i in range(1, 6)
        ],
    }
    llm = FakeLLMProvider(responses=[invalid, invalid, valid])
    repository = UsageRepositoryStub()
    registry = build_real_registry(
        llm=llm,
        search=FakeSearchProvider(),
        repository=repository,
    )

    result = await registry.get("N12").execute(
        {"N11.5": {"route": "STRUCTURE_PRESERVING_REWRITE"}},
        {"run_id": "run-n12-retry"},
    )

    assert len(llm.requests) == 3
    assert len(repository.api_calls) == 3
    assert result["outcome"] == "VALID_BATCH"
    assert result["artifact"]["llm"]["candidates"][0]["text"] == "他们正在凿agu，这是第1次。"
    assert llm.requests[2].user_payload["invalid_previous_output"] == invalid
    assert "receiving the action" in llm.requests[2].user_payload["validation_error"]


@pytest.mark.asyncio
async def test_n12_accepts_ba_and_passive_forms_where_agu_receives_the_action():
    texts = [
        "他们正在凿agu，这是第一回。",
        "他们已经把agu凿了，这是第二回。",
        "agu又被他们凿了，这是第三回。",
        "高程群的agu让群友凿了，这是第四回。",
        "同济大学的人将同济大学的agu凿了一遍，这是第五回。",
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "route_used": "STRUCTURE_PRESERVING_REWRITE",
            "candidates": [
                {"candidate_id": f"C{i}", "text": text}
                for i, text in enumerate(texts, 1)
            ],
        }]),
        search=FakeSearchProvider(),
    )

    result = await registry.get("N12").execute(
        {"N11.5": {"route": "STRUCTURE_PRESERVING_REWRITE"}},
        None,
    )

    assert [item["text"] for item in result["artifact"]["llm"]["candidates"]] == texts


@pytest.mark.asyncio
async def test_n12_drops_null_bindings_for_optional_template_slots():
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "route_used": "STRUCTURE_PRESERVING_REWRITE",
            "candidates": [
                {
                    "candidate_id": f"C{i}",
                    "text": f"他们凿agu时，我的内心毫无波动，甚至还想笑，第{i}回。",
                    "slot_bindings": {
                        "前置情境": "他们凿agu时",
                        "后续内容": None,
                    },
                }
                for i in range(1, 6)
            ],
        }]),
        search=FakeSearchProvider(),
    )

    result = await registry.get("N12").execute(
        {
            "N11.5": {
                "route": "STRUCTURE_PRESERVING_REWRITE",
                "must_preserve": ["我的内心毫无波动，甚至还想笑"],
                "integration_mode": "CAUSAL_CONTEXT",
            }
        },
        None,
    )

    bindings = result["artifact"]["llm"]["candidates"][0]["slot_bindings"]
    assert bindings == {"前置情境": "他们凿agu时"}


@pytest.mark.asyncio
async def test_n12_structure_rewrite_preserves_required_template_anchors():
    invalid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": f"他们正在凿agu，第{i}次。"}
            for i in range(1, 6)
        ],
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[invalid, invalid, invalid]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="preserve required template anchors"):
        await registry.get("N12").execute({
            "N11.5": {
                "route": "STRUCTURE_PRESERVING_REWRITE",
                "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
            }
        }, None)


@pytest.mark.asyncio
async def test_n12_rejects_mechanical_catchphrase_plus_action_append():
    actions = ["我正在凿agu", "他已经凿了agu", "大家来凿agu", "我们正在凿agu", "他们都在凿agu"]
    invalid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": f"我读书少，你不要骗我，{action}。"}
            for i, action in enumerate(actions, 1)
        ],
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[invalid, invalid, invalid]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="causally integrate"):
        await registry.get("N12").execute({
            "N11.5": {
                "route": "STRUCTURE_PRESERVING_REWRITE",
                "must_preserve": ["我读书少，你不要骗我"],
                "integration_mode": "CAUSAL_CONTEXT",
            },
        }, None)


@pytest.mark.asyncio
async def test_n12_rejects_bare_action_as_replaceable_slot_content():
    actions = ["我正在凿agu", "他已经凿了agu", "大家来凿agu", "我们正在凿agu", "他们都在凿agu"]
    invalid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": f"我走过最长的路，{action}。"}
            for i, action in enumerate(actions, 1)
        ],
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[invalid, invalid, invalid]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="template-compatible slot content"):
        await registry.get("N12").execute({
            "N11.5": {
                "route": "STRUCTURE_PRESERVING_REWRITE",
                "must_preserve": ["我走过最长的路，"],
                "integration_mode": "SLOT_FILL",
            },
        }, None)


@pytest.mark.asyncio
async def test_n05_rejects_generator_or_tool_page_as_original_meme():
    source = {
        "source_id": "O001",
        "url": "https://example.com/meme-generator",
        "title": "Meme 生成器 - 在线制作梗图文案和模板",
        "text": "免费 meme 生成器会把笑点转成文案选项和视觉方向。",
    }
    selected = {
        "title": source["title"],
        "original_text": source["text"],
        "fixed_anchors": ["meme 生成器"],
        "source_id": "O001",
        "source_url": source["url"],
        "evidence_quote": source["text"],
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[selected]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="tool or generator page"):
        await registry.get("N05").execute({"N04": {"sources": [source]}}, None)


@pytest.mark.asyncio
async def test_n05_rejects_definition_sentence_even_when_quote_is_real():
    definition = "我自闭了，就是调侃自己开始消极、颓废等状态了。"
    source = {
        "source_id": "O001",
        "url": "https://example.com/encyclopedia",
        "title": "我自闭了是什么梗-梗百科",
        "text": definition,
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "title": source["title"],
            "original_text": definition,
            "fixed_anchors": ["我自闭了"],
            "source_id": source["source_id"],
            "source_url": source["url"],
            "evidence_quote": definition,
        }]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="definition or explanatory"):
        await registry.get("N05").execute({"N04": {"sources": [source]}}, None)


@pytest.mark.asyncio
async def test_n05_extracts_core_catchphrase_from_long_evidence_quote():
    quote = (
        "我八岁那年，我碰到一个算命先生，算命先生说我二十四岁会黄袍加身。"
        "我信你个鬼，你个糟老头子坏得很，算得真准。"
    )
    source = {
        "source_id": "O001", "url": "https://example.com/source",
        "title": "糟老头子坏得很", "text": quote,
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "title": source["title"], "original_text": quote,
            "fixed_anchors": ["我信你个鬼", "糟老头子坏得很"],
            "source_id": source["source_id"], "source_url": source["url"],
            "evidence_quote": quote,
        }]),
        search=FakeSearchProvider(),
    )
    result = await registry.get("N05").execute({
        "N02": {"known_example_phrases": ["我信你个鬼，你个糟老头子坏得很"]},
        "N04": {"sources": [source]},
    }, None)
    assert result["artifact"]["llm"]["original_text"] == (
        "我信你个鬼，你个糟老头子坏得很，算得真准"
    )
    assert result["artifact"]["llm"]["evidence_quote"] == quote


@pytest.mark.asyncio
async def test_auto_discovery_requires_concrete_example_phrases():
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "discovery_hypothesis": "找中文经典梗",
            "keywords": ["中文梗", "模板"],
            "known_example_phrases": [],
        }]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="concrete example phrase"):
        await registry.get("N02").execute({"START": {"mode": "AUTO_DISCOVERY"}}, None)


@pytest.mark.asyncio
async def test_auto_discovery_retries_empty_candidate_list_before_failing_run():
    llm = FakeLLMProvider(responses=[
        {"known_example_phrases": []},
        {"known_example_phrases": [
            "大胆妖孽，我一眼就看出你不是人",
            "抛开事实不谈，难道你就没有错吗",
            "你这是在玩火",
        ]},
    ])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N02").execute({
        "START": {"mode": "AUTO_DISCOVERY"},
    }, None)
    assert result["artifact"]["llm"]["known_example_phrases"][0].startswith("大胆妖孽")
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_auto_discovery_exhausted_original_is_not_selected_again():
    exhausted = "我猜中了开头，却猜不中这结局"
    alternative = "大胆妖孽，我一眼就看出你不是人"
    source = {
        "source_id": "O001",
        "url": "https://forum.example/original",
        "title": "原梗转载",
        "text": exhausted,
    }
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
    )
    context.__dict__["exhausted_originals"] = [exhausted]
    context.strategy_snapshot.exhausted_originals = context.exhausted_originals
    services = {"strategy_snapshot": context.strategy_snapshot}
    llm = FakeLLMProvider(responses=[
        {
            "discovery_hypothesis": "重新寻找可改编原梗",
            "keywords": ["中文梗", "台词梗"],
            "known_example_phrases": [exhausted, alternative],
        },
        {
            "title": source["title"],
            "original_text": exhausted,
            "fixed_anchors": ["我猜中了", "却猜不中"],
            "source_id": source["source_id"],
            "source_url": source["url"],
            "evidence_quote": exhausted,
        },
    ])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    n02 = await registry.get("N02").execute(
        {"START": {"mode": "AUTO_DISCOVERY"}}, services,
    )

    assert n02["artifact"]["llm"]["known_example_phrases"] == [alternative]
    assert llm.requests[0].user_payload["excluded_originals"] == [
        "我猜中了开头却猜不中这结局",
    ]

    n05 = await registry.get("N05").execute({
        "N02": n02["artifact"],
        "N04": {"sources": [source]},
    }, services)

    assert n05["outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert n05["artifact"]["rejection_reason"] == "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE"
    assert len(llm.requests) == 1
    assert TransitionTable().next(
        "N05", n05["outcome"], mode=RunMode.AUTO_DISCOVERY.value,
    ) == "WAITING_HUMAN_INTERVENTION"


@pytest.mark.asyncio
async def test_auto_repeated_discovery_cycles_stop_before_n05_on_exhausted_evidence():
    exhausted = "万万没想到事情竟然会变成这样"
    traditional = "萬萬沒想到事情竟然會變成這樣"
    alternative = "大胆妖孽，我一眼就看出你不是人"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
        exhausted_originals=[exhausted],
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    llm = FakeLLMProvider(responses=[
        {"known_example_phrases": [traditional, alternative]},
        {"known_example_phrases": [traditional, alternative]},
    ])
    repeated_source = SearchResult(
        url="https://forum.example/repeated",
        canonical_url="https://forum.example/repeated",
        title="原句转载",
        text=f"帖子里写道，{traditional}，围观的人都笑了",
    )
    search = FakeSearchProvider(batches=[
        SearchBatch(results=[repeated_source]),
        SearchBatch(results=[repeated_source]),
    ])
    registry = build_real_registry(llm=llm, search=search)

    for _ in range(2):
        n02 = await registry.get("N02").execute(
            {"START": {"mode": "AUTO_DISCOVERY"}}, services,
        )
        assert n02["artifact"]["llm"]["known_example_phrases"] == [alternative]
        n04 = await registry.get("N04").execute({
            "N03": {"queries": [{
                "query_id": "OQ1",
                "query": traditional,
                "search_type": "keyword",
            }]},
        }, services)
        assert n04["outcome"] == "HUMAN_REVIEW_REQUIRED"
        assert n04["artifact"]["sources"] == []
        assert n04["artifact"]["rejection_reason"] == (
            "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE"
        )
        assert TransitionTable().next(
            "N04", n04["outcome"], mode=RunMode.AUTO_DISCOVERY.value,
        ) == "WAITING_HUMAN_INTERVENTION"

    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_auto_discovery_keeps_new_fragment_from_mixed_exhausted_source():
    exhausted = "我猜中了开头，却猜不中这结局"
    alternative = "大胆妖孽，我一眼就看出你不是人"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
        exhausted_originals=[exhausted],
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    source = SearchResult(
        url="https://forum.example/mixed",
        canonical_url="https://forum.example/mixed",
        title=exhausted,
        text=f"原帖写道：{exhausted}。\n网友还说：{alternative}。",
    )
    search = FakeSearchProvider(batches=[SearchBatch(results=[source])])
    llm = FakeLLMProvider(responses=[{
        "title": "新梗候选",
        "original_text": alternative,
        "fixed_anchors": ["大胆妖孽", "一眼就看出"],
        "source_id": "O001",
        "source_url": source.url,
        "evidence_quote": alternative,
    }])
    registry = build_real_registry(llm=llm, search=search)

    n04 = await registry.get("N04").execute({
        "N03": {"queries": [{
            "query_id": "OQ1", "query": exhausted, "search_type": "keyword",
        }]},
    }, services)

    assert n04["outcome"] == "RESULTS_FOUND"
    assert len(n04["artifact"]["sources"]) == 1
    filtered_source = n04["artifact"]["sources"][0]
    assert exhausted not in filtered_source["title"]
    assert exhausted not in filtered_source["text"]
    assert alternative in filtered_source["text"]

    n05 = await registry.get("N05").execute({
        "N04": {"sources": n04["artifact"]["sources"]},
    }, services)

    assert n05["outcome"] == "SELECTED"
    assert n05["artifact"]["llm"]["original_text"] == alternative
    assert len(llm.requests) == 1


@pytest.mark.asyncio
async def test_auto_discovery_keeps_new_evidence_after_exhausted_same_fragment():
    exhausted = "我猜中了开头，却猜不中这结局"
    alternative = "大胆妖孽，我一眼就看出你不是人"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
        exhausted_originals=[exhausted],
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    source = SearchResult(
        url="https://forum.example/same-fragment",
        canonical_url="https://forum.example/same-fragment",
        title=exhausted,
        text=f"{exhausted}，网友还说：{alternative}。",
    )
    search = FakeSearchProvider(batches=[SearchBatch(results=[source])])
    llm = FakeLLMProvider(responses=[{
        "title": "新梗候选",
        "original_text": alternative,
        "fixed_anchors": ["大胆妖孽", "一眼就看出"],
        "source_id": "O001",
        "source_url": source.url,
        "evidence_quote": alternative,
    }])
    registry = build_real_registry(llm=llm, search=search)

    n04 = await registry.get("N04").execute({
        "N03": {"queries": [{
            "query_id": "OQ1", "query": exhausted, "search_type": "keyword",
        }]},
    }, services)

    assert n04["outcome"] == "RESULTS_FOUND"
    assert len(n04["artifact"]["sources"]) == 1
    filtered_source = n04["artifact"]["sources"][0]
    assert exhausted not in filtered_source["text"]
    assert alternative in filtered_source["text"]

    n05 = await registry.get("N05").execute({
        "N04": {"sources": n04["artifact"]["sources"]},
    }, services)

    assert n05["outcome"] == "SELECTED"
    assert n05["artifact"]["llm"]["original_text"] == alternative
    assert len(llm.requests) == 1


@pytest.mark.asyncio
async def test_exhausted_filter_uses_canonical_single_glyph_script_identity():
    original = "设计一个自动触发弹窗"
    traditional = "设计一个自动觸发弹窗"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
        exhausted_originals=[original],
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    source = SearchResult(
        url="https://forum.example/traditional-reprint",
        canonical_url="https://forum.example/traditional-reprint",
        title=traditional,
        text=traditional + "。",
    )
    registry = build_real_registry(
        llm=FakeLLMProvider(),
        search=FakeSearchProvider(batches=[SearchBatch(results=[source])]),
    )

    result = await registry.get("N04").execute({
        "N03": {"queries": [{
            "query_id": "OQ1", "query": original, "search_type": "keyword",
        }]},
    }, services)

    assert result["outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert result["artifact"]["sources"] == []
    assert result["artifact"]["rejection_reason"] == (
        "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE"
    )


@pytest.mark.asyncio
async def test_n04_rejects_generic_title_after_exhausted_body_is_removed():
    exhausted = "我猜中了开头，却猜不中这结局"
    generic_title = "今天大家都在讨论这个话题"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
        exhausted_originals=[exhausted],
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    source = SearchResult(
        url="https://forum.example/generic-title",
        canonical_url="https://forum.example/generic-title",
        title=generic_title,
        text=exhausted + "。",
    )
    registry = build_real_registry(
        llm=FakeLLMProvider(),
        search=FakeSearchProvider(batches=[SearchBatch(results=[source])]),
    )

    result = await registry.get("N04").execute({
        "N03": {"queries": [{
            "query_id": "OQ1", "query": exhausted, "search_type": "keyword",
        }]},
    }, services)

    assert result["outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert result["artifact"]["sources"] == []
    assert result["artifact"]["rejection_reason"] == (
        "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE"
    )
    assert TransitionTable().next(
        "N04", result["outcome"], mode=RunMode.AUTO_DISCOVERY.value,
    ) == "WAITING_HUMAN_INTERVENTION"


@pytest.mark.asyncio
async def test_n05_rejects_unverified_title_only_after_exhausted_body_removal():
    exhausted = "我猜中了开头，却猜不中这结局"
    generic_title = "今天大家都在讨论这个话题"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
        exhausted_originals=[exhausted],
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    llm = FakeLLMProvider(responses=[{
        "title": generic_title,
        "original_text": generic_title,
        "fixed_anchors": ["今天大家", "讨论话题"],
        "source_id": "O001",
        "source_url": "https://forum.example/generic-title",
        "evidence_quote": generic_title,
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N05").execute({
        "N04": {"sources": [{
            "source_id": "O001",
            "url": "https://forum.example/generic-title",
            "title": generic_title,
            "text": exhausted + "。",
        }]},
    }, services)

    assert result["outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert result["artifact"]["sources"] == []
    assert result["artifact"]["rejection_reason"] == (
        "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE"
    )
    assert llm.requests == []


@pytest.mark.asyncio
async def test_auto_discovery_prompt_includes_only_formal_meme_titles():
    repository = FormalMemeRepositoryStub()
    llm = FakeLLMProvider(responses=[{
        "discovery_hypothesis": "换一个未收录的梗",
        "keywords": ["新梗"],
        "known_example_phrases": ["大胆妖孽，我一眼就看出你不是人"],
    }])
    registry = build_real_registry(
        llm=llm, search=FakeSearchProvider(), repository=repository,
    )
    await registry.get("N02").execute({"START": {"mode": "AUTO_DISCOVERY"}}, None)
    payload = llm.requests[0].user_payload
    assert payload["formal_meme_titles"] == [{
        "id": "existing-1",
        "title": "凿agu版·小孩才做选择，我全都要是什么梗",
    }]
    assert "original_meme_text" not in str(payload)


@pytest.mark.asyncio
async def test_n06_reads_suspected_record_and_rejects_semantic_duplicate():
    repository = FormalMemeRepositoryStub()
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(), repository=repository,
    )
    result = await registry.get("N06").execute({
        "N05": {
            "title": "网络语小孩子才做选择，我全都要什么梗",
            "original_text": "小孩子才做选择，我全都要",
        },
    }, None)
    assert result["outcome"] == "DUPLICATE"
    assert result["artifact"]["suspected_meme_id"] == "existing-1"
    assert result["artifact"]["existing_original_text"] == "小孩才做选择，我全都要"
    assert repository.detail_requests == ["existing-1"]


@pytest.mark.asyncio
async def test_auto_search_plan_is_rebuilt_from_concrete_phrase_instead_of_generic_query():
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{"queries": [{
            "query_id": "Q1", "query": "中文经典文案梗 模板 变式", "search_type": "auto",
        }]}]),
        search=FakeSearchProvider(),
    )
    result = await registry.get("N03").execute({
        "START": {"mode": "AUTO_DISCOVERY"},
        "N02": {"known_example_phrases": ["大胆妖孽，我一眼就看出你不是人"]},
    }, None)
    queries = result["artifact"]["llm"]["queries"]
    assert len(queries) >= 3
    assert all("大胆妖孽" in item["query"] for item in queries)
    assert all("中文经典文案梗" not in item["query"] for item in queries)


@pytest.mark.asyncio
async def test_auto_search_plan_covers_multiple_independent_meme_phrases():
    phrases = [
        "大胆妖孽，我一眼就看出你不是人",
        "抛开事实不谈，难道你就没有错吗",
        "你这是在玩火",
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{"queries": [{
            "query_id": "Q1", "query": "中文经典文案梗", "search_type": "auto",
        }]}]),
        search=FakeSearchProvider(),
    )
    result = await registry.get("N03").execute({
        "START": {"mode": "AUTO_DISCOVERY"},
        "N02": {"known_example_phrases": phrases},
    }, None)
    queries = result["artifact"]["llm"]["queries"]
    assert len(queries) == 5
    assert all(any(phrase in item["query"] for item in queries) for phrase in phrases)
    assert all("中文经典文案梗" not in item["query"] for item in queries)


@pytest.mark.asyncio
async def test_n10_rejects_template_that_does_not_explain_original_and_variants():
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{
            "canonical_template_text": "{原梗}", "fixed_segments": [],
            "slots": [{"name": "原梗"}], "evidence_variant_texts": [],
        }]),
        search=FakeSearchProvider(),
    )
    artifacts = {
        "N05": {"original_text": "大胆妖孽，我一眼就看出你不是人"},
        "N09": {"variants": [
            {"variant_text": "大胆猫猫，我一眼就看出你不是人"},
            {"variant_text": "大胆程序员，我一眼就看出你不是产品经理"},
            {"variant_text": "大胆机器人，我一眼就看出你不是人类"},
        ]},
    }
    with pytest.raises(ValueError, match="fixed structure"):
        await registry.get("N10").execute(artifacts, None)


@pytest.mark.asyncio
async def test_n07_builds_variant_queries_from_selected_original_without_llm_dependency():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N07").execute({
        "N05": {
            "original_text": "小孩子才做选择，我全都要",
            "fixed_anchors": ["小孩子才做选择", "我全都要"],
        }
    }, None)
    queries = result["artifact"]["llm"]["queries"]
    assert len(queries) == 5
    assert all("小孩子才做选择" in item["query"] for item in queries)
    assert llm.requests == []


@pytest.mark.parametrize(("candidate", "expected"), [
    ("我猜中了开头，却猜不中这结局", False),
    ("我猜中了開頭，卻猜不中這結局", False),
    ("我猜中了开头，却猜不中这结局是什么意思", False),
    ("句子赏析：我猜中了开头，却猜不中这结局", False),
    ("我猜中了开头，却猜不中agu被谁凿了", True),
    ("网友改成了我猜中了开头，却猜不中agu被谁凿了，笑死", False),
    ("今天看到一句话，我猜中了开头，却猜不中这结局，真的很有感触", False),
])
def test_substantive_variant_filter(candidate, expected):
    assert real_registry.is_substantive_variant(
        "我猜中了开头，却猜不中这结局",
        candidate,
        ["我猜中了", "却猜不中"],
    ) is expected


def test_substantive_variant_filter_rejects_traditional_reprint():
    assert real_registry.is_substantive_variant(
        "这个网络热门话题总是让人意想不到",
        "這個網絡熱門話題總是讓人意想不到",
        ["网络热门话题", "让人意想不到"],
    ) is False


@pytest.mark.parametrize(("candidate", "expected"), [
    ("设计一个自动觸发弹窗", False),
    ("设计一个自动触发彈窗", False),
    ("帖子里写道，设计一个自动觸发弹窗，围观的人都笑了", False),
    ("帖子里写道，设计一个自动触发彈窗，围观的人都笑了", False),
    ("设计一个自动关闭弹窗", True),
])
def test_script_identity_distinguishes_traditional_glyphs_from_semantic_slots(
    candidate, expected,
):
    assert real_registry.is_substantive_variant(
        "设计一个自动触发弹窗",
        candidate,
        ["设计一个", "弹窗"],
    ) is expected


def test_script_identity_is_shared_by_duplicate_similarity():
    original = "设计一个自动触发弹窗"

    assert real_registry._duplicate_similarity(
        original, "设计一个自动觸发弹窗",
    ) == 1.0
    assert real_registry._duplicate_similarity(
        original, "设计一个自动关闭弹窗",
    ) < 1.0


@pytest.mark.parametrize(("candidate", "expected"), [
    ("萬萬沒想到事情竟然會變成這樣", False),
    ("萬万没想到事情竟然会變成这样", False),
    ("帖子里写道，萬萬沒想到事情竟然會變成這樣，围观的人都笑了", False),
    ("萬萬沒想到群友竟然會把agu凿成這樣", True),
])
def test_traditional_and_mixed_glyph_variants_share_one_canonical_comparison(
    candidate, expected,
):
    assert real_registry.is_substantive_variant(
        "万万没想到事情竟然会变成这样",
        candidate,
        ["万万没想到", "竟然会变成这样"],
    ) is expected


def test_traditional_equivalent_original_is_an_exact_duplicate():
    assert real_registry._duplicate_similarity(
        "万万没想到事情竟然会变成这样",
        "萬萬沒想到事情竟然會變成這樣",
    ) == 1.0


@pytest.mark.asyncio
async def test_n07_strategy_query_uses_feedback_and_ugc_preference():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    directive = "优先搜索论坛帖子里的网友槽位替换，排除百科释义"

    result = await registry.get("N07").execute({
        "N05": {
            "original_text": "我猜中了开头，却猜不中这结局",
            "fixed_anchors": ["我猜中了", "却猜不中"],
        },
    }, {
        "strategy_version_id": "strategy-v2",
        "strategy_snapshot": {"search": {
            "prefer_ugc_sources": True,
            "require_slot_replacement": True,
            "variant_query_directives": [directive],
        }},
    })

    artifact = result["artifact"]
    queries = artifact["llm"]["queries"]
    assert artifact["planning_mode"] == "STRATEGY_GUIDED"
    assert artifact["strategy_version_id"] == "strategy-v2"
    assert artifact["applied_directives"] == [directive]
    assert 4 <= len(queries) <= 6
    assert sum(item["query"] == "我猜中了开头，却猜不中这结局" for item in queries) == 1
    assert any("槽位替换" in item["purpose"] for item in queries)
    assert any("UGC" in item["purpose"] for item in queries)
    assert any("论坛" in item["query"] for item in queries)
    assert all(item["strategy_origin"] for item in queries)
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n07_applied_directives_only_lists_queries_that_consumed_them():
    directives = [
        "优先搜索论坛里的真实改写",
        "排除百科页面和原句转载",
        "补充微博评论区里的槽位替换",
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N07").execute({
        "N05": {
            "original_text": "我猜中了开头，却猜不中这结局",
            "fixed_anchors": ["我猜中了", "却猜不中"],
        },
    }, {
        "strategy_snapshot": {"search": {
            "prefer_ugc_sources": True,
            "variant_query_directives": directives,
        }},
    })

    artifact = result["artifact"]
    queries = artifact["llm"]["queries"]
    assert artifact["applied_directives"] == directives[:2]
    assert all(
        any(directive in item["query"] for item in queries)
        for directive in artifact["applied_directives"]
    )
    assert all(directives[2] not in item["query"] for item in queries)


@pytest.mark.asyncio
async def test_n07_claimed_long_directive_is_not_truncated_in_query():
    directive = "优先搜索论坛帖子和微博评论区中由真实网友发布的完整槽位替换文本，并排除百科释义、营销聚合页与原句转载"
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N07").execute({
        "N05": {
            "original_text": "我猜中了开头，却猜不中这结局",
            "fixed_anchors": ["我猜中了", "却猜不中"],
        },
    }, {
        "strategy_snapshot": {"search": {
            "variant_query_directives": [directive],
        }},
    })

    artifact = result["artifact"]
    assert artifact["applied_directives"] == [directive]
    assert any(directive in item["query"] for item in artifact["llm"]["queries"])


@pytest.mark.asyncio
async def test_n05_normalizes_template_string_fixed_anchors_into_literal_segments():
    original = "你说的对，但是《原神》是由米哈游自主研发的一款开放世界冒险游戏。"
    source = {
        "source_id": "O001", "url": "https://example.com/original", "title": "原神介绍体",
        "text": original,
    }
    llm = FakeLLMProvider(responses=[{
        "title": "原神介绍体", "original_text": original,
        "fixed_anchors": "你说的对，但是[游戏名]是由[开发商]自主研发的一款[描述]。",
        "source_id": "O001", "source_url": source["url"], "evidence_quote": original,
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N05").execute({"N04": {"sources": [source]}}, None)
    anchors = result["artifact"]["llm"]["fixed_anchors"]
    assert anchors == ["你说的对，但是", "是由", "自主研发的一款", "。"]


@pytest.mark.asyncio
async def test_n05_auto_mode_falls_back_to_real_search_phrase_not_llm_invention():
    source = {
        "source_id": "O001", "url": "https://example.com/song",
        "title": "我很丑，可是我很温柔（1988年赵传演唱的歌曲）",
        "text": "《我很丑，可是我很温柔》是赵传演唱的歌曲。",
    }
    invented = {
        "title": "我穷我丑但我温柔", "original_text": "我穷，我丑，但我很温柔",
        "fixed_anchors": ["我穷", "我丑", "但我很温柔"],
        "source_id": "O001", "source_url": source["url"],
        "evidence_quote": "我穷，我丑，但我很温柔",
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[invented]), search=FakeSearchProvider(),
    )
    result = await registry.get("N05").execute({
        "START": {"mode": "AUTO_DISCOVERY"},
        "N02": {"known_example_phrases": ["我穷，我丑，但我很温柔"]},
        "N04": {"sources": [source]},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["original_text"] == "我很丑，可是我很温柔"
    assert payload["evidence_quote"] == "我很丑，可是我很温柔"


@pytest.mark.asyncio
async def test_n10_extracts_known_introduction_template_without_llm_timeout_risk():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    original = "你说的对，但是《原神》是由米哈游自主研发的一款开放世界冒险游戏。"
    variants = [
        {"variant_text": "你说得对，但是《星际战甲》是由DE自主研发的一款科幻冒险游戏。"},
        {"variant_text": "你说的对，但是《烟神》是由丁真自主研发的一款开放世界冒险游戏。"},
        {"variant_text": "你说的对，但是《命运二》是由棒鸡自主研发的一款射击游戏。"},
    ]
    result = await registry.get("N10").execute({
        "N05": {"original_text": original}, "N09": {"variants": variants},
    }, None)
    assert result["artifact"]["llm"]["canonical_template_text"] == (
        "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"
    )
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n10_extracts_all_want_template_without_llm_timeout_risk():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    variants = [
        {"variant_text": "小孩子才做选择，大人全都要"},
        {"variant_text": "小孩子才做选择，我都要"},
        {"variant_text": "小孩子才做选择题，成年人当然是全都要"},
    ]
    result = await registry.get("N10").execute({
        "N05": {"original_text": "小孩才做选择，我全都要"},
        "N09": {"variants": variants},
    }, None)
    assert result["artifact"]["llm"]["canonical_template_text"] == (
        "{年幼者}才做选择，{主体}{全都要表达}"
    )
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n10_supports_optional_prefix_catchphrase_template():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    variants = [
        {"variant_text": "这破地铁我真的会谢"},
        {"variant_text": "加班到凌晨，我真的会谢！"},
        {"variant_text": "遇到鸽子精朋友，我真的会谢"},
    ]
    result = await registry.get("N10").execute({
        "N05": {"original_text": "我真的会谢"}, "N09": {"variants": variants},
    }, None)
    assert result["artifact"]["llm"]["canonical_template_text"] == (
        "{触发情境（可选）}我真的会谢"
    )
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n10_builds_generic_optional_context_template_for_fixed_catchphrase():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N10").execute({
        "N05": {"original_text": "家人们谁懂啊"},
        "N09": {"variants": [
            {"variant_text": "家人们谁懂啊，今天又加班"},
            {"variant_text": "一觉醒来又迟到，家人们谁懂啊"},
            {"variant_text": "家人们谁懂啊，这也太离谱了"},
        ]},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["canonical_template_text"] == (
        "{前置情境（可选）}家人们谁懂啊{后续内容（可选）}"
    )
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n10_builds_fact_avoidance_template_from_real_rewrites():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N10").execute({
        "N05": {"original_text": "抛开事实不谈，男生就一点错都没有吗"},
        "N09": {"variants": [
            {"variant_text": "抛开事实不谈，整个银河系会动的都有责任"},
            {"variant_text": "只是拿了个耳机，抛开事实不谈，这并不是什么大事对不对"},
            {"variant_text": "抛开事实不谈的话，对方就没一点错误吗"},
        ]},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["canonical_template_text"] == (
        "{前置情境（可选）}抛开事实不谈{连接表达（可选）}，{归责或辩解内容}"
    )
    assert payload["fixed_segments"] == ["抛开事实不谈", "，"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n10_extracts_repeated_behavior_template_instead_of_locking_original_action():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N10").execute({
        "N05": {"original_text": "熬夜一时爽，一直熬夜「一直爽」"},
        "N09": {"variants": [
            {"variant_text": "撸猫一时爽，一直撸猫一直爽"},
            {"variant_text": "玩游戏一时爽，一直玩游戏一直爽"},
            {"variant_text": "手冲一时爽，一直手冲一直爽"},
        ]},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["canonical_template_text"] == (
        "{行为}一时爽，一直{行为}{持续爽表达}"
    )
    assert payload["fixed_segments"] == ["一时爽，一直", "一直爽"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n115_repeated_behavior_blueprint_uses_nominalized_agu_event():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N11.5").execute({
        "N10": {
            "canonical_template_text": "{行为}一时爽，一直{行为}{持续爽表达}",
            "fixed_segments": ["一时爽，一直", "一直爽"],
            "slots": [
                {"name": "行为"}, {"name": "持续爽表达"},
            ],
        },
        "N11": {"decision": "PASS"},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["integration_mode"] == "REPEATED_ACTION_EVENT"
    assert payload["allows_nominalized_event"] is True
    assert payload["must_preserve"] == ["一时爽，一直", "一直爽"]
    assert "凿agu一时爽，一直凿agu一直爽" in payload["rewrite_blueprint"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n10_prefers_supported_slot_prefix_over_locking_entire_original():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N10").execute({
        "N05": {"original_text": "世界是一个巨大的草台班子"},
        "N09": {"variants": [
            {"variant_text": "世界是一个巨大的娟子"},
            {"variant_text": "世界是一个巨大的临时班子"},
            {"variant_text": "原来世界是一个巨大的草台班子"},
        ]},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["canonical_template_text"] == (
        "{前置情境（可选）}世界是一个巨大的{变化内容}"
    )
    assert payload["fixed_segments"] == ["世界是一个巨大的"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n115_slot_prefix_blueprint_requires_filling_template_and_acting_on_agu():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N11.5").execute({
        "N10": {
            "canonical_template_text": "{前置情境（可选）}世界是一个巨大的{变化内容}",
            "fixed_segments": ["世界是一个巨大的"],
            "slots": [
                {"name": "前置情境（可选）"}, {"name": "变化内容"},
            ],
        },
        "N11": {"decision": "PASS"},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["must_preserve"] == ["世界是一个巨大的"]
    assert "变化内容" in payload["rewrite_blueprint"]
    assert "凿agu" in payload["rewrite_blueprint"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n115_builds_known_adaptation_blueprint_without_llm_json_failure():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    template = "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"
    result = await registry.get("N11.5").execute({
        "N10": {"canonical_template_text": template},
        "N11": {"decision": "PASS"},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["route"] == "STRUCTURE_PRESERVING_REWRITE"
    assert payload["must_preserve"] == ["你说的对，但是", "是由", "自主研发的一款"]
    assert "agu" in payload["rewrite_blueprint"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n115_product_blueprint_allows_nominalized_event_and_natural_role_mapping():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    template = "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"
    result = await registry.get("N11.5").execute({
        "N10": {"canonical_template_text": template},
        "N11": {"decision": "PASS"},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["integration_mode"] == "VARIANT_GUIDED_SLOT_FILL"
    assert payload["allows_nominalized_event"] is True
    assert payload["minimum_replacement_count"] == 1
    assert payload["optional_context"]["actors"] == [
        "同济大学的人", "高程群群友", "群友", "他", "他们",
    ]
    assert "研发方" in payload["natural_role_mappings"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n12_receives_verified_variants_and_structured_adaptation_context():
    old_style_texts = [
        "你说的对，但是凿具是由老王自主研发的一款趁手工具，他正在凿agu。",
        "你说的对，但是凿法是由老李自主研发的一款独门手艺，他已经凿了agu。",
        "你说的对，但是铁凿是由师傅自主研发的一款坚固工具，大家正在凿agu。",
        "你说的对，但是凿术是由工匠自主研发的一款实用技术，我正在凿agu。",
        "你说的对，但是石凿是由阿强自主研发的一款专业器具，他们正在凿agu。",
    ]
    llm = FakeLLMProvider(responses=[{
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": text}
            for i, text in enumerate(old_style_texts, 1)
        ],
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    variants = [
        {"variant_text": "变式一", "source_url": "https://example.com/1"},
        {"variant_text": "变式二", "source_url": "https://example.com/2"},
        {"variant_text": "变式三", "source_url": "https://example.com/3"},
        {"variant_text": "变式四", "source_url": "https://example.com/4"},
        {"variant_text": "变式五", "source_url": "https://example.com/5"},
        {"variant_text": "不应注入的第六条", "source_url": "https://example.com/6"},
    ]
    await registry.get("N12").execute({
        "N05": {"original_text": "普通原梗"},
        "N09": {"variants": variants},
        "N10": {"canonical_template_text": "普通{模板}"},
        "N11.5": {
            "route": "STRUCTURE_PRESERVING_REWRITE",
            "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
        },
    }, None)
    request_payload = llm.requests[0].user_payload
    assert [item["variant_text"] for item in request_payload["artifacts"]["N09"]["variants"]] == [
        "变式一", "变式二", "变式三", "变式四", "变式五",
    ]
    assert request_payload["adaptation_context"]["agu_role"] == "凿这一动作的承受者"
    assert request_payload["adaptation_context"]["variant_usage"] == "仅参考槽位替换方式、篇幅和改编克制度"
    assert request_payload["candidate_requirements"]["minimum_replacement_count"] == 1


@pytest.mark.asyncio
async def test_n12_accepts_nominalized_event_title_and_product_minimal_replacement():
    original = "你说的对，但是《原神》是由米哈游自主研发的一款全新开放世界冒险游戏。"
    minimal = "你说的对，但是《凿agu》是由米哈游自主研发的一款全新开放世界冒险游戏。"
    texts = [
        minimal,
        "你说的对，但是《他凿agu》是由米哈游自主研发的一款全新开放世界冒险游戏。",
        "你说的对，但是《凿agu》是由高程群群友自主研发的一款全新开放世界冒险游戏。",
        "你说的对，但是《他们凿agu》是由同济大学自主研发的一款全新多人冒险游戏。",
        "你说的对，但是《凿高程群的agu》是由群友自主研发的一款全新开放世界冒险游戏。",
    ]
    llm = FakeLLMProvider(responses=[{
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {"candidate_id": f"C{i}", "text": text}
            for i, text in enumerate(texts, 1)
        ],
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N12").execute({
        "N05": {"original_text": original},
        "N10": {"canonical_template_text": "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"},
        "N11.5": {
            "route": "STRUCTURE_PRESERVING_REWRITE",
            "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
            "integration_mode": "VARIANT_GUIDED_SLOT_FILL",
        },
    }, None)
    candidates = result["artifact"]["llm"]["candidates"]
    assert candidates[0]["text"] == minimal
    assert candidates[0]["generation_approach"] == "MINIMAL_REPLACEMENT"


@pytest.mark.asyncio
async def test_n12_product_candidates_require_at_least_one_minimal_replacement():
    original = "你说的对，但是《原神》是由米哈游自主研发的一款全新开放世界冒险游戏。"
    invalid = {
        "route_used": "STRUCTURE_PRESERVING_REWRITE",
        "candidates": [
            {
                "candidate_id": f"C{i}",
                "text": f"你说的对，但是《他们凿agu{i}次》是由高程群群友自主研发的一款全新多人冒险游戏。",
            }
            for i in range(1, 6)
        ],
    }
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[invalid, invalid, invalid]),
        search=FakeSearchProvider(),
    )
    with pytest.raises(ValueError, match="minimal replacement"):
        await registry.get("N12").execute({
            "N05": {"original_text": original},
            "N10": {"canonical_template_text": "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"},
            "N11.5": {
                "route": "STRUCTURE_PRESERVING_REWRITE",
                "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
                "integration_mode": "VARIANT_GUIDED_SLOT_FILL",
            },
        }, None)


@pytest.mark.asyncio
async def test_n13_receives_restraint_weighted_evaluation_priorities():
    llm = FakeLLMProvider(responses=[{
        "scores": [], "qualified_candidate_ids": [],
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    await registry.get("N13").execute({
        "N05": {"original_text": "原始梗"},
        "N10": {"canonical_template_text": "模板"},
        "N12": {"candidates": []},
    }, None)
    priorities = llm.requests[0].user_payload["evaluation_priorities"]
    assert priorities["adaptation_restraint_weight"] > priorities["all_slots_semantic_relation_weight"]
    assert priorities["minimum_replacement_effect_weight"] > 0
    assert priorities["do_not_reward_explaining_every_slot"] is True


@pytest.mark.asyncio
async def test_n13_injects_and_audits_evaluation_strategy_directives():
    llm = FakeLLMProvider(responses=[{
        "scores": [{
            "candidate_id": "C1",
            "fluency": 6,
            "recognition": 8,
            "agu_fit": 9,
            "qualified": True,
        }],
        "qualified_candidate_ids": ["C1"],
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N13").execute({
        "N05": {"original_text": "原始梗"},
        "N10": {"canonical_template_text": "模板"},
        "N12": {"candidates": [{
            "candidate_id": "C1", "text": "他正在凿agu",
        }]},
    }, {
        "strategy_snapshot": {"evaluation": {
            "directives": ["优先检查指示结构", "优先检查指示结构", "核对动作受事"],
            "minimum_fluency": 7,
            "minimum_recognition": 8,
            "minimum_agu_fit": 9,
        }},
    })

    priorities = llm.requests[0].user_payload["evaluation_priorities"]
    assert priorities["directives"] == ["优先检查指示结构", "核对动作受事"]
    assert priorities["minimum_thresholds"] == {
        "fluency": 7, "recognition": 8, "agu_fit": 9,
    }
    assert priorities["score_scale"] == {
        "minimum": 0, "maximum": 10, "default_minimum": 6,
    }
    assert result["artifact"]["applied_evaluation_directives"] == [
        "优先检查指示结构", "核对动作受事",
    ]
    assert result["outcome"] == "ALL_UNQUALIFIED"


@pytest.mark.asyncio
async def test_n13_awkward_candidate_cannot_pass_fluency_threshold():
    candidate_texts = {
        "C1": "我猜中了开头，却猜不中这凿agu",
        "C2": "我猜中了开头，却猜不中那凿agu",
        "C3": "我猜中了开头，却猜不中此凿agu",
        "C4": "我猜中了开头，却猜不中这凿agu的结果",
        "C5": "他先凿了小王，又凿agu",
    }
    high_score = {
        "fluency": 10,
        "recognition": 10,
        "agu_fit": 10,
        "humor": 10,
        "rhythm": 10,
        "adaptation_restraint": 10,
        "minimal_replacement_effect": 10,
        "qualified": True,
        "reason": "模型认为表达自然",
    }
    llm = FakeLLMProvider(responses=[{
        "scores": [
            {**high_score, "candidate_id": candidate_id}
            for candidate_id in candidate_texts
        ],
        "qualified_candidate_ids": list(candidate_texts),
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N13").execute({
        "N05": {"original_text": "我猜中了开头，却猜不中这结局"},
        "N10": {"canonical_template_text": "我猜中了{开头内容}，却猜不中这{结局内容}"},
        "N12": {"candidates": [
            {"candidate_id": candidate_id, "text": text}
            for candidate_id, text in candidate_texts.items()
        ]},
    }, {
        "strategy_snapshot": {
            "generation": {"reject_awkward_demonstrative_phrase": True},
            "evaluation": {
                "minimum_fluency": 6,
                "minimum_recognition": 6,
                "minimum_agu_fit": 6,
            },
        },
    })

    payload = result["artifact"]["llm"]
    scores = {score["candidate_id"]: score for score in payload["scores"]}
    assert result["outcome"] == "HAS_QUALIFIED"
    assert payload["qualified_candidate_ids"] == ["C4"]
    for candidate_id in ("C1", "C2", "C3"):
        assert scores[candidate_id]["fluency"] < 6
        assert scores[candidate_id]["qualified"] is False
        assert "指示结构不通顺" in "".join(scores[candidate_id]["problems"])
    assert scores["C4"]["fluency"] == 10
    assert scores["C4"]["qualified"] is True
    assert not scores["C4"]["problems"]
    assert scores["C5"]["agu_fit"] < 6
    assert scores["C5"]["qualified"] is False
    assert "动作受事" in "".join(scores["C5"]["problems"])


@pytest.mark.asyncio
async def test_n13_default_thresholds_route_all_unqualified_back_to_n12():
    llm = FakeLLMProvider(responses=[{
        "scores": [{
            "candidate_id": "C1",
            "fluency": 5,
            "recognition": 10,
            "agu_fit": 10,
            "qualified": True,
        }],
        "qualified_candidate_ids": ["C1"],
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N13").execute({
        "N12": {"candidates": [{
            "candidate_id": "C1", "text": "他正在凿agu",
        }]},
    }, None)

    assert result["outcome"] == "ALL_UNQUALIFIED"
    assert result["artifact"]["llm"]["qualified_candidate_ids"] == []
    assert TransitionTable().next("N13", "ALL_UNQUALIFIED", has_budget=True) == "N12"


@pytest.mark.asyncio
async def test_n13_rejects_other_action_objects_after_arbitrary_context_prefixes():
    candidate_texts = {
        "C1": "他拿锤子凿小王，又凿agu",
        "C2": "群友昨晚在宿舍凿小李，随后凿agu",
        "C3": "为了测试工具先凿木板，再凿agu",
        "C4": "他们凿agu",
        "C5": "拿锤子凿agu",
        "C6": "agu被他们凿了",
        "C7": "凿agu的结果很明显",
    }
    high_score = {
        "fluency": 10,
        "recognition": 10,
        "agu_fit": 10,
        "qualified": True,
    }
    llm = FakeLLMProvider(responses=[{
        "scores": [
            {**high_score, "candidate_id": candidate_id}
            for candidate_id in candidate_texts
        ],
        "qualified_candidate_ids": list(candidate_texts),
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N13").execute({
        "N12": {"candidates": [
            {"candidate_id": candidate_id, "text": text}
            for candidate_id, text in candidate_texts.items()
        ]},
    }, None)

    payload = result["artifact"]["llm"]
    scores = {score["candidate_id"]: score for score in payload["scores"]}
    assert result["outcome"] == "HAS_QUALIFIED"
    assert payload["qualified_candidate_ids"] == ["C4", "C5", "C6", "C7"]
    for candidate_id in ("C1", "C2", "C3"):
        assert scores[candidate_id]["agu_fit"] < 6
        assert scores[candidate_id]["qualified"] is False
        assert "其他动作受事" in "".join(scores[candidate_id]["problems"])
    for candidate_id in ("C4", "C5", "C6", "C7"):
        assert scores[candidate_id]["agu_fit"] == 10
        assert scores[candidate_id]["qualified"] is True
        assert not scores[candidate_id]["problems"]


@pytest.mark.asyncio
async def test_n13_rejects_coordinated_other_recipient_without_blocking_new_predicate():
    candidate_texts = {
        "C1": "他凿agu和小王",
        "C2": "凿agu、小王",
        "C3": "他凿agu和他聊天",
        "C4": "他凿agu，然后回家",
        "C5": "agu被他们凿了",
        "C6": "凿agu的结果很明显",
        "C7": "他凿agu和朋友聊天",
        "C8": "他凿agu，回家",
        "C9": "他凿agu和朋友",
        "C10": "他凿agu和小王聊天",
        "C11": "他凿agu和小王，然后回家",
        "C12": "他凿agu、小王，随后回家",
    }
    high_score = {
        "fluency": 10,
        "recognition": 10,
        "agu_fit": 10,
        "qualified": True,
    }
    llm = FakeLLMProvider(responses=[{
        "scores": [
            {**high_score, "candidate_id": candidate_id}
            for candidate_id in candidate_texts
        ],
        "qualified_candidate_ids": list(candidate_texts),
    }])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N13").execute({
        "N12": {"candidates": [
            {"candidate_id": candidate_id, "text": text}
            for candidate_id, text in candidate_texts.items()
        ]},
    }, None)

    payload = result["artifact"]["llm"]
    scores = {score["candidate_id"]: score for score in payload["scores"]}
    assert result["outcome"] == "HAS_QUALIFIED"
    assert payload["qualified_candidate_ids"] == [
        "C3", "C4", "C5", "C6", "C7", "C8", "C10",
    ]
    for candidate_id in ("C1", "C2", "C9", "C11", "C12"):
        assert scores[candidate_id]["agu_fit"] < 6
        assert scores[candidate_id]["qualified"] is False
        assert "其他动作受事" in "".join(scores[candidate_id]["problems"])
    for candidate_id in ("C3", "C4", "C5", "C6", "C7", "C8", "C10"):
        assert scores[candidate_id]["agu_fit"] == 10
        assert scores[candidate_id]["qualified"] is True
        assert not scores[candidate_id]["problems"]


@pytest.mark.asyncio
async def test_n115_builds_fixed_catchphrase_blueprint_without_llm_json_failure():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    result = await registry.get("N11.5").execute({
        "N10": {
            "canonical_template_text": "{前置情境（可选）}家人们谁懂啊{后续内容（可选）}",
            "fixed_segments": ["家人们谁懂啊"],
        },
        "N11": {"decision": "PASS"},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["route"] == "STRUCTURE_PRESERVING_REWRITE"
    assert payload["must_preserve"] == ["家人们谁懂啊"]
    assert "凿agu" in payload["rewrite_blueprint"]
    assert "动作受事" in payload["rewrite_blueprint"]
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n11_revalidates_template_coverage_without_llm_json_failure():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    template = "大胆{被呵斥对象}，我一眼就看出你不是{表面身份}"
    result = await registry.get("N11").execute({
        "N05": {"original_text": "大胆妖孽，我一眼就看出你不是人"},
        "N09": {"variants": [
            {"variant_text": "大胆猫猫，我一眼就看出你不是人"},
            {"variant_text": "大胆程序员，我一眼就看出你不是产品经理"},
            {"variant_text": "大胆机器人，我一眼就看出你不是人类"},
        ]},
        "N10": {
            "canonical_template_text": template,
            "fixed_segments": ["大胆", "，我一眼就看出你不是"],
            "slots": [
                {"name": "被呵斥对象"},
                {"name": "表面身份"},
            ],
            "evidence_variant_texts": [
                "大胆猫猫，我一眼就看出你不是人",
                "大胆程序员，我一眼就看出你不是产品经理",
                "大胆机器人，我一眼就看出你不是人类",
            ],
        },
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["decision"] == "PASS"
    assert payload["matched_variant_count"] == 3
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n11_coverage_threshold_rejects_five_of_twenty_variants():
    matching = [
        {"variant_text": f"我猜中了第{i}幕，却猜不中这结局"}
        for i in range(1, 6)
    ]
    nonmatching = [
        {"variant_text": f"我猜中了第{i}幕，却猜不中这收尾"}
        for i in range(6, 21)
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N11").execute({
        "N05": {"original_text": "我猜中了开头，却猜不中这结局"},
        "N09": {"variants": matching + nonmatching},
        "N10": {
            "canonical_template_text": "我猜中了{开头内容}，却猜不中这结局",
            "fixed_segments": ["我猜中了", "，却猜不中这结局"],
            "slots": [{"name": "开头内容"}],
            "evidence_variant_texts": [
                variant["variant_text"] for variant in matching
            ],
        },
    }, {
        "strategy_snapshot": {
            "search": {"minimum_template_coverage": 0.6},
        },
    })

    payload = result["artifact"]["llm"]
    assert result["outcome"] == "MORE_EVIDENCE"
    assert payload["decision"] == "MORE_EVIDENCE"
    assert payload["original_reconstructable"] is True
    assert payload["matched_variant_count"] == 5
    assert payload["total_variant_count"] == 20
    assert payload["coverage"] == pytest.approx(5 / 20)
    assert payload["accuracy"] < 5
    assert payload["problems"]


@pytest.mark.asyncio
async def test_n11_coverage_threshold_rejects_two_of_four_variants_at_half():
    matching = [
        {"variant_text": "我猜中了起点，却猜不中这结局"},
        {"variant_text": "我猜中了过程，却猜不中这结局"},
    ]
    nonmatching = [
        {"variant_text": "我猜中了起点，却猜不中这收尾"},
        {"variant_text": "我猜中了过程，却猜不中这收尾"},
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N11").execute({
        "N05": {"original_text": "我猜中了开头，却猜不中这结局"},
        "N09": {"variants": matching + nonmatching},
        "N10": {
            "canonical_template_text": "我猜中了{开头内容}，却猜不中这结局",
            "fixed_segments": ["我猜中了", "，却猜不中这结局"],
            "slots": [{"name": "开头内容"}],
            "evidence_variant_texts": [
                "我猜中了起点，却猜不中这结局",
                "我猜中了过程，却猜不中这结局",
            ],
        },
    }, None)

    payload = result["artifact"]["llm"]
    assert result["outcome"] == "MORE_EVIDENCE"
    assert payload["matched_variant_count"] == 2
    assert payload["total_variant_count"] == 4
    assert payload["coverage"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_n11_reextracts_when_one_declared_slot_has_no_replacement_evidence():
    variants = [
        {"variant_text": "大胆猫猫，我一眼就看出你不是人"},
        {"variant_text": "大胆程序员，我一眼就看出你不是人"},
        {"variant_text": "大胆机器人，我一眼就看出你不是人"},
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N11").execute({
        "N05": {"original_text": "大胆妖孽，我一眼就看出你不是人"},
        "N09": {"variants": variants},
        "N10": {
            "canonical_template_text": "大胆{被呵斥对象}，我一眼就看出你不是{表面身份}",
            "fixed_segments": ["大胆", "，我一眼就看出你不是"],
            "slots": [{"name": "被呵斥对象"}, {"name": "表面身份"}],
            "evidence_variant_texts": [
                variant["variant_text"] for variant in variants
            ],
        },
    }, None)

    payload = result["artifact"]["llm"]
    assert result["outcome"] == "REEXTRACT"
    assert payload["decision"] == "REEXTRACT"
    assert any("表面身份" in problem and "缺少替换证据" in problem
               for problem in payload["problems"])


@pytest.mark.asyncio
async def test_n11_reextracts_template_with_only_four_fixed_chars_and_catch_all_slot():
    variants = [
        {"variant_text": "我猜中了天气预报"},
        {"variant_text": "我猜中了产品需求"},
        {"variant_text": "我猜中了考试答案"},
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N11").execute({
        "N05": {"original_text": "我猜中了开头，却猜不中这结局"},
        "N09": {"variants": variants},
        "N10": {
            "canonical_template_text": "我猜中了{任意内容}",
            "fixed_segments": ["我猜中了"],
            "slots": [{"name": "任意内容"}],
            "evidence_variant_texts": [
                variant["variant_text"] for variant in variants
            ],
        },
    }, None)

    payload = result["artifact"]["llm"]
    assert result["outcome"] == "REEXTRACT"
    assert payload["decision"] == "REEXTRACT"
    assert any("固定结构过宽" in problem for problem in payload["problems"])


@pytest.mark.asyncio
async def test_n11_reextracts_unsupported_fixed_and_fabricated_variant_evidence():
    variants = [
        {"variant_text": "我猜中了起点，却猜不中这结局"},
        {"variant_text": "我猜中了过程，却猜不中这结局"},
        {"variant_text": "我猜中了终点，却猜不中这结局"},
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(), search=FakeSearchProvider(),
    )

    result = await registry.get("N11").execute({
        "N05": {"original_text": "我猜中了开头，却猜不中这结局"},
        "N09": {"variants": variants},
        "N10": {
            "canonical_template_text": "我猜中了{开头内容}，却猜不中这结局",
            "fixed_segments": ["万能前缀"],
            "slots": [{"name": "开头内容"}],
            "evidence_variant_texts": ["我猜中了虚构证据，却猜不中这结局"],
        },
    }, None)

    payload = result["artifact"]["llm"]
    assert result["outcome"] == "REEXTRACT"
    assert any("fixed_segments" in problem for problem in payload["problems"])
    assert any("evidence_variant_texts" in problem for problem in payload["problems"])


@pytest.mark.asyncio
async def test_n15_packages_exact_selected_candidate_without_another_llm_call():
    llm = FakeLLMProvider()
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    selected_text = "你说的对，但是铁凿是由老王自主研发的一款趁手工具，他正在凿agu。"
    result = await registry.get("N15").execute({
        "N05": {"title": "原神介绍体", "original_text": "原始梗", "source_url": "https://example.com"},
        "N10": {"canonical_template_text": "模板"},
        "N12": {"llm": {"candidates": [{"candidate_id": "C3", "text": selected_text}]}},
        "N14": {"llm": {"selected_candidate_id": "C3"}},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["final_agu_text"] == selected_text
    assert payload["original"] == "原始梗"
    assert payload["template"] == "模板"
    assert payload["content_safety"]["status"] == "PASS"
    assert payload["content_safety"]["method"] == "DETERMINISTIC_RULESET"
    assert payload["content_safety"]["policy_version"] == "content-safety-v1"
    assert payload["content_safety"]["checked_fields"] == ["title", "final_agu_text"]
    assert all(check["passed"] for check in payload["content_safety"]["checks"])
    assert llm.requests == []


@pytest.mark.asyncio
async def test_n09_sends_only_anchor_relevant_excerpts_instead_of_full_search_pages():
    variants = [
        "你说的对，但是《星际战甲》是由DE自主研发的一款科幻冒险游戏。",
        "你说的对，但是《烟神》是由丁真自主研发的一款开放世界冒险游戏。",
        "你说的对，但是《命运二》是由棒鸡自主研发的一款射击游戏。",
    ]
    sources = [
        {
            "source_id": f"V{i}", "url": f"https://example.com/{i}", "title": f"来源{i}",
            "text": "无关网页导航" * 1200 + "。" + variant,
        }
        for i, variant in enumerate(variants, 1)
    ]
    llm = FakeLLMProvider(responses=[{"variants": [
        {
            "variant_text": variant, "source_id": f"V{i}",
            "source_url": f"https://example.com/{i}", "evidence_quote": variant,
            "shared_anchor": "你说的对，但是",
        }
        for i, variant in enumerate(variants, 1)
    ]}])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())
    await registry.get("N09").execute({
        "N05": {
            "original_text": "你说的对，但是《原神》是由米哈游自主研发的一款开放世界冒险游戏。",
            "fixed_anchors": ["你说的对，但是", "是由", "自主研发的一款"],
        },
        "N08": {"sources": sources},
    }, None)
    sent_sources = llm.requests[0].user_payload["artifacts"]["N08"]["sources"]
    assert all(variant in source["text"] for variant, source in zip(variants, sent_sources, strict=True))
    assert sum(len(source["text"]) for source in sent_sources) < 5000


@pytest.mark.asyncio
async def test_n09_falls_back_to_verified_anchor_extraction_after_model_json_failure():
    variants = [
        "你说的对，但是《星际战甲》是由DE自主研发的一款科幻冒险游戏。",
        "你说的对，但是《烟神》是由丁真自主研发的一款开放世界冒险游戏。",
        "你说得对，但是《命运二》是由棒鸡自主研发的一款射击游戏。",
    ]
    sources = [
        {"source_id": f"V{i}", "url": f"https://example.com/{i}", "title": f"来源{i}", "text": variant}
        for i, variant in enumerate(variants, 1)
    ]
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())
    result = await registry.get("N09").execute({
        "N05": {
            "original_text": "你说的对，但是《原神》是由米哈游自主研发的一款开放世界冒险游戏。",
            "fixed_anchors": ["你说的对，但是", "是由", "自主研发的一款"],
        },
        "N08": {"sources": sources},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["is_sufficient"] is True
    assert len(payload["variants"]) == 3
    assert result["artifact"]["extraction_mode"] == "DETERMINISTIC_AFTER_LLM_FAILURE"


@pytest.mark.asyncio
async def test_n09_strict_fallback_returns_insufficient_for_reprints_and_explanations():
    original = "我猜中了开头，却猜不中这结局"
    sources = [
        {"source_id": "V1", "url": "https://a.example/1", "title": "原句转载", "text": original},
        {"source_id": "V2", "url": "https://b.example/2", "title": "繁体转载", "text": "我猜中了開頭，卻猜不中這結局"},
        {"source_id": "V3", "url": "https://c.example/3", "title": "释义", "text": original + "是什么意思"},
    ]
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())

    result = await registry.get("N09").execute({
        "N05": {"original_text": original, "fixed_anchors": ["我猜中了", "却猜不中"]},
        "N08": {"sources": sources},
    }, None)

    assert result["outcome"] == "INSUFFICIENT"
    assert result["artifact"]["llm"]["variants"] == []
    assert result["artifact"]["llm"]["is_sufficient"] is False
    assert result["artifact"]["extraction_mode"] == "DETERMINISTIC_AFTER_LLM_FAILURE"


@pytest.mark.asyncio
async def test_n09_mixed_traditional_reprints_cannot_reach_sufficient():
    original = "这个网络热门话题总是让人意想不到"
    reprints = [
        "這個網絡熱門話題總是讓人意想不到",
        "這個網絡热門話題總是讓人意想不到",
        "這個網絡熱門话題總是讓人意想不到",
    ]
    sources = [
        {
            "source_id": f"V{i}",
            "url": f"https://forum.example/{i}",
            "title": f"转载{i}",
            "text": reprint,
        }
        for i, reprint in enumerate(reprints, 1)
    ]
    registry = build_real_registry(llm=FakeLLMProvider(responses=[{
        "variants": [
            {
                "variant_text": reprint,
                "source_id": f"V{i}",
                "source_url": f"https://forum.example/{i}",
                "evidence_quote": reprint,
                "shared_anchor": "网络热门话题",
            }
            for i, reprint in enumerate(reprints, 1)
        ],
    }]), search=FakeSearchProvider())

    result = await registry.get("N09").execute({
        "N05": {
            "original_text": original,
            "fixed_anchors": ["网络热门话题", "让人意想不到"],
        },
        "N08": {"sources": sources},
    }, None)

    assert result["outcome"] == "INSUFFICIENT"
    assert result["artifact"]["llm"]["variants"] == []


@pytest.mark.asyncio
async def test_n09_uses_canonical_script_identity_for_variant_deduplication():
    original = "设计一个自动触发弹窗"
    variants = [
        "设计一个手动触发agu弹窗",
        "设计一个手动觸发agu弹窗",
        "设计一个手动触发agu彈窗",
    ]
    sources = [
        {
            "source_id": f"V{i}",
            "url": f"https://forum.example/{i}",
            "title": f"网友改编{i}",
            "text": variant,
        }
        for i, variant in enumerate(variants, 1)
    ]
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{"variants": [
            {
                "variant_text": variant,
                "source_id": f"V{i}",
                "source_url": f"https://forum.example/{i}",
                "evidence_quote": variant,
                "shared_anchor": "设计一个",
            }
            for i, variant in enumerate(variants, 1)
        ]}]),
        search=FakeSearchProvider(),
    )

    result = await registry.get("N09").execute({
        "N05": {
            "original_text": original,
            "fixed_anchors": ["设计一个", "弹窗"],
        },
        "N08": {"sources": sources},
    }, None)

    assert result["outcome"] == "INSUFFICIENT"
    assert result["artifact"]["llm"]["is_sufficient"] is False


@pytest.mark.asyncio
async def test_n09_rejects_title_body_split_evidence():
    original = "我猜中了开头，却猜不中这结局"
    variants = [
        "我猜中了开头，却猜不中agu被谁凿了",
        "我猜中了开头，却猜不中是谁先动的手",
        "我猜中了开头，却猜不中群友最后凿了谁",
    ]
    sources = [
        {
            "source_id": f"V{i}",
            "url": f"https://forum.example/{i}",
            "title": variant,
            "text": f"正文只写了无关摘要{i}",
        }
        for i, variant in enumerate(variants, 1)
    ]
    registry = build_real_registry(llm=FakeLLMProvider(responses=[{
        "variants": [
            {
                "variant_text": variant,
                "source_id": f"V{i}",
                "source_url": f"https://forum.example/{i}",
                "evidence_quote": f"正文只写了无关摘要{i}",
                "shared_anchor": "我猜中了",
            }
            for i, variant in enumerate(variants, 1)
        ],
    }]), search=FakeSearchProvider())

    result = await registry.get("N09").execute({
        "N05": {
            "original_text": original,
            "fixed_anchors": ["我猜中了", "却猜不中"],
        },
        "N08": {"sources": sources},
    }, None)

    assert result["outcome"] == "INSUFFICIENT"
    assert result["artifact"]["llm"]["variants"] == []


@pytest.mark.asyncio
async def test_n09_limits_structured_extraction_to_eight_sources_and_variants():
    original = "我猜中了开头，却猜不中这结局"
    variants = [
        f"我猜中了开头，却猜不中第{i}个结局"
        for i in range(1, 13)
    ]
    sources = [
        {"source_id": f"V{i}", "url": f"https://forum.example/{i}", "title": f"网友改编{i}", "text": variant}
        for i, variant in enumerate(variants, 1)
    ]
    llm = FakeLLMProvider(responses=[{"variants": [{
        "variant_text": variant,
        "source_id": f"V{i}",
        "source_url": f"https://forum.example/{i}",
        "evidence_quote": variant,
        "shared_anchor": "我猜中了",
    } for i, variant in enumerate(variants[:8], 1)]}])
    registry = build_real_registry(llm=llm, search=FakeSearchProvider())

    result = await registry.get("N09").execute({
        "N05": {"original_text": original, "fixed_anchors": ["我猜中了", "却猜不中"]},
        "N08": {"sources": sources},
    }, None)

    sent_sources = llm.requests[0].user_payload["artifacts"]["N08"]["sources"]
    assert len(sent_sources) == 8
    assert len(result["artifact"]["llm"]["variants"]) <= 8


@pytest.mark.asyncio
async def test_n09_and_n11_share_two_variant_search_retries_per_original():
    original = "我猜中了开头，却猜不中这结局"
    context = RunContext(
        mode=RunMode.MANUAL_SEED,
        admission_mode=AdmissionMode.HUMAN,
        strategy_snapshot={"search": {}},
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())
    insufficient_input = {
        "N05": {"original_text": original, "fixed_anchors": ["我猜中了", "却猜不中"]},
        "N08": {"sources": []},
    }

    first = await registry.get("N09").execute(insufficient_input, services)
    assert first["outcome"] == "INSUFFICIENT"
    assert first["artifact"]["fallback"] == {
        "count": 1,
        "threshold": 2,
        "reason": "N09_INSUFFICIENT_VARIANTS",
    }

    invalid_template_input = {
        "N05": {"original_text": original},
        "N09": {"variants": [
            {"variant_text": "我猜中了起点，却猜不中这结局"},
            {"variant_text": "我猜中了开头，却猜不中是谁先动的手"},
            {"variant_text": "我猜中了开头，却猜不中群友最后凿了谁"},
        ]},
        "N10": {
            "canonical_template_text": "我猜中了{前半句}，却猜不中这结局",
            "fixed_segments": ["我猜中了", "，却猜不中这结局"],
            "slots": [{"name": "前半句"}],
            "evidence_variant_texts": ["我猜中了起点，却猜不中这结局"],
        },
    }
    second = await registry.get("N11").execute(invalid_template_input, services)
    assert second["outcome"] == "MORE_EVIDENCE"
    assert second["artifact"]["fallback"]["count"] == 2

    exhausted = await registry.get("N09").execute(insufficient_input, services)
    assert exhausted["outcome"] == "ABANDON_ORIGINAL"
    assert exhausted["artifact"]["fallback"] == {
        "count": 2,
        "threshold": 2,
        "reason": "N09_INSUFFICIENT_VARIANTS",
    }
    assert context.loop_counters["variant_search:我猜中了开头却猜不中这结局"] == 2
    assert context.snapshot()["loop_counters"] == {
        "variant_search:我猜中了开头却猜不中这结局": 2,
    }


@pytest.mark.asyncio
async def test_exhausted_original_tracking_keeps_other_original_counter_isolated():
    exhausted = "我猜中了开头，却猜不中这结局"
    different = "大胆妖孽，我一眼就看出你不是人"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
    )
    context.__dict__["exhausted_originals"] = []
    context.strategy_snapshot.exhausted_originals = context.exhausted_originals
    context.loop_counters["variant_search:我猜中了开头却猜不中这结局"] = 2
    services = {"strategy_snapshot": context.strategy_snapshot}
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())

    exhausted_result = await registry.get("N09").execute({
        "N05": {"original_text": exhausted, "fixed_anchors": ["我猜中了", "却猜不中"]},
        "N08": {"sources": []},
    }, services)
    different_result = await registry.get("N09").execute({
        "N05": {"original_text": different, "fixed_anchors": ["大胆妖孽", "一眼就看出"]},
        "N08": {"sources": []},
    }, services)

    assert exhausted_result["outcome"] == "ABANDON_ORIGINAL"
    assert different_result["outcome"] == "INSUFFICIENT"
    assert context.exhausted_originals == ["我猜中了开头却猜不中这结局"]
    assert context.loop_counters == {
        "variant_search:我猜中了开头却猜不中这结局": 2,
        "variant_search:大胆妖孽我一眼就看出你不是人": 1,
    }
    assert context.snapshot()["exhausted_originals"] == [
        "我猜中了开头却猜不中这结局",
    ]


@pytest.mark.asyncio
async def test_variant_retry_counter_uses_one_key_for_traditional_spellings():
    simplified = "万万没想到事情竟然会变成这样"
    traditional = "萬萬沒想到事情竟然會變成這樣"
    mixed = "萬万没想到事情竟然会變成这样"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())

    first = await registry.get("N09").execute({
        "N05": {"original_text": simplified, "fixed_anchors": ["万万没想到"]},
        "N08": {"sources": []},
    }, services)
    second = await registry.get("N09").execute({
        "N05": {"original_text": traditional, "fixed_anchors": ["萬萬沒想到"]},
        "N08": {"sources": []},
    }, services)
    exhausted = await registry.get("N09").execute({
        "N05": {"original_text": mixed, "fixed_anchors": ["萬万没想到"]},
        "N08": {"sources": []},
    }, services)

    assert first["artifact"]["fallback"]["count"] == 1
    assert second["artifact"]["fallback"]["count"] == 2
    assert exhausted["outcome"] == "ABANDON_ORIGINAL"
    assert context.loop_counters == {
        "variant_search:万万没想到事情竟然会变成这样": 2,
    }
    assert context.exhausted_originals == [simplified]


@pytest.mark.asyncio
async def test_variant_retry_counter_uses_canonical_single_glyph_script_identity():
    simplified = "设计一个自动触发弹窗"
    traditional_trigger = "设计一个自动觸发弹窗"
    traditional_window = "设计一个自动触发彈窗"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())

    first = await registry.get("N09").execute({
        "N05": {"original_text": simplified, "fixed_anchors": ["设计一个"]},
        "N08": {"sources": []},
    }, services)
    second = await registry.get("N09").execute({
        "N05": {
            "original_text": traditional_trigger,
            "fixed_anchors": ["设计一个"],
        },
        "N08": {"sources": []},
    }, services)
    exhausted = await registry.get("N09").execute({
        "N05": {
            "original_text": traditional_window,
            "fixed_anchors": ["设计一个"],
        },
        "N08": {"sources": []},
    }, services)

    assert first["artifact"]["fallback"]["count"] == 1
    assert second["artifact"]["fallback"]["count"] == 2
    assert exhausted["outcome"] == "ABANDON_ORIGINAL"
    assert context.loop_counters == {
        "variant_search:设计一个自动触发弹窗": 2,
    }
    assert context.exhausted_originals == [simplified]


@pytest.mark.asyncio
async def test_variant_retry_counter_ignores_punctuation_and_whitespace():
    original = "设计一个自动触发弹窗"
    punctuated = "设计一个，自动触发弹窗"
    spaced = "设计一个 自动触发 弹窗"
    context = RunContext(
        mode=RunMode.AUTO_DISCOVERY,
        admission_mode=AdmissionMode.AUTO,
        strategy_snapshot={"search": {}},
    )
    services = {"strategy_snapshot": context.strategy_snapshot}
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())

    first = await registry.get("N09").execute({
        "N05": {"original_text": original, "fixed_anchors": ["设计一个"]},
        "N08": {"sources": []},
    }, services)
    second = await registry.get("N09").execute({
        "N05": {"original_text": punctuated, "fixed_anchors": ["设计一个"]},
        "N08": {"sources": []},
    }, services)
    exhausted = await registry.get("N09").execute({
        "N05": {"original_text": spaced, "fixed_anchors": ["设计一个"]},
        "N08": {"sources": []},
    }, services)

    assert first["artifact"]["fallback"]["count"] == 1
    assert second["artifact"]["fallback"]["count"] == 2
    assert exhausted["outcome"] == "ABANDON_ORIGINAL"
    assert context.loop_counters == {
        "variant_search:设计一个自动触发弹窗": 2,
    }
    assert context.exhausted_originals == [original]


@pytest.mark.asyncio
async def test_n09_preserves_independent_url_that_corrobates_a_duplicate_variant():
    variants = [
        "你说的对，但是《烟神》是由丁真自主研发的一款开放世界冒险游戏。",
        "你说的对，但是《命运二》是由棒鸡自主研发的一款射击游戏。",
        "你说的对，但是《你说的对》是由你说的对自主研发的一款全新你说的对。",
    ]
    sources = [
        {
            "source_id": "V1", "url": "https://example.com/collection",
            "title": "变式合集", "text": "\n".join(variants),
        },
        {
            "source_id": "V2", "url": "https://example.com/independent",
            "title": "独立发布", "text": variants[-1],
        },
    ]
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())
    result = await registry.get("N09").execute({
        "N05": {
            "original_text": "你说的对，但是《原神》是由米哈游自主研发的一款开放世界冒险游戏。",
            "fixed_anchors": ["你说的对，但是", "是由", "自主研发的一款"],
        },
        "N08": {"sources": sources},
    }, None)
    accepted = result["artifact"]["llm"]["variants"]
    assert len({item["variant_text"] for item in accepted}) == 3
    assert {item["source_url"] for item in accepted} == {
        "https://example.com/collection", "https://example.com/independent",
    }
    assert result["artifact"]["llm"]["is_sufficient"] is True


@pytest.mark.asyncio
async def test_n09_excludes_navigation_and_definition_text_from_all_want_variants():
    sources = [
        {"source_id": "V1", "url": "https://a.example", "title": "来源1", "text": "小孩才做选择，大人全都要。"},
        {"source_id": "V2", "url": "https://b.example", "title": "来源2", "text": "小孩才做选择，我都要。"},
        {"source_id": "V3", "url": "https://c.example", "title": "来源3", "text": "小孩才做选择呢，成年人什么都没有。"},
        {"source_id": "V4", "url": "https://d.example", "title": "噪声", "text": "# 下载 都要！小孩子才做选择！ Demo。"},
        {"source_id": "V5", "url": "https://e.example", "title": "定义", "text": "小孩子才做选择题，成年人当然全都要是原本网络梗的一种衍生说法。"},
    ]
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())
    result = await registry.get("N09").execute({
        "N05": {
            "original_text": "小孩才做选择，我全都要",
            "fixed_anchors": ["小孩才做选择", "我全都要"],
        },
        "N08": {"sources": sources},
    }, None)
    texts = [item["variant_text"] for item in result["artifact"]["llm"]["variants"]]
    assert len(texts) == 3
    assert all("下载" not in text and "网络梗" not in text for text in texts)


@pytest.mark.asyncio
async def test_n09_excludes_storefront_pages_from_validated_variants():
    sources = [
        {"source_id": "V1", "url": "https://a.example/post/1", "title": "网友改编1", "text": "小孩才做选择，大人全都要。"},
        {"source_id": "V2", "url": "https://b.example/post/2", "title": "网友改编2", "text": "小孩才做选择，我都要。"},
        {"source_id": "V3", "url": "https://c.example/post/3", "title": "网友改编3", "text": "小孩才做选择呢，成年人什么都没有。"},
        {"source_id": "V4", "url": "https://store.steampowered.com/app/123", "title": "游戏商店", "text": "小孩才做选择，成年人可以都要！"},
    ]
    registry = build_real_registry(llm=FailingLLM(), search=FakeSearchProvider())
    result = await registry.get("N09").execute({
        "N05": {
            "original_text": "小孩才做选择，我全都要",
            "fixed_anchors": ["小孩才做选择", "我全都要"],
        },
        "N08": {"sources": sources},
    }, None)
    variants = result["artifact"]["llm"]["variants"]
    assert len(variants) == 3
    assert all("steampowered.com" not in item["source_url"] for item in variants)


@pytest.mark.asyncio
async def test_n09_keeps_actual_rewrites_and_rejects_definition_or_generator_evidence():
    sources = [
        {"source_id": "V1", "url": "https://forum.example/1", "title": "网友衍生", "text": "大e了没有闪"},
        {"source_id": "V2", "url": "https://forum.example/2", "title": "谐音改编", "text": "我大姨来了，没油闪"},
        {"source_id": "V3", "url": "https://forum.example/3", "title": "网友变式", "text": "我大意了，没带闪"},
        {"source_id": "V4", "url": "https://wiki.example/4", "title": "词语解释", "text": "我大意了，没有闪这句话是网络流行语，意思是自己失误。"},
        {"source_id": "V5", "url": "https://memes.tw/maker/template/5", "title": "梗图生成器", "text": "我大意了阿，没有闪"},
    ]
    model_variants = [{
        "variant_text": source["text"],
        "source_id": source["source_id"],
        "source_url": source["url"],
        "evidence_quote": source["text"],
        "shared_anchor": "没有闪",
    } for source in sources]
    registry = build_real_registry(
        llm=FakeLLMProvider(responses=[{"variants": model_variants}]),
        search=FakeSearchProvider(),
    )
    result = await registry.get("N09").execute({
        "N05": {
            "original_text": "我大意了，没有闪",
            "fixed_anchors": ["我大意了", "没有闪"],
        },
        "N08": {"sources": sources},
    }, None)
    texts = [item["variant_text"] for item in result["artifact"]["llm"]["variants"]]
    assert texts == [
        "大e了没有闪",
        "我大姨来了，没油闪",
        "我大意了，没带闪",
    ]


@pytest.mark.asyncio
async def test_n09_rejects_incomplete_anchor_and_fact_avoidance_explanations():
    sources = [
        {"source_id": "V1", "url": "https://a.example/1", "title": "改编1", "text": "抛开事实不谈，整个银河系会动的都有责任。"},
        {"source_id": "V2", "url": "https://b.example/2", "title": "改编2", "text": "只是拿了个耳机，抛开事实不谈，这并不是什么大事对不对。"},
        {"source_id": "V3", "url": "https://c.example/3", "title": "改编3", "text": "抛开事实不谈的话，对方就没一点错误吗？"},
        {"source_id": "V4", "url": "https://d.example/4", "title": "截断", "text": "抛开事实不谈"},
        {"source_id": "V5", "url": "https://e.example/5", "title": "释义", "text": "抛开事实不谈这个梗出自一起网络事件。"},
    ]
    registry = build_real_registry(llm=FakeLLMProvider(responses=[{
        "variants": [{
            "variant_text": source["text"], "source_id": source["source_id"],
            "source_url": source["url"], "evidence_quote": source["text"],
            "shared_anchor": "抛开事实不谈",
        } for source in sources],
    }]), search=FakeSearchProvider())
    result = await registry.get("N09").execute({
        "N05": {
            "original_text": "抛开事实不谈，男生就一点错都没有吗",
            "fixed_anchors": ["抛开事实不谈"],
        },
        "N08": {"sources": sources},
    }, None)
    texts = [item["variant_text"] for item in result["artifact"]["llm"]["variants"]]
    assert texts == [source["text"].rstrip("。？") for source in sources[:3]]
