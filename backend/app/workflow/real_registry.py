"""Provider-backed registry used when real credentials are configured.

This intentionally keeps the MVP orchestration contract small: every language
node makes one structured LLM call, while N04/N08 perform an actual Exa search.
The state machine still owns all routing decisions.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from ..contracts.nodes import N12Output
from ..providers.base import (
    LLMProvider,
    NodeLLMRequest,
    ParameterProfile,
    SearchProvider,
    SearchRequest,
)
from .registry import NodeRegistry

_OUTCOMES = {
    "N01": "ACCEPTED", "N02": "PLANNED", "N03": "PLAN_READY", "N04": "RESULTS_FOUND",
    "N05": "SELECTED", "N06": "NOT_DUPLICATE", "N07": "PLAN_READY", "N08": "RESULTS_FOUND",
    "N09": "SUFFICIENT", "N10": "TEMPLATE_READY", "N11": "PASS",
    "N11.5": "STRUCTURE_PRESERVING_REWRITE", "N12": "VALID_BATCH", "N13": "HAS_QUALIFIED",
    "N14": "SELECTED", "N15": "DRAFT_READY", "N16": "NOT_DUPLICATE",
    "N17": "WAIT_HUMAN_DECISION", "N19": "PATCH_VALID", "N20": "COMPLETED",
}

# A smoke run exercises real language generation at representative planning,
# template, candidate, and selection stages.  Other nodes still execute and
# route normally, but avoid multiplying external calls during MVP validation.
_LLM_NODES = {"N01", "N02", "N03", "N05", "N07", "N09", "N10", "N11", "N11.5", "N12", "N13", "N14", "N15", "N19"}

_MAX_OUTPUT_TOKENS = {
    "N01": 1500, "N02": 4000, "N03": 1600, "N05": 1800, "N09": 2400,
    "N10": 1800, "N11": 1200, "N11.5": 1600, "N12": 6000,
    "N13": 4000, "N14": 1000, "N15": 1200, "N19": 1600,
}

_INSTRUCTIONS = {
    "N01": "规范化人工种子。输出 normalized_seed、core_expression、possible_original_phrases、initial_query_concepts。不得改写成凿agu。",
    "N02": "为自主发现提出中文纯文本文案梗候选。输出 discovery_hypothesis、keywords、known_example_phrases；known_example_phrases必须给出5个彼此独立、可直接搜索的完整原句或台词梗，不要给同一模板的5个变式。每句都应有可替换结构，并且你已知网上至少存在三种网友改编；不要选择单一情绪流行词（例如我自闭了）、释义句或泛化的meme生成器。formal_meme_titles是正式库已有标题，所有候选不得与其中任何标题相同或近似。",
    "N03": "根据人工种子或自主发现方向制定原始梗搜索计划。输出 queries 数组，3到5条；每条含 query_id、query、search_type(keyword或auto)、purpose。查询必须包含具体原句锚点，不要只搜中文经典文案梗。",
    "N05": "从N04真实搜索结果中只选择一个可被反复改编的中文文案梗。输出 title、original_text、fixed_anchors、source_id、source_url、evidence_quote、selection_reason。original_text必须逐字来自某条结果的title或text，禁止编造。",
    "N07": "只围绕N05选中的唯一原始梗制定变式搜索。输出 queries 数组4到6条，含 query_id、query、search_type、purpose；至少使用两个固定锚点和原句片段，目标是网友替换槽位后的实际变式。",
    "N09": "从N08真实结果中提取原始梗的网友变式。最多输出8条 variants，每条含 variant_text、source_id、source_url、evidence_quote、shared_anchor；只接受可在对应搜索结果正文中逐字找到且发生实质槽位替换的文案，排除原文转载、繁简标点异写、标题释义包裹和长上下文。",
    "N10": "根据N05唯一原始梗和N09有效变式抽取模板。输出 canonical_template_text、fixed_segments、slots、evidence_variant_texts、template_explanation。模板必须能重建原句和多个变式，不得包含agu或凿。",
    "N11": "验证N10模板能否覆盖原始梗和变式。输出 decision(PASS/REEXTRACT/MORE_EVIDENCE)、coverage、accuracy、problems。",
    "N11.5": "判断模板如何自然改写为凿agu。agu是人物，凿是作用于agu的动作；凿agu也可以整体名词化为标题、主语或宾语。实施方可按模板逻辑映射为研发方、发明方、创作者或组织者。输出 route、must_preserve、may_rewrite、rewrite_blueprint；route只能DIRECT_SLOT_FILL或STRUCTURE_PRESERVING_REWRITE。",
    "N12": "严格生成5条不同候选C1到C5。必须同时参考N10模板和N09中3至5条真实变式：变式只用于学习槽位替换方式、篇幅与克制度，不要归纳深层语义。agu始终是被凿的人；凿agu可作为完整事件短语进入标题、主语或宾语，正文无需机械重复动作。实施方可自然映射为研发方、发明方、创作者或组织者。至少一条采用最小替换，只改关键笑点并尽量保留原句其他部分；其他候选可选使用同济大学、高程群、群友、他或他们，不得强塞。输出route_used、candidates，每条含candidate_id、text、target_semantics、preserved_features、rewritten_features、slot_bindings、generation_approach。",
    "N13": "对N12五条候选评分。输出scores数组，含candidate_id、fluency、recognition、agu_fit、humor、rhythm、adaptation_restraint、minimal_replacement_effect、qualified，并输出qualified_candidate_ids。优先奖励原梗辨识度、改编克制度和最小替换效果；不要因研发方、描述等所有槽位都强行解释凿而加分。",
    "N14": "只从N13合格候选中选出一条，不得改写。输出selected_candidate_id、ranked_candidate_ids、selection_reason。",
    "N15": "生成正式梗包装。final_agu_text必须逐字等于N14选中的N12候选；输出title(4到40字)、normalized_title、final_agu_text、original、template、source_url。",
    "N19": (
        "根据七模块人工评价输出下一轮策略反馈。必须输出feedback_summary、affected_nodes、"
        "patch_operations、score_gaps、next_round_hypotheses。patch_operations只能用add向现有"
        "directive数组追加文字建议，不得修改阈值、质量开关、预算、安全、候选数量或路由。"
    ),
}


_MAX_FEEDBACK_TEXT_LENGTH = 300
_ALLOWED_PATCH_PATHS = {
    "/search/discovery_directives/-",
    "/search/variant_query_directives/-",
    "/generation/directives/-",
    "/evaluation/directives/-",
    "/admission/directives/-",
}
_EVALUATION_NODE_MAP = {
    "original_search_plan": ["N03", "N04"],
    "selected_original_meme": ["N05", "N06"],
    "variant_search_plan": ["N07"],
    "variant_search_results": ["N08", "N09"],
    "template_extraction": ["N10", "N11"],
    "candidate_generation": ["N12", "N13", "N14"],
    "final_result": ["N15", "N17"],
}
_WORKFLOW_NODE_KEYS = {
    "N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09",
    "N10", "N11", "N11.5", "N12", "N13", "N14", "N15", "N16", "N17",
    "N18", "N19", "N20",
}


def _safe_feedback_text(value: Any) -> str:
    return " ".join(str(value or "").split())[:_MAX_FEEDBACK_TEXT_LENGTH]


def _score_gaps(evaluation: dict[str, Any]) -> dict[str, int]:
    gaps: dict[str, int] = {}

    def collect(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for field, child in value.items():
                collect(child, (*path, str(field)))
        elif type(value) is int and 1 <= value < 4:
            gaps[".".join(path)] = 4 - value

    for module in _EVALUATION_NODE_MAP:
        collect(evaluation.get(module), (module,))
    return gaps


def _affected_nodes(evaluation: dict[str, Any]) -> list[str]:
    affected: list[str] = []
    gaps = _score_gaps(evaluation)
    for module, nodes in _EVALUATION_NODE_MAP.items():
        if any(key.startswith(module + ".") for key in gaps):
            affected.extend(nodes)
    return list(dict.fromkeys(affected))


def _safe_patch_operation(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    operation = raw.get("op")
    path = str(raw.get("path", ""))
    if operation not in {"add", "replace"} or path not in _ALLOWED_PATCH_PATHS:
        return None
    if "value" not in raw:
        return None
    value = raw["value"]
    if isinstance(value, str):
        value = _safe_feedback_text(value)
        if not value:
            return None
    elif isinstance(value, list):
        value = list(dict.fromkeys(
            text for item in value if (text := _safe_feedback_text(item))
        ))
    if path.endswith("/-") and (operation != "add" or not isinstance(value, str)):
        return None
    return {"op": operation, "path": path, "value": value}


def derive_required_patch_operations(
    evaluation: dict[str, Any], llm_patch: Any,
) -> list[dict[str, Any]]:
    """Merge safe LLM advice with mandatory low-score search corrections."""
    suggested = [
        operation for raw in (llm_patch if isinstance(llm_patch, list) else [])
        if (operation := _safe_patch_operation(raw)) is not None
    ]
    gaps = _score_gaps(evaluation)
    search_modules = ("variant_search_plan", "variant_search_results", "template_extraction")
    low_search_modules = [
        module for module in search_modules
        if any(key.startswith(module + ".") for key in gaps)
    ]
    required: list[dict[str, Any]] = []
    if low_search_modules:
        required.extend([
            {"op": "replace", "path": "/search/prefer_ugc_sources", "value": True},
            {"op": "replace", "path": "/search/exclude_exact_reprints", "value": True},
            {"op": "replace", "path": "/search/require_slot_replacement", "value": True},
        ])
        comments = [
            _safe_feedback_text(evaluation.get(module, {}).get("comment", ""))
            for module in low_search_modules
            if isinstance(evaluation.get(module), dict)
        ]
        comments = [comment for comment in comments if comment]
        gap_names = [key for key in gaps if key.split(".", 1)[0] in low_search_modules]
        feedback = "；".join(comments) or "、".join(gap_names)
        required.append({
            "op": "add",
            "path": "/search/variant_query_directives/-",
            "value": _safe_feedback_text(
                f"人工评价低于4分：{feedback}；下一轮优先UGC来源，排除原句转载，并要求网友槽位替换。"
            ),
        })

    operations: list[dict[str, Any]] = []
    scalar_indexes: dict[str, int] = {}
    directive_keys: set[tuple[str, str]] = set()
    for operation in [*suggested, *required]:
        path = operation["path"]
        if path.endswith("/-"):
            key = (path, operation["value"].casefold())
            if key not in directive_keys:
                directive_keys.add(key)
                operations.append(operation)
            continue
        if path in scalar_indexes:
            operations[scalar_indexes[path]] = operation
        else:
            scalar_indexes[path] = len(operations)
            operations.append(operation)
    return operations


def _compact_artifacts(node_key: str, value: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "N01": ["START"], "N02": ["START"], "N03": ["START", "N01", "N02"],
        "N05": ["START", "N04"], "N07": ["N05"], "N09": ["N05", "N08"],
        "N10": ["N05", "N09"], "N11": ["N05", "N09", "N10"],
        "N11.5": ["N10", "N11"], "N12": ["N05", "N09", "N10", "N11.5"],
        "N13": ["N05", "N10", "N12"], "N14": ["N12", "N13"],
        "N15": ["N05", "N10", "N12", "N14"], "N19": ["N13", "N14", "N15", "N18"],
    }.get(node_key, list(value))
    result = {key: value[key] for key in keep if key in value}
    if node_key == "N05" and isinstance(result.get("N04"), dict):
        seed = str(result.get("START", {}).get("seed_text", ""))
        anchors = [part.strip() for part in re.split(r"[，。！？?!]", seed)
                   if len(part.strip()) >= 4]
        compact_search = dict(result["N04"])
        ranked_sources = sorted(
            enumerate(compact_search.get("sources", [])),
            key=lambda pair: (
                -sum(anchor in (str(pair[1].get("title", ""))
                                + str(pair[1].get("text", "")))
                     for anchor in anchors),
                pair[0],
            ),
        )
        compact_sources = []
        for _, source in ranked_sources[:10]:
            item = dict(source)
            text = str(item.get("text", ""))
            match = next((text.find(anchor) for anchor in anchors if anchor in text), -1)
            start = max(0, match - 200) if match >= 0 else 0
            item["text"] = text[start:start + 700]
            compact_sources.append(item)
        compact_search["sources"] = compact_sources
        compact_search.pop("results", None)
        result["N04"] = compact_search
    if node_key == "N09" and isinstance(result.get("N08"), dict):
        selected = result.get("N05", {})
        selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
        anchors = list(selected.get("fixed_anchors", [])) if isinstance(selected, dict) else []
        if "你说的对，但是" in anchors:
            anchors.append("你说得对，但是")
        compact_search = dict(result["N08"])
        compact_sources = []
        for source in compact_search.get("sources", []):
            item = dict(source)
            text = str(item.get("text", ""))
            excerpts: list[str] = []
            for anchor in anchors:
                start = 0
                while anchor and len(excerpts) < 4:
                    index = text.find(anchor, start)
                    if index < 0:
                        break
                    left = max(0, text.rfind("。", 0, index) + 1)
                    right = text.find("。", index)
                    right = len(text) if right < 0 else right + 1
                    excerpt = text[left:right].strip()
                    if len(excerpt) > 600:
                        excerpt = text[max(0, index - 80): min(len(text), index + 520)].strip()
                    if excerpt and excerpt not in excerpts:
                        excerpts.append(excerpt)
                    start = index + len(anchor)
            item["text"] = "\n".join(excerpts)[:600]
            if item["text"]:
                compact_sources.append(item)
            if len(compact_sources) >= 8:
                break
        compact_search["sources"] = compact_sources[:8]
        compact_search.pop("results", None)
        result["N08"] = compact_search
    for search_key in ("N04", "N08"):
        search = result.get(search_key)
        if isinstance(search, dict):
            search = dict(search)
            sources = []
            for source in search.get("sources", [])[:20]:
                item = dict(source); item["text"] = item.get("text", "")[:1800]; sources.append(item)
            search["sources"] = sources; search.pop("results", None); result[search_key] = search
    if isinstance(result.get("N09"), dict):
        n09 = dict(result["N09"])
        n09_payload = n09.get("llm", n09)
        if isinstance(n09_payload, dict):
            n09_payload = dict(n09_payload)
            variants = n09_payload.get("variants", [])
            if node_key in {"N10", "N11"}:
                structural = [v for v in variants if "自主研发的一款" in v.get("variant_text", "")]
                variants = structural or variants
                compact_variants = []
                for variant in variants[:6]:
                    item = dict(variant)
                    first = item.get("variant_text", "").split("。", 1)[0] + "。"
                    item["variant_text"] = first
                    item["evidence_quote"] = first
                    compact_variants.append(item)
                variants = compact_variants
            if node_key == "N12":
                variants = [
                    {
                        "variant_text": str(item.get("variant_text", "")),
                        "source_url": str(item.get("source_url", "")),
                    }
                    for item in variants[:5] if isinstance(item, dict)
                ]
            n09_payload["variants"] = variants[:12]
            if "llm" in n09: n09["llm"] = n09_payload
            else: n09 = n09_payload
            result["N09"] = n09
    return result


_AGU_OBJECT = r"(?:(?:同济大学|高程群)的)*agu"
_ACTION_ON_AGU = re.compile(
    rf"(?:"
    rf"凿(?:了|着|过)?(?:一下|一遍|几下)?{_AGU_OBJECT}"
    rf"|(?:把|将){_AGU_OBJECT}(?:给)?凿(?:了|着|过)?(?:一下|一遍|几下)?"
    rf"|{_AGU_OBJECT}(?:又|再|已经|刚刚|刚|还)?(?:被|让|给)"
    rf"(?:同济大学的人|高程群群友|群友|他们|她们|他|她|大家|我们)?"
    rf"(?:给)?凿(?:了|着|过)?(?:一下|一遍|几下)?"
    rf")"
)
_TOOL_PAGE = re.compile(
    r"(?:meme\s*generator|生成器|在线制作|表情包制作|AI.{0,8}文案工具)",
    re.IGNORECASE,
)
_STOREFRONT_SOURCE = re.compile(
    r"(?:store\.steampowered\.com|apps\.apple\.com|play\.google\.com|"
    r"microsoft\.com/(?:[^/]+/)?store|/download(?:/|\?|$)|/product(?:/|\?|$)|"
    r"/maker/template/|/soft/\d+)",
    re.IGNORECASE,
)


def _is_tool_source(source: dict[str, Any], quote: str = "") -> bool:
    haystack = "\n".join((
        str(source.get("title", "")),
        str(source.get("url", "")),
        quote,
    ))
    return bool(_TOOL_PAGE.search(haystack))


def _is_definition_or_explanation(text: str) -> bool:
    return bool(re.search(
        r"(?:是什么梗|什么意思|意思是|就是(?:用来)?调侃|指的是|源于|出处(?:是|源自)|"
        r"网络流行(?:语|词)|这句话(?:表示|是)|用于形容|用来形容)",
        text,
        re.IGNORECASE,
    ))


def _evidence_backed_original(sources: list[dict[str, Any]], references: list[str]) -> tuple[dict[str, Any], str] | None:
    best: tuple[float, dict[str, Any], str] | None = None
    for source in sources:
        if _is_tool_source(source):
            continue
        title = str(source.get("title", ""))
        text = str(source.get("text", ""))
        candidates = re.findall(r"《([^》]{4,100})》", title + "\n" + text)
        candidates.extend(re.split(r"[\n。！？|]", title + "\n" + text))
        for candidate in candidates:
            candidate = re.sub(r"^[#\s]+", "", candidate).strip()
            candidate = re.split(r"[（(]", candidate, maxsplit=1)[0].strip(" ：:-")
            if not 6 <= len(candidate) <= 120:
                continue
            if not any(marker in candidate for marker in ("但是", "可是", "但我", "全都要", "才做选择", "一眼就看出", "你说的对", "你说得对")):
                continue
            score = max((SequenceMatcher(None, candidate, reference).ratio() for reference in references), default=0.0)
            if best is None or score > best[0]:
                best = (score, source, candidate)
    if best is None or best[0] < 0.3:
        return None
    return best[1], best[2]


def _core_phrase_from_evidence(text: str, references: list[str]) -> str:
    if not references:
        return text
    candidates = [
        segment.strip(" \t\r\n，,；;：:")
        for segment in re.split(r"[。！？!?\n]", text)
        if 6 <= len(segment.strip()) <= 80
    ]
    if not candidates:
        return text
    score = lambda candidate: max(
        SequenceMatcher(None, _normalize_duplicate_text(candidate),
                        _normalize_duplicate_text(reference)).ratio()
        for reference in references
    )
    best = max(candidates, key=score)
    if score(best) >= 0.55 and score(best) >= score(text) + 0.1:
        return best
    return text


def _concrete_phrases(node: Any) -> list[str]:
    payload = node.get("llm", node) if isinstance(node, dict) else {}
    if not isinstance(payload, dict):
        return []
    values = payload.get("known_example_phrases") or payload.get("possible_original_phrases") or []
    generic = re.compile(r"^(?:中文|网络|经典|热门|流行|文案|台词|模板|meme|梗|段子|表情包|\s)+$", re.IGNORECASE)
    return [str(value).strip() for value in values
            if isinstance(value, str) and 6 <= len(value.strip()) <= 180
            and not generic.fullmatch(value.strip())]


def _specific_search_plan(phrase: str) -> list[dict[str, str]]:
    phrase = phrase.strip().strip('"“”')
    anchor = phrase[: min(len(phrase), 18)]
    return [
        {"query_id": "OQ1", "query": f'"{phrase}"', "search_type": "keyword", "purpose": "找完整原句和出处"},
        {"query_id": "OQ2", "query": f'"{anchor}" 什么梗 原句', "search_type": "auto", "purpose": "找梗百科或来源说明"},
        {"query_id": "OQ3", "query": f'"{anchor}" 改编 变式', "search_type": "auto", "purpose": "验证该句式存在网友改编"},
        {"query_id": "OQ4", "query": f'"{anchor}" 衍生梗', "search_type": "keyword", "purpose": "补充传播和变式证据"},
    ]


def _multi_phrase_search_plan(phrases: list[str]) -> list[dict[str, str]]:
    plan = [
        {"query_id": f"OQ{index}", "query": f'"{phrase}"', "search_type": "keyword",
         "purpose": "并行验证候选原句和真实网页证据"}
        for index, phrase in enumerate(phrases[:5], 1)
    ]
    fillers = [
        (phrases[0] + " 什么梗 原句", "auto", "补充首个候选的出处说明"),
        (phrases[min(1, len(phrases) - 1)] + " 网友改编", "auto", "补充候选的改编证据"),
    ]
    for query, search_type, purpose in fillers:
        if len(plan) >= 5:
            break
        plan.append({"query_id": f"OQ{len(plan) + 1}", "query": query,
                     "search_type": search_type, "purpose": purpose})
    return plan


def _normalize_anchors(original: str, raw_anchors: Any) -> list[str]:
    if "你说的对，但是《" in original and "自主研发的一款" in original:
        return ["你说的对，但是", "是由", "自主研发的一款", "。"]
    if isinstance(raw_anchors, str):
        anchors = [part.strip() for part in re.split(r"\[[^\]]+\]|\{[^{}]+\}", raw_anchors)]
    elif isinstance(raw_anchors, list):
        anchors = [str(part).strip() for part in raw_anchors if isinstance(part, str)]
    else:
        anchors = []
    anchors = [anchor for anchor in anchors if len(anchor) >= 2]
    if not anchors:
        anchors = [part.strip() for part in re.split(r"[，。！？]", original) if len(part.strip()) >= 4]
    return list(dict.fromkeys(anchors))[:8]


def _variant_search_plan(
    original: str,
    anchors: list[str],
    search_strategy: dict[str, Any] | None = None,
    directives: list[str] | None = None,
) -> list[dict[str, str]]:
    anchors = _normalize_anchors(original, anchors)
    primary = anchors[0] if anchors else original[:12]
    secondary = anchors[1] if len(anchors) > 1 else original[-8:]
    strategy = search_strategy if isinstance(search_strategy, dict) else {}
    directives = list(dict.fromkeys(directives or []))
    plan = [
        {
            "query_id": "VQ1", "query": original, "search_type": "keyword",
            "purpose": "保留精确原句基线，用于识别并排除转载",
            "strategy_origin": "BASELINE_EXACT_ORIGINAL",
        },
        {
            "query_id": "VQ2", "query": f'"{primary}" "{secondary}" 网友改编',
            "search_type": "auto", "purpose": "寻找保留两个固定锚点的槽位替换",
            "strategy_origin": "FIXED_ANCHOR_SLOT_REPLACEMENT",
        },
        {
            "query_id": "VQ3", "query": f'"{primary}" 换成 改编',
            "search_type": "auto", "purpose": "寻找替换原句可变语境的槽位替换",
            "strategy_origin": "REPLACEMENT_CONTEXT",
        },
    ]
    if strategy.get("prefer_ugc_sources"):
        plan.append({
            "query_id": "VQ4", "query": f'"{primary}" 论坛 微博 知乎 网友改编',
            "search_type": "auto", "purpose": "优先定位论坛、微博、知乎等UGC来源",
            "strategy_origin": "STRATEGY_PREFER_UGC",
        })
    for directive in directives[:2]:
        plan.append({
            "query_id": f"VQ{len(plan) + 1}",
            "query": f'"{primary}" {directive}',
            "search_type": "auto",
            "purpose": "执行人工反馈指令并寻找槽位替换",
            "strategy_origin": "FEEDBACK_DIRECTIVE",
        })
    fillers = [
        (f'"{primary}" 衍生梗 网友原文', "定位网友发布的实际衍生文案", "UGC_VARIANT_FALLBACK"),
        (f'"{primary}" "{secondary}" 变体', "补足固定锚点组合覆盖", "ANCHOR_COMBINATION_FALLBACK"),
    ]
    for query, purpose, origin in fillers:
        if len(plan) >= 5:
            break
        plan.append({
            "query_id": f"VQ{len(plan) + 1}", "query": query,
            "search_type": "auto", "purpose": purpose, "strategy_origin": origin,
        })
    return plan[:6]


def _normalize_meme_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().replace("你说得对", "你说的对")
                  .replace("“", '"').replace("”", '"').rstrip("。！？!?"))


_COMMON_TRADITIONAL_TO_SIMPLIFIED = str.maketrans({
    "開": "开", "頭": "头", "卻": "却", "這": "这", "結": "结",
    "網": "网", "絡": "络", "語": "语", "詞": "词", "義": "义",
    "為": "为", "說": "说", "對": "对", "發": "发", "現": "现",
    "實": "实", "體": "体", "來": "来", "時": "时", "個": "个",
    "們": "们", "與": "与", "後": "后", "裡": "里", "從": "从",
    "熱": "热", "門": "门", "話": "话", "題": "题", "總": "总",
    "讓": "让", "覺": "觉", "興": "兴", "編": "编", "寫": "写",
    "學": "学", "經": "经", "過": "过", "還": "还", "樣": "样",
    "嗎": "吗", "無": "无", "關": "关", "點": "点", "應": "应",
    "機": "机", "會": "会", "進": "进", "長": "长", "間": "间",
    "問": "问", "頁": "页", "區": "区", "國": "国", "愛": "爱",
    "傳": "传", "統": "统", "變": "变", "種": "种", "書": "书",
    "圖": "图", "簡": "简", "轉": "转", "換": "换", "純": "纯",
    "異": "异", "廣": "广", "東": "东", "臺": "台", "灣": "湾",
    "萬": "万", "沒": "没", "風": "风", "雲": "云", "電": "电",
    "車": "车", "馬": "马", "鳥": "鸟", "魚": "鱼", "龍": "龙",
    "鳳": "凤", "貓": "猫", "劉": "刘", "張": "张", "楊": "杨",
    "陳": "陈", "趙": "赵", "錢": "钱", "孫": "孙", "難": "难",
    "歡": "欢", "歸": "归", "聽": "听", "見": "见", "給": "给",
    "認": "认", "識": "识", "講": "讲", "請": "请", "謝": "谢",
    "讀": "读", "買": "买", "賣": "卖", "著": "着", "麼": "么",
    "於": "于", "將": "将", "當": "当", "麗": "丽", "嚴": "严",
    "壞": "坏", "媽": "妈", "爺": "爷", "兒": "儿", "歲": "岁",
    "號": "号", "遠": "远", "邊": "边", "選": "选", "擇": "择",
    "啟": "启", "閉": "闭", "報": "报", "導": "导", "業": "业",
    "產": "产", "線": "线", "級": "级", "數": "数", "據": "据",
    "庫": "库", "測": "测", "試": "试", "驗": "验", "錯": "错",
    "誤": "误", "斷": "断", "軟": "软", "項": "项", "標": "标",
    "準": "准", "確": "确", "備": "备", "計": "计", "劃": "划",
    "務": "务", "領": "领", "組": "组", "織": "织", "構": "构",
    "運": "运", "維": "维", "護": "护", "該": "该", "夠": "够",
    "處": "处", "輸": "输", "鍵": "键", "檔": "档", "檢": "检",
    "查": "查", "複": "复", "製": "制", "刪": "删", "增": "增",
    "減": "减", "險": "险", "權": "权", "限": "限", "態": "态",
    "狀": "状", "敗": "败", "終": "终", "歷": "历", "記": "记",
    "錄": "录", "資": "资", "訊": "讯", "註": "注", "冊": "册",
    "登": "登", "陸": "陆", "戶": "户", "帳": "账",
    "聯": "联", "繫": "系", "環": "环", "境": "境",
    "設": "设", "置": "置", "顯": "显", "示": "示",
    "隱": "隐", "藏": "藏", "優": "优", "先": "先", "隊": "队",
    "列": "列", "協": "协", "議": "议", "響": "响", "載": "载",
    "則": "则", "僅": "仅", "達": "达", "額": "额",
    "滿": "满", "縮": "缩", "擴": "扩", "寬": "宽", "緊": "紧",
    "鬆": "松", "細": "细", "節": "节", "內": "内",
    "畫": "画", "顏": "颜", "聲": "声", "類": "类",
    "別": "别", "輕": "轻", "重": "重", "強": "强", "弱": "弱",
    "復": "复", "動": "动",
    "暫": "暂", "停": "停", "繼": "继", "續": "续", "完": "完",
    "畢": "毕", "順": "顺", "序": "序", "併": "并", "獨": "独",
    "衝": "冲", "突": "突", "佔": "占", "屬": "属",
    "獲": "获", "須": "须",
})
_VARIANT_WRAPPER = re.compile(
    r"(?:是什么意思|什么意思|意思是|含义|释义|赏析|解析|解读|出处|"
    r"原句(?:是|：|:)?|句子赏析|标题|台词|这句话|这句|网络流行(?:语|词)|"
    r"(?:网友|有人)(?:改成了|改写成|改编成)|笑死)",
    re.IGNORECASE,
)


def _canonical_original_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = normalized.translate(_COMMON_TRADITIONAL_TO_SIMPLIFIED)
    return _normalize_meme_text(normalized).casefold()


def _normalize_variant_compare(text: str) -> str:
    normalized = _canonical_original_key(text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", normalized)


def is_substantive_variant(
    original: str, candidate: str, anchors: list[str],
) -> bool:
    """Return whether candidate changes a real slot instead of wrapping a repost."""
    original_normalized = _normalize_variant_compare(original)
    candidate_normalized = _normalize_variant_compare(candidate)
    if not original_normalized or not candidate_normalized:
        return False
    if _VARIANT_WRAPPER.search(candidate):
        return False
    if (candidate_normalized == original_normalized
            or original_normalized in candidate_normalized
            or candidate_normalized in original_normalized):
        return False
    if len(candidate_normalized) > max(220, len(original_normalized) * 3):
        return False
    similarity = SequenceMatcher(
        None, original_normalized, candidate_normalized,
    ).ratio()
    normalized_anchors = list(dict.fromkeys(
        normalized for anchor in anchors
        if (normalized := _normalize_variant_compare(anchor))
    ))
    shared_anchors = [
        anchor for anchor in normalized_anchors
        if anchor in original_normalized and anchor in candidate_normalized
    ]
    if similarity < 0.35 and not shared_anchors:
        return False
    original_slots = original_normalized
    candidate_slots = candidate_normalized
    for anchor in shared_anchors:
        original_slots = original_slots.replace(anchor, "", 1)
        candidate_slots = candidate_slots.replace(anchor, "", 1)
    if similarity >= 0.9 and SequenceMatcher(
        None, original_slots, candidate_slots,
    ).ratio() >= 0.86:
        return False
    return bool(shared_anchors or similarity >= 0.45)


def _normalize_duplicate_text(text: str) -> str:
    normalized = _canonical_original_key(text).replace("小孩子", "小孩")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", normalized)


def _duplicate_similarity(left: str, right: str) -> float:
    left_normalized = _normalize_duplicate_text(left)
    right_normalized = _normalize_duplicate_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if min(len(left_normalized), len(right_normalized)) >= 6 and (
        left_normalized in right_normalized or right_normalized in left_normalized
    ):
        return 1.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def _template_pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^{}]+\})", _normalize_meme_text(template))
    pattern = "".join((".*?" if "可选" in part else ".+?")
                      if part.startswith("{") and part.endswith("}") else re.escape(part)
                      for part in parts)
    return re.compile(f"^{pattern}$")


def _validate_template(template: str, original: str, variants: list[dict[str, Any]]) -> None:
    slots = re.findall(r"\{[^{}]+\}", template)
    fixed = re.sub(r"\{[^{}]+\}", "", template)
    fixed_chars = re.sub(r"[\s，。！？、；：,.!?;:\"'《》]", "", fixed)
    if not slots or len(fixed_chars) < 4:
        raise ValueError("N10 template must contain reusable slots and meaningful fixed structure")
    pattern = _template_pattern(template)
    if not pattern.fullmatch(_normalize_meme_text(original)):
        raise ValueError("N10 template does not reconstruct the selected original meme")
    matched = 0
    for variant in variants:
        text = str(variant.get("variant_text", "")).split("。", 1)[0]
        if pattern.fullmatch(_normalize_meme_text(text)):
            matched += 1
    if matched < 2:
        raise ValueError("N10 template is not supported by at least two verified variants")


def _supported_replaceable_prefix(original: str, variants: list[dict[str, Any]]) -> str:
    normalized_original = _normalize_meme_text(original)
    variant_texts = [_normalize_meme_text(str(item.get("variant_text", ""))) for item in variants]
    replacing_variants = [text for text in variant_texts if normalized_original not in text]
    for end in range(len(normalized_original) - 2, 3, -1):
        prefix = normalized_original[:end]
        if len(normalized_original) - len(prefix) >= 2 and sum(
            prefix in text for text in replacing_variants
        ) >= 2:
            return prefix
    return ""


def _clean_variant_text(original: str, text: str, anchors: list[str]) -> str | None:
    text = text.strip()
    quoted = re.findall(r"[“「『]\s*([^”」』]{4,160}?)\s*[”」』]", text)
    if quoted:
        original_normalized = _normalize_duplicate_text(original)
        related = [
            phrase.strip() for phrase in quoted
            if SequenceMatcher(
                None, original_normalized, _normalize_duplicate_text(phrase),
            ).ratio() >= 0.35
        ]
        if related:
            text = max(related, key=len)
    explanatory = re.compile(
        r"(?:是什么梗|什么意思|网络流行语|网络流行词|网梗词|意义及解释|"
        r"词意|这句话|这个梗|意思是|是一个.{0,8}梗|是指|源于|出自|出处|最初|"
        r"用意是|说法是|年度金句|摘要|梗图产生器)",
        re.IGNORECASE,
    )
    if explanatory.search(text):
        return None
    original_normalized = _normalize_duplicate_text(original)
    text_normalized = _normalize_duplicate_text(text)
    if not text_normalized or text_normalized == original_normalized:
        return None
    similarity = SequenceMatcher(None, original_normalized, text_normalized).ratio()
    slot_replacement_structure = (
        (re.match(r"^小孩(?:子)?才做选择", original) and original.endswith("我全都要"))
        or ("你说的对，但是《" in original and "自主研发的一款" in original)
    )
    if (not slot_replacement_structure
            and abs(len(text_normalized) - len(original_normalized)) <= 2
            and similarity >= 0.88):
        return None
    if (text_normalized.startswith(original_normalized)
            and len(text_normalized) > max(80, len(original_normalized) * 3)):
        return None
    if (original_normalized.startswith(text_normalized)
            and len(text_normalized) < len(original_normalized) * 0.7):
        return None
    if not is_substantive_variant(original, text, anchors):
        return None
    return text.rstrip("。！？!?")


def _filter_verified_variants(
    original: str, anchors: list[str], variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    noise = re.compile(r"(?:^\s*#|下载|购买|Steam|中文名|分享到|关注我们|最新进展|网络梗的一种|网络流行词|作为网络语|别名|拼音)", re.IGNORECASE)
    filtered: list[dict[str, Any]] = []
    per_url: dict[str, int] = {}
    seen_evidence: set[tuple[str, str]] = set()
    for variant in variants:
        text = str(variant.get("variant_text", "")).strip()
        url = str(variant.get("source_url", ""))
        if not text or len(text) > 220 or noise.search(text) or _STOREFRONT_SOURCE.search(url):
            continue
        cleaned_text = _clean_variant_text(original, text, anchors)
        if cleaned_text is None:
            continue
        text = cleaned_text
        if "你说的对，但是《" in original and "自主研发的一款" in original:
            normalized = text.replace("你说得对", "你说的对")
            if "你说的对，但是" not in normalized or "自主研发的一款" not in normalized:
                continue
        elif re.match(r"^小孩(?:子)?才做选择", original) and original.endswith("我全都要"):
            if not re.search(r"小孩(?:子)?才做选择", text) or not any(token in text for token in ("都要", "全都要", "什么都没有")):
                continue
        elif original == "我真的会谢":
            if not re.search(r"我真的会谢[！!。.]?$", text) or len(text) > 80:
                continue
        if per_url.get(url, 0) >= 3:
            continue
        normalized_text = _normalize_variant_compare(text)
        evidence_key = (normalized_text, url)
        if evidence_key in seen_evidence:
            continue
        cleaned_variant = dict(variant)
        cleaned_variant["variant_text"] = text
        filtered.append(cleaned_variant)
        seen_evidence.add(evidence_key)
        per_url[url] = per_url.get(url, 0) + 1
        if len(filtered) >= 8:
            break
    return filtered


_MAX_VARIANT_SEARCH_RETRIES = 2


def _runtime_exhausted_originals(services: Any) -> list[str]:
    strategy_snapshot = (
        services.get("strategy_snapshot") if isinstance(services, dict) else None
    )
    values = getattr(strategy_snapshot, "exhausted_originals", None)
    if values is None and isinstance(strategy_snapshot, dict):
        values = strategy_snapshot.get("exhausted_originals")
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(
        _canonical_original_key(value) for value in values
        if isinstance(value, str) and _canonical_original_key(value)
    ))


def _filter_exhausted_sources(
    sources: list[dict[str, Any]], exhausted_originals: list[str],
) -> tuple[list[dict[str, Any]], int]:
    exhausted_keys = [
        _normalize_variant_compare(original) for original in exhausted_originals
        if len(_normalize_variant_compare(original)) >= 6
    ]
    if not exhausted_keys:
        return list(sources), 0
    eligible: list[dict[str, Any]] = []
    filtered_count = 0
    for source in sources:
        evidence = _normalize_variant_compare(
            str(source.get("title", "")) + "\n" + str(source.get("text", "")),
        )
        if any(original in evidence for original in exhausted_keys):
            filtered_count += 1
        else:
            eligible.append(source)
    return eligible, filtered_count


def _remove_exhausted_originals(
    parsed: dict[str, Any], exhausted_originals: list[str],
) -> None:
    excluded = {
        _normalize_variant_compare(original) for original in exhausted_originals
    }
    for field_name in ("known_example_phrases", "possible_original_phrases"):
        values = parsed.get(field_name)
        if isinstance(values, list):
            parsed[field_name] = [
                value for value in values
                if not isinstance(value, str)
                or _normalize_variant_compare(value) not in excluded
            ]


def _bounded_variant_fallback(
    services: Any,
    original: str,
    *,
    retry_outcome: str,
    reason: str,
) -> tuple[str, dict[str, Any]]:
    strategy_snapshot = (
        services.get("strategy_snapshot") if isinstance(services, dict) else None
    )
    counters = getattr(strategy_snapshot, "loop_counters", None)
    original_key = _canonical_original_key(original)
    key = f"variant_search:{original_key}"
    current = int(counters.get(key, 0)) if isinstance(counters, dict) else 0
    if current >= _MAX_VARIANT_SEARCH_RETRIES:
        outcome = "ABANDON_ORIGINAL"
        count = current
        exhausted_originals = getattr(
            strategy_snapshot, "exhausted_originals", None,
        )
        if (isinstance(exhausted_originals, list) and original_key
                and original_key not in {
                    _canonical_original_key(value)
                    for value in exhausted_originals if isinstance(value, str)
                }):
            exhausted_originals.append(original_key)
    else:
        count = current + 1
        if isinstance(counters, dict):
            counters[key] = count
        outcome = retry_outcome
    return outcome, {
        "count": count,
        "threshold": _MAX_VARIANT_SEARCH_RETRIES,
        "reason": reason,
    }


_PRODUCT_TEMPLATE = "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"


def _minimal_product_replacement(original: str) -> str | None:
    if "你说的对，但是《" not in original or "自主研发的一款" not in original:
        return None
    replaced, count = re.subn(r"《[^》]+》", "《凿agu》", original, count=1)
    return replaced if count == 1 else None


def _invalid_agu_identity(text: str) -> bool:
    for title in re.findall(r"《([^》]*)》", text):
        if "agu" in title and not _ACTION_ON_AGU.search(title):
            return True
    without_action = _ACTION_ON_AGU.sub("", text)
    return bool(re.search(r"agu是.{0,12}(游戏|作品|计划|身份|设定)", without_action))


def _n12_problem(parsed: dict[str, Any], value: dict[str, Any] | None = None) -> str | None:
    candidates = parsed.get("candidates", [])
    texts = [c.get("text", "") for c in candidates if isinstance(c, dict)]
    if len(texts) != 5:
        return "N12 must return exactly five candidates"
    if len(set(texts)) != 5:
        return "N12 candidates must be distinct"
    if any(not _ACTION_ON_AGU.search(text) for text in texts):
        return "N12 must treat agu as the person receiving the action 凿"
    if any(_invalid_agu_identity(text) for text in texts):
        return "N12 must treat agu as the person receiving the action, not a title or identity"
    original_node = (value or {}).get("N05", {})
    original_node = original_node.get("llm", original_node) if isinstance(original_node, dict) else {}
    original = str(original_node.get("original_text", "")) if isinstance(original_node, dict) else ""
    template_node = (value or {}).get("N10", {})
    template_node = template_node.get("llm", template_node) if isinstance(template_node, dict) else {}
    template = str(template_node.get("canonical_template_text", "")) if isinstance(template_node, dict) else ""
    expected_minimal = _minimal_product_replacement(original) if template == _PRODUCT_TEMPLATE else None
    if expected_minimal and not any(
        _normalize_meme_text(text) == _normalize_meme_text(expected_minimal) for text in texts
    ):
        return "N12 product introduction candidates require at least one minimal replacement"
    n115 = (value or {}).get("N11.5", {})
    n115 = n115.get("llm", n115) if isinstance(n115, dict) else {}
    route = parsed.get("route_used", parsed.get("route", n115.get("route")))
    must_preserve = n115.get("must_preserve", []) if isinstance(n115, dict) else []
    if route == "STRUCTURE_PRESERVING_REWRITE" and must_preserve:
        if any(any(anchor not in text for anchor in must_preserve) for text in texts):
            return "N12 structure rewrite must preserve required template anchors"
    integration_mode = n115.get("integration_mode")
    if integration_mode in {"CAUSAL_CONTEXT", "SLOT_FILL"} and must_preserve:
        simple_action = re.compile(
            r"^(?:我|他|她|我们|他们|大家)(?:正在|已经|都在|来|快来|赶紧)?"
            r"凿(?:了|着|过)?agu$"
        )
        for text in texts:
            for anchor in must_preserve:
                remainder = text.replace(anchor, "", 1)
                remainder = re.sub(r"[\s，。！？、；：,.!?;:\"'《》]", "", remainder)
                if simple_action.fullmatch(remainder):
                    if integration_mode == "SLOT_FILL":
                        return "N12 must fill template-compatible slot content, not use a bare 凿agu action"
                    return "N12 fixed catchphrase must causally integrate 凿agu, not append an isolated action"
    return None


class RealWorkflowNode:
    def __init__(self, key: str, outcome: str, llm: LLMProvider | None, search: SearchProvider | None, repository: Any = None) -> None:
        self.key, self.outcome, self.llm, self.search, self.repository = key, outcome, llm, search, repository

    async def execute(self, value: Any, services: Any = None) -> dict[str, Any]:
        run_id = services.get("run_id", "unknown") if isinstance(services, dict) else context_run_id(value)
        outcome = self.outcome
        parsed: dict[str, Any]
        if self.key in {"N04", "N08"}:
            if self.search is None:
                raise RuntimeError("search provider is not configured")
            plan_key = "N03" if self.key == "N04" else "N07"
            plan = value.get(plan_key, {}) if isinstance(value, dict) else {}
            plan = plan.get("llm", plan) if isinstance(plan, dict) else {}
            queries = plan.get("queries", []) if isinstance(plan, dict) else []
            if self.key == "N08" and not queries and isinstance(value, dict):
                selected = value.get("N05", {})
                selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
                original = selected.get("original_text", "") if isinstance(selected, dict) else ""
                anchors = selected.get("fixed_anchors", []) if isinstance(selected, dict) else []
                if original:
                    queries = [
                        {"query": original, "search_type": "keyword", "query_id": "VQ1"},
                        {"query": f'"{original[:12]}" 改编', "search_type": "auto", "query_id": "VQ2"},
                        {"query": " ".join(anchors[:2]) + " 梗 变式", "search_type": "auto", "query_id": "VQ3"},
                        {"query": f'{anchors[0] if anchors else original[:8]} 衍生梗 完整版', "search_type": "keyword", "query_id": "VQ4"},
                    ]
            if self.key == "N08" and isinstance(value, dict):
                selected = value.get("N05", {}); selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
                original = selected.get("original_text", "") if isinstance(selected, dict) else ""
                anchor = (selected.get("fixed_anchors") or [original[:6]])[0] if isinstance(selected, dict) else ""
                discovered: list[str] = []
                for source in value.get("N04", {}).get("sources", []):
                    for chunk in re.split(r"[。\n]", source.get("text", "")):
                        chunk = chunk.strip()
                        if anchor and anchor in chunk and "自主研发的一款" in chunk and chunk != original and 15 <= len(chunk) <= 180:
                            if chunk not in discovered: discovered.append(chunk)
                for index, variant in enumerate(discovered[:2], 1):
                    queries.append({"query_id": f"VQX{index}", "query": variant, "search_type": "keyword", "purpose": "为已发现变式补充独立来源"})
            if not queries:
                seed = value.get("seed_text") if isinstance(value, dict) else None
                queries = [{"query": seed or "中文经典文案梗 模板 变式", "search_type": "auto"}]
            all_results: list[Any] = []
            failures: list[dict[str, Any]] = []
            request_ids: list[str] = []
            costs: list[float] = []
            for item in queries:
                query = item if isinstance(item, str) else item.get("query", "")
                try:
                    requested_type = item.get("search_type", "auto") if isinstance(item, dict) else "auto"
                    search_type = requested_type if requested_type in {"keyword", "auto"} else "auto"
                    batch = await self.search.search(SearchRequest(query=query, search_type=search_type, num_results=5 if self.key == "N04" else 10, max_characters=1500 if self.key == "N04" else 5000, query_id=item.get("query_id") if isinstance(item, dict) else None))
                    all_results.extend(r.__dict__ for r in batch.results)
                    if batch.request_id: request_ids.append(batch.request_id)
                    if isinstance(batch.cost_dollars, (int, float)):
                        costs.append(float(batch.cost_dollars))
                    elif isinstance(batch.cost_dollars, dict) and isinstance(batch.cost_dollars.get("total"), (int, float)):
                        costs.append(float(batch.cost_dollars["total"]))
                    if self.repository:
                        cost = batch.cost_dollars if isinstance(batch.cost_dollars, (int, float)) else (batch.cost_dollars.get("total") if isinstance(batch.cost_dollars, dict) else None)
                        await self.repository.record_api_call(run_id, api_type="search", provider="exa", provider_request_id=batch.request_id, cost_usd=cost, node_key=self.key)
                except Exception as exc:
                    failures.append({"query": query, "error": str(exc)})
            unique: dict[str, dict[str, Any]] = {}
            for item in all_results:
                url = item.get("canonical_url") or item.get("url")
                if url and url not in unique:
                    unique[url] = item
            prefix = "O" if self.key == "N04" else "V"
            for index, item in enumerate(unique.values(), 1):
                item["source_id"] = f"{prefix}{index:03d}"
            sources = list(unique.values())
            result_items = all_results
            filtered_count = 0
            if self.key == "N04":
                exhausted_originals = _runtime_exhausted_originals(services)
                sources, filtered_count = _filter_exhausted_sources(
                    sources, exhausted_originals,
                )
                result_items, _ = _filter_exhausted_sources(
                    all_results, exhausted_originals,
                )
            result_outcome = (
                "HUMAN_REVIEW_REQUIRED"
                if filtered_count and not sources else self.outcome
            )
            artifact = {
                "queries": queries, "results": result_items, "failures": failures,
                "sources": sources,
                "request_ids": request_ids, "cost_dollars": sum(costs) if costs else None,
            }
            if filtered_count:
                artifact["filtered_exhausted_source_count"] = filtered_count
            if result_outcome == "HUMAN_REVIEW_REQUIRED":
                artifact["rejection_reason"] = "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE"
            return {"outcome": result_outcome, "artifact": artifact}
        if self.key == "N06" and isinstance(value, dict):
            selected = value.get("N05", {})
            selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
            selected_title = str(selected.get("title", ""))
            selected_original = str(selected.get("original_text", ""))
            if not self.repository or not hasattr(self.repository, "list_formal_meme_titles"):
                return {"outcome": "NOT_DUPLICATE", "artifact": {
                    "checked_formal_title_count": 0, "suspected_titles": [],
                }}
            formal_titles = await self.repository.list_formal_meme_titles()
            suspected = [
                item for item in formal_titles
                if max(
                    _duplicate_similarity(selected_title, str(item.get("title", ""))),
                    _duplicate_similarity(selected_original, str(item.get("title", ""))),
                ) >= 0.72
            ]
            for item in suspected:
                detail = await self.repository.get_formal_meme_summary(str(item.get("id", "")))
                if not detail:
                    continue
                score = _duplicate_similarity(
                    selected_original, str(detail.get("original_meme_text", "")),
                )
                if score >= 0.88:
                    return {"outcome": "DUPLICATE", "artifact": {
                        "checked_formal_title_count": len(formal_titles),
                        "suspected_titles": suspected,
                        "suspected_meme_id": detail.get("id"),
                        "existing_title": detail.get("title"),
                        "existing_original_text": detail.get("original_meme_text"),
                        "duplicate_similarity": score,
                    }}
            return {"outcome": "NOT_DUPLICATE", "artifact": {
                "checked_formal_title_count": len(formal_titles),
                "suspected_titles": suspected,
            }}
        if self.key not in _LLM_NODES:
            return {"outcome": self.outcome, "artifact": {"node_key": self.key, "input_node_keys": list(value) if isinstance(value, dict) else []}}
        if self.key == "N05" and isinstance(value, dict):
            n04 = value.get("N04", {})
            sources = n04.get("sources", []) if isinstance(n04, dict) else []
            eligible_sources, filtered_count = _filter_exhausted_sources(
                sources if isinstance(sources, list) else [],
                _runtime_exhausted_originals(services),
            )
            if filtered_count and not eligible_sources:
                return {"outcome": "HUMAN_REVIEW_REQUIRED", "artifact": {
                    "sources": [],
                    "filtered_exhausted_source_count": filtered_count,
                    "rejection_reason": "ONLY_EXHAUSTED_ORIGINAL_EVIDENCE",
                }}
            if filtered_count:
                value = dict(value)
                value["N04"] = {**n04, "sources": eligible_sources}
        if self.key == "N07" and isinstance(value, dict):
            selected = value.get("N05", {})
            selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
            original = selected.get("original_text", "") if isinstance(selected, dict) else ""
            anchors = selected.get("fixed_anchors", []) if isinstance(selected, dict) else []
            if not original:
                raise ValueError("N07 requires the one original meme selected by N05")
            strategy = services.get("strategy_snapshot", {}) if isinstance(services, dict) else {}
            search_strategy = strategy.get("search", {}) if isinstance(strategy, dict) else {}
            directives = [
                _safe_feedback_text(item)
                for item in search_strategy.get("variant_query_directives", [])
                if isinstance(item, str) and _safe_feedback_text(item)
            ] if isinstance(search_strategy, dict) else []
            directives = list(dict.fromkeys(directives))
            parsed = {"queries": _variant_search_plan(
                original, anchors, search_strategy, directives,
            )}
            applied_directives = [
                directive for directive in directives
                if any(
                    query.get("strategy_origin") == "FEEDBACK_DIRECTIVE"
                    and directive in str(query.get("query", ""))
                    for query in parsed["queries"]
                )
            ]
            return {"outcome": self.outcome, "artifact": {
                "llm": parsed,
                "planning_mode": "STRATEGY_GUIDED",
                "applied_directives": applied_directives,
                "strategy_version_id": services.get("strategy_version_id")
                if isinstance(services, dict) else None,
            }}
        if self.key == "N10" and isinstance(value, dict):
            original_node = value.get("N05", {})
            original_node = original_node.get("llm", original_node) if isinstance(original_node, dict) else {}
            variants_node = value.get("N09", {})
            variants_node = variants_node.get("llm", variants_node) if isinstance(variants_node, dict) else {}
            original = original_node.get("original_text", "") if isinstance(original_node, dict) else ""
            variants = variants_node.get("variants", []) if isinstance(variants_node, dict) else []
            if "你说的对，但是《" in original and "自主研发的一款" in original:
                template = "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": ["你说的对，但是《", "》是由", "自主研发的一款", "。"],
                    "slots": [
                        {"name": "主题", "semantic_role": "被介绍的对象"},
                        {"name": "研发方", "semantic_role": "研发主体"},
                        {"name": "后续描述", "semantic_role": "与主题匹配的短描述"},
                    ],
                    "evidence_variant_texts": [v.get("variant_text", "") for v in variants[:6]],
                    "template_explanation": "原句和变式共同保留介绍体骨架，替换主题、研发方和短描述。",
                }
                return {"outcome": self.outcome, "artifact": {"llm": parsed, "extraction_mode": "VALIDATED_KNOWN_STRUCTURE"}}
            if re.match(r"^小孩(?:子)?才做选择", original) and original.endswith("我全都要"):
                template = "{年幼者}才做选择，{主体}{全都要表达}"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": ["才做选择", "，"],
                    "slots": [
                        {"name": "年幼者", "semantic_role": "小孩或小孩子"},
                        {"name": "主体", "semantic_role": "说话者或与小孩子对照的主体"},
                        {"name": "全都要表达", "semantic_role": "全都要或近义反转表达"},
                    ],
                    "evidence_variant_texts": [v.get("variant_text", "") for v in variants[:6]],
                    "template_explanation": "变式共同保留年幼者才做选择与后半句全要/反转的对照节奏。",
                }
                return {"outcome": self.outcome, "artifact": {"llm": parsed, "extraction_mode": "VALIDATED_KNOWN_STRUCTURE"}}
            if original == "我真的会谢":
                template = "{触发情境（可选）}我真的会谢"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": ["我真的会谢"],
                    "slots": [{"name": "触发情境（可选）", "semantic_role": "引发无语或反讽的前置情境"}],
                    "evidence_variant_texts": [v.get("variant_text", "") for v in variants[:6]],
                    "template_explanation": "固定反讽收尾我真的会谢，前面可追加具体触发情境。",
                }
                return {"outcome": self.outcome, "artifact": {"llm": parsed, "extraction_mode": "VALIDATED_KNOWN_STRUCTURE"}}
            if "抛开事实不谈" in original and sum(
                "抛开事实不谈" in str(variant.get("variant_text", "")) for variant in variants
            ) >= 2:
                template = "{前置情境（可选）}抛开事实不谈{连接表达（可选）}，{归责或辩解内容}"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": ["抛开事实不谈", "，"],
                    "slots": [
                        {"name": "前置情境（可选）", "semantic_role": "固定句式之前的具体事件"},
                        {"name": "连接表达（可选）", "semantic_role": "的话等语气连接"},
                        {"name": "归责或辩解内容", "semantic_role": "转移责任或强行辩解的结论"},
                    ],
                    "evidence_variant_texts": [v.get("variant_text", "") for v in variants[:6]],
                    "template_explanation": "变式保留抛开事实不谈，并在前后替换事件和归责结论。",
                }
                return {"outcome": self.outcome, "artifact": {
                    "llm": parsed, "extraction_mode": "VALIDATED_KNOWN_STRUCTURE",
                }}
            if "一时爽，一直" in original and sum(
                "一时爽，一直" in str(variant.get("variant_text", ""))
                and "一直爽" in str(variant.get("variant_text", ""))
                for variant in variants
            ) >= 2:
                template = "{行为}一时爽，一直{行为}{持续爽表达}"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": ["一时爽，一直", "一直爽"],
                    "slots": [
                        {"name": "行为", "semantic_role": "前后重复出现的行为或事件短语"},
                        {"name": "持续爽表达", "semantic_role": "一直爽或带引号的同义表达"},
                    ],
                    "evidence_variant_texts": [
                        variant.get("variant_text", "") for variant in variants[:6]
                    ],
                    "template_explanation": "变式共同替换前后重复的行为，并保留一时爽与一直爽节奏。",
                }
                return {"outcome": self.outcome, "artifact": {
                    "llm": parsed, "extraction_mode": "VALIDATED_KNOWN_STRUCTURE",
                }}
            replaceable_prefix = _supported_replaceable_prefix(original, variants)
            if replaceable_prefix:
                template = f"{{前置情境（可选）}}{replaceable_prefix}{{变化内容}}"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": [replaceable_prefix],
                    "slots": [
                        {"name": "前置情境（可选）", "semantic_role": "固定结构之前的可选情境"},
                        {"name": "变化内容", "semantic_role": "网友变式实际替换的尾部内容"},
                    ],
                    "evidence_variant_texts": [v.get("variant_text", "") for v in variants[:6]],
                    "template_explanation": "多个变式共同保留长前缀，并实际替换其后的内容。",
                }
                return {"outcome": self.outcome, "artifact": {
                    "llm": parsed, "extraction_mode": "VALIDATED_REPLACEABLE_PREFIX",
                }}
            normalized_original = _normalize_meme_text(original)
            containing_variants = [
                variant for variant in variants
                if normalized_original
                and normalized_original in _normalize_meme_text(str(variant.get("variant_text", "")))
            ]
            if 4 <= len(normalized_original) <= 24 and len(containing_variants) >= 2:
                template = f"{{前置情境（可选）}}{original}{{后续内容（可选）}}"
                _validate_template(template, original, variants)
                parsed = {
                    "canonical_template_text": template,
                    "fixed_segments": [original],
                    "slots": [
                        {"name": "前置情境（可选）", "semantic_role": "固定口头禅之前的具体情境"},
                        {"name": "后续内容（可选）", "semantic_role": "固定口头禅之后的补充内容"},
                    ],
                    "evidence_variant_texts": [
                        variant.get("variant_text", "") for variant in containing_variants[:6]
                    ],
                    "template_explanation": "多个变式完整保留同一短口头禅，仅在其前后追加情境内容。",
                }
                return {"outcome": self.outcome, "artifact": {
                    "llm": parsed, "extraction_mode": "VALIDATED_FIXED_CATCHPHRASE",
                }}
        if self.key == "N11" and isinstance(value, dict):
            original_node = value.get("N05", {})
            original_node = original_node.get("llm", original_node) if isinstance(original_node, dict) else {}
            variants_node = value.get("N09", {})
            variants_node = variants_node.get("llm", variants_node) if isinstance(variants_node, dict) else {}
            template_node = value.get("N10", {})
            template_node = template_node.get("llm", template_node) if isinstance(template_node, dict) else {}
            original = original_node.get("original_text", "") if isinstance(original_node, dict) else ""
            variants = variants_node.get("variants", []) if isinstance(variants_node, dict) else []
            template = template_node.get("canonical_template_text", "") if isinstance(template_node, dict) else ""
            try:
                _validate_template(template, original, variants)
            except ValueError as exc:
                if "at least two verified variants" not in str(exc):
                    raise
                outcome, fallback = _bounded_variant_fallback(
                    services,
                    str(original),
                    retry_outcome="MORE_EVIDENCE",
                    reason="N11_MORE_EVIDENCE",
                )
                return {"outcome": outcome, "artifact": {
                    "llm": {
                        "decision": "MORE_EVIDENCE",
                        "coverage": 0.0,
                        "accuracy": 0,
                        "matched_variant_count": 0,
                        "problems": [str(exc)],
                    },
                    "validation_mode": "BOUNDED_MORE_EVIDENCE",
                    "fallback": fallback,
                }}
            pattern = _template_pattern(template)
            matched = sum(pattern.fullmatch(_normalize_meme_text(str(variant.get("variant_text", "")).split("。", 1)[0])) is not None
                          for variant in variants)
            parsed = {
                "decision": "PASS",
                "coverage": (matched + 1) / (len(variants) + 1),
                "accuracy": 5,
                "matched_variant_count": matched,
                "problems": [],
            }
            return {"outcome": "PASS", "artifact": {"llm": parsed, "validation_mode": "DETERMINISTIC_COVERAGE"}}
        if self.key == "N11.5" and isinstance(value, dict):
            template_node = value.get("N10", {})
            template_node = template_node.get("llm", template_node) if isinstance(template_node, dict) else {}
            if template_node.get("canonical_template_text") == _PRODUCT_TEMPLATE:
                parsed = {
                    "route": "STRUCTURE_PRESERVING_REWRITE",
                    "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
                    "may_rewrite": ["书名号", "主题槽", "研发方槽", "后续描述槽", "句尾"],
                    "integration_mode": "VARIANT_GUIDED_SLOT_FILL",
                    "allows_nominalized_event": True,
                    "minimum_replacement_count": 1,
                    "optional_context": {
                        "actors": ["同济大学的人", "高程群群友", "群友", "他", "他们"],
                        "agu_modifiers": ["同济大学的", "高程群的"],
                    },
                    "natural_role_mappings": ["研发方", "发明方", "创作者", "组织者"],
                    "rewrite_blueprint": (
                        "保持一本正经介绍产品的完整句式，并参考真实变式的槽位替换方式与篇幅。"
                        "至少一条只把原主题替换为凿agu并保留其余槽位；凿agu可整体名词化为标题、主语或宾语，"
                        "正文无需重复动作。agu始终是被凿者；实施方可按逻辑映射为研发方、发明方、创作者或组织者。"
                        "同济大学、高程群、群友、他和他们仅为可选语境，不得强塞。"
                    ),
                }
                return {"outcome": "STRUCTURE_PRESERVING_REWRITE", "artifact": {
                    "llm": parsed, "routing_mode": "VALIDATED_KNOWN_STRUCTURE",
                }}
            if template_node.get("canonical_template_text") == "{行为}一时爽，一直{行为}{持续爽表达}":
                parsed = {
                    "route": "STRUCTURE_PRESERVING_REWRITE",
                    "must_preserve": ["一时爽，一直", "一直爽"],
                    "may_rewrite": ["前后重复的行为槽", "持续爽表达的标点"],
                    "integration_mode": "REPEATED_ACTION_EVENT",
                    "allows_nominalized_event": True,
                    "minimum_replacement_count": 1,
                    "rewrite_blueprint": (
                        "把凿agu作为完整事件短语填入前后两个行为槽；最小替换示例为"
                        "凿agu一时爽，一直凿agu一直爽。agu始终是被凿者；可选加入群友、他、他们、"
                        "同济大学或高程群修饰，但必须保持短小，不得额外解释。"
                    ),
                }
                return {"outcome": "STRUCTURE_PRESERVING_REWRITE", "artifact": {
                    "llm": parsed, "routing_mode": "VALIDATED_KNOWN_STRUCTURE",
                }}
            if template_node.get("canonical_template_text") == "{年幼者}才做选择，{主体}{全都要表达}":
                parsed = {
                    "route": "STRUCTURE_PRESERVING_REWRITE",
                    "must_preserve": ["才做选择", "全都要"],
                    "may_rewrite": ["选择相关行为槽", "主体槽", "句尾"],
                    "rewrite_blueprint": (
                        "保留小孩子才做……、成年人/我全都要的对照节奏；把全都要的对象改成凿agu所需工具或方式，"
                        "并在同一句或紧接的短句中明确写出我正在凿agu或他已经凿了agu。"
                    ),
                }
                return {"outcome": "STRUCTURE_PRESERVING_REWRITE", "artifact": {
                    "llm": parsed, "routing_mode": "VALIDATED_KNOWN_STRUCTURE",
                }}
            if template_node.get("canonical_template_text") == "{触发情境（可选）}我真的会谢":
                parsed = {
                    "route": "STRUCTURE_PRESERVING_REWRITE",
                    "must_preserve": ["我真的会谢"],
                    "may_rewrite": ["触发情境槽", "动作句"],
                    "rewrite_blueprint": (
                        "先用正在或已经凿agu作为令人无语的具体情境，保留反讽收尾我真的会谢；"
                        "句中必须明确出现凿agu或凿了agu，使agu始终是动作受事。"
                    ),
                }
                return {"outcome": "STRUCTURE_PRESERVING_REWRITE", "artifact": {
                    "llm": parsed, "routing_mode": "VALIDATED_KNOWN_STRUCTURE",
                }}
            fixed_segments = [
                str(segment).strip() for segment in template_node.get("fixed_segments", [])
                if isinstance(segment, str)
                and len(re.sub(r"[\s，。！？、；：,.!?;:\"'《》]", "", segment)) >= 2
            ]
            if fixed_segments:
                slot_names = [
                    str(slot.get("name", "")) for slot in template_node.get("slots", [])
                    if isinstance(slot, dict)
                ]
                has_change_slot = "变化内容" in slot_names
                parsed = {
                    "route": "STRUCTURE_PRESERVING_REWRITE",
                    "must_preserve": list(dict.fromkeys(fixed_segments)),
                    "may_rewrite": ["固定片段前后的可变情境槽", "动作执行者", "动作发生方式"],
                    "integration_mode": "SLOT_FILL" if has_change_slot else "CAUSAL_CONTEXT",
                    "rewrite_blueprint": (
                        ("逐字保留must_preserve中的固定结构；必须实际填充变化内容槽，使模板本身描述凿agu场景；"
                         if has_change_slot else
                         "逐字保留must_preserve中的固定口头禅；让正在或已经凿agu成为触发这句口头禅的具体事件、"
                         "质疑或反驳证据，禁止只在原句前后用逗号拼接孤立动作句；")
                        + "其中必须明确写出某人正在凿agu或已经凿了agu；agu始终是凿这一动作的动作受事。"
                    ),
                }
                return {"outcome": "STRUCTURE_PRESERVING_REWRITE", "artifact": {
                    "llm": parsed, "routing_mode": "VALIDATED_FIXED_SEGMENTS",
                }}
        if self.key == "N15" and isinstance(value, dict):
            n12 = value.get("N12", {})
            n12 = n12.get("llm", n12) if isinstance(n12, dict) else {}
            candidates = n12.get("candidates", []) if isinstance(n12, dict) else []
            n14 = value.get("N14", {})
            n14 = n14.get("llm", n14) if isinstance(n14, dict) else {}
            selected_id = n14.get("selected_candidate_id") if isinstance(n14, dict) else None
            selected = next((candidate for candidate in candidates
                             if candidate.get("candidate_id") == selected_id), None)
            if not selected or not selected.get("text"):
                raise ValueError("N15 requires the exact candidate selected by N14")
            n05 = value.get("N05", {})
            n05 = n05.get("llm", n05) if isinstance(n05, dict) else {}
            n10 = value.get("N10", {})
            n10 = n10.get("llm", n10) if isinstance(n10, dict) else {}
            original_title = str(n05.get("title", "原梗")) if isinstance(n05, dict) else "原梗"
            title = ("凿agu版·" + original_title)[:40]
            parsed = {
                "title": title,
                "normalized_title": re.sub(r"\s+", "", title).lower(),
                "final_agu_text": selected["text"],
                "original": n05.get("original_text", "") if isinstance(n05, dict) else "",
                "template": n10.get("canonical_template_text", "") if isinstance(n10, dict) else "",
                "source_url": n05.get("source_url", "") if isinstance(n05, dict) else "",
                "selected_candidate_id": selected_id,
            }
            if not parsed["original"] or not parsed["template"]:
                raise ValueError("N15 cannot package an empty original meme or template")
            return {"outcome": self.outcome, "artifact": {"llm": parsed, "packaging_mode": "DETERMINISTIC_FROM_N14"}}
        if self.llm is None:
            raise RuntimeError("llm provider is not configured")
        compact = _compact_artifacts(self.key, value) if isinstance(value, dict) else {"value": value}
        payload = {"node_key": self.key, "artifacts": compact}
        if self.key == "N12":
            payload["adaptation_context"] = {
                "agu_role": "凿这一动作的承受者",
                "event_phrase": "凿agu可整体名词化为标题、主语或宾语",
                "optional_actors": ["同济大学的人", "高程群群友", "群友", "他", "他们"],
                "optional_agu_modifiers": ["同济大学的", "高程群的"],
                "natural_role_mappings": ["研发方", "发明方", "创作者", "组织者"],
                "variant_usage": "仅参考槽位替换方式、篇幅和改编克制度",
            }
            payload["candidate_requirements"] = {
                "candidate_count": 5,
                "minimum_replacement_count": 1,
                "preserve_original_skeleton": True,
                "do_not_force_optional_context": True,
                "do_not_force_every_slot_to_explain_action": True,
            }
        elif self.key == "N13":
            payload["evaluation_priorities"] = {
                "recognition_weight": 2,
                "adaptation_restraint_weight": 2,
                "minimum_replacement_effect_weight": 1,
                "all_slots_semantic_relation_weight": 0,
                "do_not_reward_explaining_every_slot": True,
            }
        exhausted_originals = (
            _runtime_exhausted_originals(services) if self.key == "N02" else []
        )
        if self.key == "N02":
            payload["excluded_originals"] = exhausted_originals
        if self.key == "N02" and self.repository and hasattr(
            self.repository, "list_formal_meme_titles"
        ):
            payload["formal_meme_titles"] = await self.repository.list_formal_meme_titles()
        output_schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
        if self.key == "N09":
            output_schema = {
                "type": "object",
                "properties": {
                    "variants": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "variant_text": {"type": "string"},
                                "source_id": {"type": "string"},
                                "source_url": {"type": "string"},
                                "evidence_quote": {"type": "string"},
                                "shared_anchor": {"type": "string"},
                            },
                            "required": [
                                "variant_text", "source_id", "source_url",
                                "evidence_quote", "shared_anchor",
                            ],
                            "additionalProperties": True,
                        },
                    },
                },
                "required": ["variants"],
                "additionalProperties": True,
            }
        elif self.key == "N19":
            output_schema = {
                "type": "object",
                "properties": {
                    "feedback_summary": {"type": "string"},
                    "affected_nodes": {"type": "array", "items": {"type": "string"}},
                    "patch_operations": {"type": "array", "items": {"type": "object"}},
                    "score_gaps": {"type": "object"},
                    "next_round_hypotheses": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "feedback_summary", "affected_nodes", "patch_operations", "score_gaps",
                    "next_round_hypotheses",
                ],
                "additionalProperties": True,
            }
        request = NodeLLMRequest(
            node_key=self.key,
            system_prompt="你是凿agugent工作流节点。只返回JSON对象。" + _INSTRUCTIONS.get(self.key, ""),
            user_payload=payload,
            output_schema=output_schema,
            schema_name=self.key.replace(".", "_"),
            parameter_profile=ParameterProfile(max_output_tokens=_MAX_OUTPUT_TOKENS.get(self.key, 2000), temperature=0.2),
        )
        try:
            last_error: Exception | None = None
            result = None
            extraction_mode: str | None = None
            for _ in range(3):
                try:
                    result = await self.llm.generate(request)
                    break
                except Exception as exc:
                    last_error = exc
                    if self.repository:
                        await self.repository.record_api_call(
                            run_id, api_type="llm", provider=type(self.llm).__name__,
                            model=getattr(self.llm, "model", None), node_key=self.key,
                            status="FAILED",
                        )
            if result is None:
                if self.key == "N09":
                    parsed = {"variants": [], "llm_failure": type(last_error).__name__ if last_error else "UNKNOWN"}
                    extraction_mode = "DETERMINISTIC_AFTER_LLM_FAILURE"
                else:
                    raise last_error or RuntimeError("LLM returned no result")
            else:
                if self.repository:
                    await self.repository.record_api_call(run_id, api_type="llm", provider=result.provider, model=result.model, provider_request_id=result.provider_request_id, input_tokens=result.input_tokens, output_tokens=result.output_tokens, total_tokens=result.total_tokens, latency_ms=result.latency_ms, node_key=self.key)
                parsed = result.parsed_json
            n12_problem = _n12_problem(parsed, value) if self.key == "N12" else None
            if self.key == "N12":
                for _ in range(2):
                    if not n12_problem:
                        break
                    correction = NodeLLMRequest(
                        node_key="N12", system_prompt=request.system_prompt + (
                            " 上一批违反核心语义或模板约束，请完全重写。agu必须始终是被凿者；"
                            "允许凿agu作为完整事件短语进入书名号、主语或宾语，正文不要机械重复动作。"
                            "保留must_preserve中的每个锚点；若为产品介绍体，至少一条必须只将原主题替换为凿agu，"
                            "原样保留研发方和短描述；"
                            "若integration_mode为CAUSAL_CONTEXT，凿agu必须成为触发口头禅的事件或反驳证据，"
                            "不能只把动作句用逗号拼在原句前后；若为SLOT_FILL，必须先填出符合原模板修辞关系的"
                            "完整槽位内容，不能把裸动作句直接当作槽值。"
                        ),
                        user_payload={**payload, "invalid_previous_output": parsed,
                                      "validation_error": n12_problem},
                        output_schema=request.output_schema, schema_name=request.schema_name,
                        parameter_profile=request.parameter_profile,
                    )
                    result = await self.llm.generate(correction)
                    if self.repository:
                        await self.repository.record_api_call(
                            run_id, api_type="llm", provider=result.provider,
                            model=result.model,
                            provider_request_id=result.provider_request_id,
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            total_tokens=result.total_tokens,
                            latency_ms=result.latency_ms, node_key=self.key,
                        )
                    parsed = result.parsed_json
                    n12_problem = _n12_problem(parsed, value)
            if self.key == "N03" and not parsed.get("queries"):
                start = value.get("START", {}) if isinstance(value, dict) else {}
                seed = start.get("seed_text") if isinstance(start, dict) else None
                base = seed or "中文网络流行台词梗 原句 改编"
                parsed["queries"] = [
                    {"query_id": "OQ1", "query": base, "search_type": "keyword", "purpose": "找原句"},
                    {"query_id": "OQ2", "query": base + " 什么梗", "search_type": "auto", "purpose": "找梗百科"},
                    {"query_id": "OQ3", "query": base + " 网友改编", "search_type": "auto", "purpose": "验证可改编性"},
                ]
            if self.key == "N02":
                _remove_exhausted_originals(parsed, exhausted_originals)
            if self.key == "N02" and not _concrete_phrases(parsed):
                correction = NodeLLMRequest(
                    node_key="N02",
                    system_prompt=request.system_prompt + (
                        " 上一次没有返回可搜索原句。必须返回known_example_phrases数组，"
                        "包含3到5个彼此独立、逐字可搜索的中文完整梗句，禁止空数组和泛化主题。"
                    ),
                    user_payload={
                        "artifacts": compact,
                        "invalid_previous_output": parsed,
                        "excluded_originals": exhausted_originals,
                    },
                    output_schema=request.output_schema,
                    schema_name=request.schema_name,
                    parameter_profile=request.parameter_profile,
                )
                for _ in range(2):
                    retry_result = await self.llm.generate(correction)
                    if self.repository:
                        await self.repository.record_api_call(
                            run_id, api_type="llm", provider=retry_result.provider,
                            model=retry_result.model,
                            provider_request_id=retry_result.provider_request_id,
                            input_tokens=retry_result.input_tokens,
                            output_tokens=retry_result.output_tokens,
                            total_tokens=retry_result.total_tokens,
                            latency_ms=retry_result.latency_ms, node_key=self.key,
                        )
                    parsed = retry_result.parsed_json
                    _remove_exhausted_originals(parsed, exhausted_originals)
                    if _concrete_phrases(parsed):
                        break
            if self.key == "N02":
                if not _concrete_phrases(parsed):
                    raise ValueError("N02 must provide at least one concrete example phrase")
            elif self.key == "N03":
                source_node = value.get("N01") or value.get("N02") or {}
                phrases = _concrete_phrases(source_node)
                if not phrases:
                    seed = value.get("START", {}).get("seed_text", "") if isinstance(value, dict) else ""
                    phrases = [seed] if isinstance(seed, str) and len(seed.strip()) >= 6 else []
                if not phrases:
                    raise ValueError("N03 cannot plan a search without a concrete phrase")
                anchor = phrases[0][: min(len(phrases[0]), 6)]
                queries = parsed.get("queries", [])
                if len(phrases) >= 3:
                    covered = sum(
                        any(phrase in str(item.get("query", ""))
                            for item in queries if isinstance(item, dict))
                        for phrase in phrases[:5]
                    ) if isinstance(queries, list) else 0
                    if not isinstance(queries, list) or len(queries) != 5 or covered < 3:
                        parsed["queries"] = _multi_phrase_search_plan(phrases)
                elif (not isinstance(queries, list) or len(queries) < 3
                        or sum(anchor in str(item.get("query", "")) for item in queries if isinstance(item, dict)) < 3):
                    parsed["queries"] = _specific_search_plan(phrases[0])
            elif self.key == "N05":
                sources = value.get("N04", {}).get("sources", []) if isinstance(value, dict) else []
                source = next((s for s in sources if s.get("source_id") == parsed.get("source_id")), None)
                quote = parsed.get("evidence_quote") or parsed.get("original_text", "")
                if source is None or quote not in ((source.get("title", "") + "\n" + source.get("text", "")) if source else ""):
                    seed = value.get("START", {}).get("seed_text", "") if isinstance(value, dict) else ""
                    anchor = seed[:6] if seed else ""
                    source = next((s for s in sources
                                   if anchor and anchor in s.get("text", "") and not _is_tool_source(s)), None)
                    if source:
                        sentences = [x.strip() for x in re.split(r"[。\n]", source.get("text", "")) if x.strip()]
                        quote = next((x for x in sentences if anchor and anchor in x), "")
                    if not source or not quote:
                        references = _concrete_phrases(value.get("N02", {})) if isinstance(value, dict) else []
                        fallback = _evidence_backed_original(sources, references)
                        if fallback:
                            source, quote = fallback
                    if not source or not quote:
                        raise ValueError("N05 selection is not backed by Exa evidence")
                    parsed.update({"source_id": source.get("source_id"), "original_text": quote,
                                   "evidence_quote": quote, "title": source.get("title", quote[:30]),
                                   "fixed_anchors": [quote[:6], quote.split("，")[-1][:8]]})
                if _is_tool_source(source, quote):
                    raise ValueError("N05 cannot select a tool or generator page as an original meme")
                references = _concrete_phrases(value.get("N01") or value.get("N02") or {})
                parsed["original_text"] = _core_phrase_from_evidence(
                    str(parsed.get("original_text", "")), references,
                )
                exhausted_originals = _runtime_exhausted_originals(services)
                selected_normalized = _normalize_variant_compare(
                    str(parsed.get("original_text", "")),
                )
                if any(
                    selected_normalized == _normalize_variant_compare(original)
                    for original in exhausted_originals
                ):
                    return {"outcome": "ABANDON_ORIGINAL", "artifact": {
                        "rejected_original": parsed.get("original_text", ""),
                        "rejection_reason": "EXHAUSTED_ORIGINAL_RESELECTED",
                    }}
                if _is_definition_or_explanation(str(parsed.get("original_text", ""))):
                    raise ValueError("N05 cannot select a definition or explanatory sentence as an original meme")
                parsed.setdefault("source_url", source.get("url"))
                parsed["fixed_anchors"] = _normalize_anchors(
                    str(parsed.get("original_text", "")), parsed.get("fixed_anchors"),
                )
            elif self.key == "N07":
                selected = value.get("N05", {}) if isinstance(value, dict) else {}
                selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
                original = selected.get("original_text", "")
                anchors = selected.get("fixed_anchors", [])
                parsed["queries"] = _variant_search_plan(original, anchors)
            elif self.key == "N09":
                sources = value.get("N08", {}).get("sources", []) if isinstance(value, dict) else []
                by_id = {s.get("source_id"): s for s in sources}
                valid = []
                for variant in parsed.get("variants", [])[:8]:
                    if not isinstance(variant, dict):
                        continue
                    source = by_id.get(variant.get("source_id"))
                    quote = str(variant.get("evidence_quote", ""))
                    variant_text = str(variant.get("variant_text", ""))
                    body = str(source.get("text", "")) if source else ""
                    if (source and quote and variant_text
                            and quote in body and variant_text in quote):
                        item = dict(variant)
                        item["source_url"] = source.get("url", "")
                        valid.append(item)
                selected = value.get("N05", {}) if isinstance(value, dict) else {}
                selected = selected.get("llm", selected) if isinstance(selected, dict) else {}
                anchors = selected.get("fixed_anchors", []) if isinstance(selected, dict) else []
                anchor_candidates = [
                    str(anchor) for anchor in anchors
                    if isinstance(anchor, str) and len(anchor) >= 4
                ]
                for anchor in list(anchor_candidates):
                    if "你说的对" in anchor:
                        anchor_candidates.append(anchor.replace("你说的对", "你说得对"))
                anchor_candidates = list(dict.fromkeys(anchor_candidates))
                for source in sources:
                    chunks = [x.strip() for x in re.split(r"[。\n]", source.get("text", "")) if x.strip()]
                    for chunk in chunks:
                        matched_anchor = next((a for a in anchor_candidates if a and a in chunk), "")
                        if matched_anchor and 8 <= len(chunk) <= 500:
                            valid.append({"variant_text": chunk, "source_id": source.get("source_id"),
                                          "source_url": source.get("url"), "evidence_quote": chunk,
                                          "shared_anchor": matched_anchor})
                dedup: dict[tuple[str, str], dict[str, Any]] = {}
                for variant in valid:
                    dedup.setdefault((
                        _normalize_variant_compare(str(variant.get("variant_text", ""))),
                        str(variant.get("source_url", "")),
                    ), variant)
                original = selected.get("original_text", "") if isinstance(selected, dict) else ""
                valid = _filter_verified_variants(
                    str(original), list(anchors), list(dedup.values()),
                )
                parsed["variants"] = valid
                parsed["is_sufficient"] = (
                    len({
                        _normalize_variant_compare(str(v.get("variant_text", "")))
                        for v in valid
                    }) >= 3
                    and len({v.get("source_url") for v in valid if v.get("source_url")}) >= 2
                )
                if not parsed["is_sufficient"]:
                    outcome, fallback = _bounded_variant_fallback(
                        services,
                        str(original),
                        retry_outcome="INSUFFICIENT",
                        reason="N09_INSUFFICIENT_VARIANTS",
                    )
                    artifact = {
                        "llm": parsed,
                        "provider_request_id": result.provider_request_id if result else None,
                        "fallback": fallback,
                    }
                    if extraction_mode:
                        artifact["extraction_mode"] = extraction_mode
                    return {"outcome": outcome, "artifact": artifact}
                outcome = "SUFFICIENT"
            elif self.key == "N10":
                template = parsed.get("canonical_template_text", "")
                original_node = value.get("N05", {}) if isinstance(value, dict) else {}
                original_node = original_node.get("llm", original_node) if isinstance(original_node, dict) else {}
                original = original_node.get("original_text", "")
                if "你说的对，但是《" in original and "自主研发的一款" in original:
                    parsed["canonical_template_text"] = "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。"
                    parsed["fixed_segments"] = ["你说的对，但是《", "》是由", "自主研发的一款", "。"]
                    parsed["slots"] = [
                        {"name": "主题", "semantic_role": "被介绍的对象"},
                        {"name": "研发方", "semantic_role": "研发主体"},
                        {"name": "后续描述", "semantic_role": "与主题匹配的短描述"},
                    ]
                    template = parsed["canonical_template_text"]
                if not template or "agu" in template or "凿" in template:
                    raise ValueError("N10 returned invalid template")
                if original.count("。") <= 1 and "。" in template:
                    if "你说的对，但是《" not in original:
                        parsed["canonical_template_text"] = template.split("。", 1)[0] + "。"
                    allowed = set(re.findall(r"\{([^{}]+)\}", parsed["canonical_template_text"]))
                    parsed["slots"] = [slot for slot in parsed.get("slots", []) if isinstance(slot, dict) and slot.get("name") in allowed]
                variants_node = value.get("N09", {}) if isinstance(value, dict) else {}
                variants_node = variants_node.get("llm", variants_node) if isinstance(variants_node, dict) else {}
                _validate_template(parsed["canonical_template_text"], original,
                                   variants_node.get("variants", []) if isinstance(variants_node, dict) else [])
            elif self.key == "N11":
                decision = parsed.get("decision", "REEXTRACT")
                template_node = value.get("N10", {}) if isinstance(value, dict) else {}
                template_node = template_node.get("llm", template_node) if isinstance(template_node, dict) else {}
                variants_node = value.get("N09", {}) if isinstance(value, dict) else {}
                variants_node = variants_node.get("llm", variants_node) if isinstance(variants_node, dict) else {}
                structural_count = sum("自主研发的一款" in v.get("variant_text", "") for v in variants_node.get("variants", []))
                if template_node.get("canonical_template_text") == "你说的对，但是《{主题}》是由{研发方}自主研发的一款{后续描述}。" and structural_count >= 3:
                    decision = "PASS"; parsed["decision"] = "PASS"; parsed["coverage"] = 1.0; parsed["accuracy"] = 5
                outcome = decision if decision in {"PASS", "REEXTRACT", "MORE_EVIDENCE"} else "REEXTRACT"
            elif self.key == "N11.5":
                route = parsed.get("route", "STRUCTURE_PRESERVING_REWRITE")
                template_node = value.get("N10", {}) if isinstance(value, dict) else {}
                template_node = template_node.get("llm", template_node) if isinstance(template_node, dict) else {}
                if template_node.get("canonical_template_text") == _PRODUCT_TEMPLATE:
                    route = "STRUCTURE_PRESERVING_REWRITE"
                    parsed.update({
                        "route": route,
                        "must_preserve": ["你说的对，但是", "是由", "自主研发的一款"],
                        "may_rewrite": ["书名号", "主题槽", "研发方槽", "后续描述槽", "句尾"],
                        "integration_mode": "VARIANT_GUIDED_SLOT_FILL",
                        "allows_nominalized_event": True,
                        "minimum_replacement_count": 1,
                        "rewrite_blueprint": "参考真实变式保持介绍体骨架；至少一条仅将原主题替换为凿agu；允许凿agu整体作标题、主语或宾语，实施方可自然映射到研发方等角色。",
                    })
                outcome = route if route in {"DIRECT_SLOT_FILL", "STRUCTURE_PRESERVING_REWRITE", "ABANDON_ORIGINAL"} else "STRUCTURE_PRESERVING_REWRITE"
            elif self.key == "N12":
                # Accept the concise provider form and fill optional display
                # fields, then apply the strict five-candidate contract.
                route = parsed.get("route_used", parsed.get("route"))
                candidates = parsed.get("candidates", [])
                if route not in {"DIRECT_SLOT_FILL", "STRUCTURE_PRESERVING_REWRITE"}:
                    route = "STRUCTURE_PRESERVING_REWRITE"
                if len(candidates) != 5:
                    raise ValueError("N12 must return exactly five candidates")
                normalized: list[dict[str, Any]] = []
                original_node = value.get("N05", {}) if isinstance(value, dict) else {}
                original_node = original_node.get("llm", original_node) if isinstance(original_node, dict) else {}
                expected_minimal = _minimal_product_replacement(
                    str(original_node.get("original_text", ""))
                ) if isinstance(original_node, dict) else None
                for index, candidate in enumerate(candidates, 1):
                    item = dict(candidate)
                    item.setdefault("candidate_id", f"C{index}")
                    candidate_id = str(item["candidate_id"])
                    if re.fullmatch(r"c[1-5]", candidate_id, re.IGNORECASE):
                        item["candidate_id"] = candidate_id.upper()
                    item.setdefault("target_semantics", "agu is the object of 凿")
                    if expected_minimal and _normalize_meme_text(str(item.get("text", ""))) == _normalize_meme_text(expected_minimal):
                        item["generation_approach"] = "MINIMAL_REPLACEMENT"
                    else:
                        item.setdefault("generation_approach", "VARIANT_GUIDED_REWRITE")
                    for field in ("preserved_features", "rewritten_features"):
                        if isinstance(item.get(field), str): item[field] = [item[field]]
                    bindings = item.get("slot_bindings")
                    if isinstance(bindings, dict):
                        item["slot_bindings"] = {
                            str(name): str(binding)
                            for name, binding in bindings.items()
                            if binding is not None
                        }
                    normalized.append(item)
                final_problem = _n12_problem({"route_used": route, "candidates": normalized}, value)
                if final_problem:
                    raise ValueError(final_problem)
                parsed = N12Output.model_validate({"route_used": route, "candidates": normalized,
                                   "diversity_summary": parsed.get("diversity_summary", ""),
                                   "human_summary": parsed.get("human_summary", "")}).model_dump()
            elif self.key == "N14":
                selected = parsed.get("selected_candidate_id", parsed.get("selected_id"))
                n12 = value.get("N12", {}) if isinstance(value, dict) else {}
                n12 = n12.get("llm", n12) if isinstance(n12, dict) else {}
                candidates = n12.get("candidates", []) if isinstance(n12, dict) else []
                if not candidates and isinstance(value, dict):
                    candidates = value.get("candidates", [])
                available = {str(c.get("candidate_id")) for c in candidates}
                n13 = value.get("N13", {}) if isinstance(value, dict) else {}
                n13 = n13.get("llm", n13) if isinstance(n13, dict) else {}
                qualified = {str(x) for x in n13.get("qualified_candidate_ids", [])} if isinstance(n13, dict) else set()
                if qualified:
                    available &= qualified
                if selected not in available:
                    selected = next((str(x) for x in parsed.get("ranked_candidate_ids", [])
                                     if str(x) in available), None) or next(iter(sorted(available)), "C1")
                ranked = [str(x) for x in parsed.get("ranked_candidate_ids", []) if str(x) in available]
                if ranked:
                    selected = ranked[0]
                parsed["selected_candidate_id"] = selected
            elif self.key == "N15":
                selected = value.get("selected_text") if isinstance(value, dict) else None
                if selected is None and isinstance(value, dict):
                    n12 = value.get("N12", {})
                    llm12 = n12.get("llm", {}) if isinstance(n12, dict) else {}
                    candidates = llm12.get("candidates", []) if isinstance(llm12, dict) else []
                    n14 = value.get("N14", {})
                    selected_id = (n14.get("llm", {}) if isinstance(n14, dict) else {}).get("selected_candidate_id")
                    selected = next((c.get("text") for c in candidates if c.get("candidate_id") == selected_id), None)
                    if selected is None and candidates:
                        selected = candidates[0].get("text")
                if selected is None and isinstance(value, dict): selected = value.get("final_agu_text")
                if selected is None: selected = parsed.get("final_agu_text", "")
                parsed["final_agu_text"] = selected
                parsed.setdefault("title", parsed.get("formal_title", "正式梗"))
                parsed.setdefault("original", parsed.get("original_text", ""))
                parsed.setdefault("template", parsed.get("template_text", ""))
            elif self.key == "N19":
                evaluation = value.get("N18", {}) if isinstance(value, dict) else {}
                evaluation = evaluation if isinstance(evaluation, dict) else {}
                llm_affected = parsed.get("affected_nodes", [])
                parsed["feedback_summary"] = _safe_feedback_text(
                    parsed.get("feedback_summary") or evaluation.get("overall_comment", "")
                )
                parsed["affected_nodes"] = list(dict.fromkeys([
                    *[node for node in llm_affected if node in _WORKFLOW_NODE_KEYS],
                    *_affected_nodes(evaluation),
                ]))
                parsed["patch_operations"] = derive_required_patch_operations(
                    evaluation, parsed.get("patch_operations", []),
                )
                parsed["score_gaps"] = _score_gaps(evaluation)
                hypotheses = parsed.get("next_round_hypotheses", [])
                parsed["next_round_hypotheses"] = list(dict.fromkeys(
                    text for item in (hypotheses if isinstance(hypotheses, list) else [])[:10]
                    if (text := _safe_feedback_text(item))
                ))
                parsed["before_strategy_version_id"] = None
                parsed["after_strategy_version_id"] = None
            artifact = (
                {**parsed, "provider_request_id": result.provider_request_id if result else None}
                if self.key == "N19"
                else {"llm": parsed, "provider_request_id": result.provider_request_id if result else None}
            )
            if extraction_mode:
                artifact["extraction_mode"] = extraction_mode
        except Exception:  # noqa: TRY203 - preserve the original typed validation error
            # A node that did not produce its business artifact must never be
            # routed as success. The engine records the failure for inspection.
            raise
        return {"outcome": outcome, "artifact": artifact}


def context_run_id(value: Any) -> str:
    return str(value.get("__run_id", "unknown")) if isinstance(value, dict) else "unknown"


def build_real_registry(*, llm: LLMProvider, search: SearchProvider, repository: Any = None) -> NodeRegistry:
    return NodeRegistry({key: RealWorkflowNode(key, outcome, llm, search, repository)
                         for key, outcome in _OUTCOMES.items()})
