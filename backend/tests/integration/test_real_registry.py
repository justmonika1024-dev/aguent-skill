import pytest

from app.providers.base import SearchBatch, SearchResult
from app.providers.fake import FakeLLMProvider, FakeSearchProvider
from app.workflow.real_registry import build_real_registry


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
        }

    async def record_api_call(self, *args, **kwargs):
        return None


class UsageRepositoryStub:
    def __init__(self):
        self.api_calls = []

    async def record_api_call(self, *args, **kwargs):
        self.api_calls.append({"args": args, "kwargs": kwargs})


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
        "N10": {"canonical_template_text": template},
    }, None)
    payload = result["artifact"]["llm"]
    assert payload["decision"] == "PASS"
    assert payload["matched_variant_count"] == 3
    assert llm.requests == []


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
        {"source_id": "V3", "url": "https://wiki.example/3", "title": "用法举例", "text": "比如输了可以说：“我大意了，没有闪，年轻人不讲武德，偷袭我”"},
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
        "我大意了，没有闪，年轻人不讲武德，偷袭我",
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
