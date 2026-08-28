# “凿 agugent”节点可行性实验方案

- 文档性质：临时实验文档，不是正式技术方案
- 实验日期：2026-08-27
- 实验目标：在不编写产品代码的情况下，用独立 Subagent 模拟 Responses LLM Provider，验证已确认状态机节点能否找到真实中文模板梗、网友变式、抽取模板、生成候选、自评选优，并根据真实人工评价产生更合理的下一轮策略补丁。

## 1. 验证范围

本次连续进行两轮实验：

1. 人工种子轮：种子固定为“你说得对，但是”。
2. 自主发现轮：不提供种子，使用人工种子轮评价后形成的新策略，并避开正式梗标题。

不验证：Web UI、数据库写入、并发、崩溃恢复、REST/SSE、真实 OpenAI/DeepSeek API 的字段兼容性。

## 2. 实验角色

- 主 Agent：只负责编排、确定性校验、保存节点产物、执行状态转移和展示结果。
- LLM Subagent：模拟一个无状态 Responses API 调用。每次只得到该节点明确允许的输入，不读取其他节点的隐藏上下文。
- 搜索执行器：实际访问公开搜索结果和网页；不得虚构来源。由于实验环境没有 Brave API Key，实验使用可访问的公开搜索入口代替 Brave，只验证查询和证据链能力，不验证 Brave 的响应格式与配额行为。
- 人工评审者：用户本人。人工种子轮结束后提交结构化评价。

## 3. 公共 LLM 系统提示词

所有 LLM 节点使用以下共同约束：

```text
你是“凿 agugent”状态机中的一个独立节点。你只能处理当前节点任务，不能自行改变状态图，不能假装调用未提供的工具，不能补造网页、网友文案、来源或传播数据。

你必须：
1. 只依据输入中的证据 ID 引用事实；
2. 将网页原文、你的归纳和你生成的内容严格区分；
3. 输出符合给定 JSON Schema 的单个 JSON 对象；
4. 不输出隐藏思维过程，只输出简洁、可审计的判断理由；
5. 缺少证据时明确返回证据不足，不得凑结果；
6. 所有评分使用 1 至 5 的整数；
7. 中文文案保持原貌，除非节点任务明确要求规范化或生成。
```

## 4. 节点提示词与结构化契约

### N01 `ACCEPT_MANUAL_SEED`

```text
任务：理解人工种子。把输入整理成核心表达、可能原句和搜索概念，不执行搜索。
输入：raw_seed、strategy.accept_manual_seed。
输出：raw_seed、normalized_seed、core_expression、possible_original_phrases[]、ambiguities[]、initial_query_concepts[]、human_summary。
失败：输入为空、超过 2000 字或不是可识别的中文文案线索。
```

### N02 `PLAN_DISCOVERY_DIRECTION`

```text
任务：在没有人工种子的情况下选择一个中文纯文本文案模板梗发现方向。
输入：正式梗 id+title 全量列表、上一轮策略反馈、strategy.plan_discovery_direction。
要求：主动避开已有标题；选择搜索引擎可能找到原句与多个改编变式的方向。
输出：direction_title、meme_categories[]、avoid_topics[]、reason、initial_query_concepts[]、possible_duplicate。
```

### N03 `BUILD_ORIGINAL_SEARCH_PLAN`

```text
任务：为人工种子理解结果或自主发现方向制定有序搜索计划。
输入：mode、seed_understanding 或 discovery_direction、strategy.build_original_search_plan。
要求：生成 3 至 8 条不同目的的中文搜索词，分别注明找原句、找梗名、找改编迹象等目的。
输出：queries[{query,purpose,priority,expected_signal}]、stop_conditions[]、human_summary。
```

### N04 `SEARCH_ORIGINAL_CANDIDATES`

确定性搜索节点，不调用 LLM。输入查询计划，输出真实搜索结果、来源 URL、标题、摘要或正文引用片段。搜索证据均分配 source_id。

### N05 `EVALUATE_AND_SELECT_ONE_ORIGINAL_MEME`

```text
任务：从真实搜索证据中最终且只选择一个最值得继续处理的原始模板梗。
输入：search_results[]、source_evidence[]、strategy.evaluate_original。
要求：可以比较多个候选，但 selected_original 必须且只能有一个；不得创造证据中不存在的原句；没有合格项时返回 NO_QUALIFIED_CANDIDATE。
评分：中文纯文本属性、模板性、可见改编证据、来源质量、凿 agu 适配潜力。
输出：outcome、selected_original{provisional_title,original_text,source_ids,scores,strengths,risks}、selection_reason、rejected_candidate_summaries[]、confidence、human_summary。
```

### N06 `CHECK_ORIGINAL_DUPLICATION`

```text
任务：只对 selected_original 与正式梗标题进行查重。
第一阶段输入：selected_original、formal_titles[{record_id,title}]。
第一阶段输出：initial_decision(NOT_DUPLICATE|SUSPECTED|DUPLICATE)、suspected_record_ids(最多5个)、comparison_reasons[]。
如果存在怀疑项，编排器按 ID 提供详情后进行第二阶段判断。
最终输出：final_decision、details_requested[]、comparison_reasons[]、human_override_required。
```

### N07 `BUILD_VARIANT_SEARCH_PLAN`

```text
任务：只围绕唯一 selected_original 制定变式搜索计划。
输入：selected_original、original_sources、strategy.build_variant_search_plan。
要求：覆盖完整原句、固定前后缀、留空式搜索、替换词搜索；生成 4 至 10 条查询。
输出：fixed_anchors[]、variable_hypotheses[]、queries[]、minimum_evidence_goal、human_summary。
```

### N08 `SEARCH_VARIANTS`

确定性搜索节点，不调用 LLM。实际搜索并提取含固定锚点的局部文案证据，保存 source_id、query、evidence_text、evidence_type、URL 和标题；不直接判定其为有效变式。

### N09 `EVALUATE_VARIANT_EVIDENCE`

```text
任务：判断每条真实证据是否为唯一原始梗的网友变式。
输入：selected_original、variant_evidence[]、strategy.evaluate_variants。
分类：VALID_VARIANT、ORIGINAL_REPOST、IRRELEVANT、INSUFFICIENT_CONTEXT、DUPLICATE_VARIANT。
要求：有效变式必须引用真实 source_id，并说明固定部分、变化部分和关系。
输出：valid_variants[]、rejected_evidence[]、evidence_metrics、is_sufficient、insufficiency_reason、human_summary。
默认充分条件：至少3条不同变式、至少2个URL、共享至少一个可辨识固定表达。
```

### N10 `EXTRACT_TEMPLATE`

```text
任务：根据唯一原始梗和有效变式提取模板。
输入：selected_original、valid_variants[]、strategy.extract_template。
要求：模板必须包含固定文本与至少一个槽位；槽位说明语义、语法作用、是否必填和例值；不得提前包含 agu 或凿。
输出：template_title、segments[]、canonical_template_text、invariant_features[]、optional_variations[]、derivation_evidence[]、human_summary。
```

### N11 `VALIDATE_TEMPLATE`

```text
任务：用原始梗和所有有效变式反向校验模板。
输入：template、selected_original、valid_variants[]、strategy.validate_template。
要求：逐条给出槽位绑定和重建结果；区分精确匹配与语义匹配。
输出：validation_cases[]、coverage_rate、template_accuracy_score、decision(PASS|REEXTRACT|MORE_EVIDENCE)、revision_suggestions[]、human_summary。
默认通过：原始梗匹配；至少80%变式精确或语义匹配；准确度不低于4。
```

### N11.5 `ASSESS_AGU_ADAPTABILITY`

```text
任务：在模板验证通过后，判断该模板能否自然承载“凿 agu”的目标语义，并决定生成路由。
输入：validated_template、selected_original、valid_variants[]、target_semantics、strategy.assess_agu_adaptability。
目标语义：小写 ASCII `agu` 是人物和动作受事；“凿”是直接施加于 agu 的及物动作；成品必须肯定该动作已经发生、正在发生或将要发生。
分析要求：显式说明模板槽位的语义角色、否定范围、动作谓词槽是否存在、槽位负担、原梗核心锚点、语气、节奏和笑点机制。不得因为原梗传播度高或模板提取准确就提高适配评分。
输出：target_semantics、template_semantics、direct_fill_compatibility、direct_fill_problems[]、structure_rewrite_compatibility、route、must_preserve[]、may_rewrite[]、rewrite_blueprints[]、abandon_conditions[]、risks[]、decision_reason、human_summary。
路由枚举：DIRECT_SLOT_FILL、STRUCTURE_PRESERVING_REWRITE、ABANDON_ORIGINAL。
默认路由：direct_fill_compatibility>=4 时直接回填；否则 structure_rewrite_compatibility>=3 时保结构改写；两者均未达到门槛时放弃当前原始梗。
限制：rewrite_blueprints 只能描述抽象骨架和保留特征，不生成最终候选。
```

状态转移：

- `DIRECT_SLOT_FILL` → N12，N12 只能按验证模板回填。
- `STRUCTURE_PRESERVING_REWRITE` → N12，N12 必须遵守 `must_preserve`、`may_rewrite` 和改写蓝图。
- `ABANDON_ORIGINAL` → 放弃当前原始梗；自主发现模式回 N02，人工种子模式回 N03 并携带本轮排除项。
- 放弃项不写正式梗库，也不注入后续正式标题查重；只能作为本轮运行态中的搜索止损信息。

### N12 `GENERATE_AGU_CANDIDATES`

```text
任务：严格按照 N11.5 的唯一确定路由，生成5条有实际差异的“凿 agu”候选。
输入：validated_template、selected_original、valid_variants[]、adaptability_assessment、strategy.generate_candidates。
共同硬约束：每条必须原样包含小写 ASCII `agu`；agu 是人物；“凿”是直接施加于 agu 的及物动作；动作必须处于肯定范围；不得冒充网友原文或写成作品名、工作室、计划、社团和世界观设定。
DIRECT_SLOT_FILL 要求：只在适配度达标时使用；保持验证模板的固定文本、槽位语义和完整结构。
STRUCTURE_PRESERVING_REWRITE 要求：保留 must_preserve 中的核心锚点、语气、节奏和笑点机制；只改写 may_rewrite 允许的局部；不得退回把“凿 agu”包装成长身份短语的机械填槽。
差异要求：五条应覆盖不同的动作断言或反差机制，不能只更换称呼、职业或状语。
输出：route_used、candidates[{candidate_id,text,target_semantics,preserved_features[],rewritten_features[],slot_bindings?,generation_approach,length_note}]、diversity_summary、human_summary。
确定性校验：编排器在进入 N13 前检查候选 ID、数量、`agu`、`凿`、route_used、必保留锚点以及动作肯定性中的可确定部分；失败则拒绝节点产物，不交给 N13 补救。
```

### N13 `SELF_SCORE_CANDIDATES`

```text
任务：独立评价候选，不读取生成节点的解释、自我评分或自我辩护。
输入：candidate_texts[]、validated_template、selected_original、adaptability_assessment 中的 route/must_preserve/target_semantics、scoring_rubric、strategy.self_score_candidates。
评分：fluency、original_meme_recognition、agu_zao_naturalness、humor、rhythm_preservation、rewrite_rationality。
关键检查：agu 是否为人物；“凿”是否直接作用于 agu；动作是否处于肯定范围；候选是否保留路由要求的核心特征；局部改写是否解决模板不适配问题，而非随意脱离原梗。
输出：candidate_scores[{candidate_id,scores,average,action_affirmed,qualified,critical_failures[],reason}]、set_diversity_score、set_quality_score、all_unqualified、recommended_candidate_id、human_summary。
默认合格：六维平均分>=3.5，且通顺度、原梗辨识度、agu/凿自然度均>=3，action_affirmed=true。
保守规则：其他维度不得补偿关键检查失败；只包含关键词但没有反差时幽默不得高于1；冗长解释导致节奏消失时必须降低节奏与改写合理性。
```

### N14 `SELECT_FINAL_CANDIDATE`

```text
任务：只从已有合格候选中选择一条最终结果，不得新写文案。
输入：qualified_candidates[]、candidate_scores[]、selected_original、adaptability_assessment、strategy.select_final_candidate。
输出：ranked_candidate_ids[]、selected_candidate_id、selection_reason、rejection_reasons_by_candidate、selection_confidence、human_summary。
```

### N15 `GENERATE_FORMAL_MEME_DRAFT`

```text
任务：生成正式梗草稿及有辨识度的标题。
输入：selected_original、validated_template、adaptability_assessment、selected_final_candidate、primary_sources。
要求：标题描述原始模板梗身份，长度4至40个中文字符或等价长度，不使用运行编号，不冒充网页标题。
输出：title、normalized_title、original_meme_text、template_summary、template_segments、adaptation_route、preserved_features[]、rewritten_features[]、final_agu_text、primary_source_ids[]、human_summary。
```

### N16 `FINAL_TITLE_DEDUP_CHECK`

与 N06 同一契约，但读取执行时最新正式梗标题。本实验没有并发正式梗写入时仍执行，以验证契约。

### N17 `DECIDE_ADMISSION`

本实验固定为人工准入，不验证自动阈值。输出 WAIT_HUMAN 和待评价草稿。

### N18 `WAIT_FOR_HUMAN_EVALUATION`

不调用 LLM。由用户真实评价处理链、候选集、每条候选、最终结果、主要问题节点和入库决定。评分为1至5。

### N19 `UPDATE_STRATEGY`

```text
任务：根据本轮完整链路、Agent 自评分、真实人工评价和当前策略生成受限 StrategyPatch。
要求：只能修改人工反馈能够支持的节点；必须区分适配路由、生成质量与选优问题；不得修改状态图、模型连接、数据库、安全约束或人工评价必做规则。
输出：feedback_summary、self_human_score_gaps[]、affected_nodes[]、keep_rules[]、changes[{node_key,field_path,operation,old_value,new_value,feedback_evidence,expected_effect}]、next_round_hypotheses[]、human_summary。
```

### N20 `COMPLETE_RUN`

本实验不写 SQLite，只冻结一份模拟运行快照和新策略，供第二轮使用。

## 5. 初始策略 V1

```json
{
  "version": "experiment-v1",
  "plan_discovery_direction": {
    "prefer": ["有固定句式", "搜索结果中可能出现多人改编", "适合替换人物和动作"],
    "avoid": ["只有单一出处且没有改编", "纯图片或视频梗", "依赖谐音但无固定文案"]
  },
  "build_original_search_plan": {
    "query_count": [3, 8],
    "query_intents": ["原句", "梗名", "改编迹象"]
  },
  "evaluate_original": {
    "minimum_average": 3.5,
    "minimum_template_score": 3,
    "minimum_evidence_score": 3,
    "single_selection": true
  },
  "build_variant_search_plan": {
    "query_count": [4, 10],
    "minimum_valid_variants": 3,
    "minimum_distinct_urls": 2
  },
  "extract_template": {
    "require_fixed_text": true,
    "require_slot": true
  },
  "validate_template": {
    "minimum_coverage": 0.8,
    "minimum_accuracy_score": 4
  },
  "assess_agu_adaptability": {
    "target_agu_role": "PERSON_PATIENT",
    "target_zao_role": "TRANSITIVE_ACTION",
    "require_affirmed_action": true,
    "direct_fill_threshold": 4,
    "structure_rewrite_threshold": 3,
    "allow_abandon_original": true
  },
  "generate_candidates": {
    "candidate_count": 5,
    "require_agu": true,
    "require_zao": true,
    "require_affirmed_action": true,
    "require_material_diversity": true,
    "follow_adaptability_route": true
  },
  "self_score_candidates": {
    "minimum_average": 3.5,
    "minimum_critical_dimension": 3,
    "require_action_affirmed": true
  },
  "select_final_candidate": {
    "select_existing_only": true
  }
}
```

## 6. 实验通过标准

### 6.1 搜索与证据

- 搜索计划至少包含不同搜索意图，而不是同义改写。
- 原始梗引用可以访问的真实 URL 或可核验搜索证据。
- 只选一个原始梗，后续不混入其他候选。
- 至少找到3条不同有效变式，来自至少2个 URL；若未找到，状态机应诚实回退或失败。
- LLM 不得伪造来源或把自己的生成文案当网友变式。

### 6.2 模板与生成

- 模板能解释原始梗和至少80%的有效变式。
- N11.5 能分别评价直接回填与保结构改写的适配度，并只输出一个合法路由。
- 直接回填不适配时不得机械填槽；保结构改写也不适配时必须放弃当前原始梗并回退。
- 候选均原样包含小写 ASCII `agu` 与“凿”；agu 是人物受事，“凿”是直接动作且处于肯定范围。
- DIRECT_SLOT_FILL 候选保持验证模板；STRUCTURE_PRESERVING_REWRITE 候选保留 must_preserve 并只修改 may_rewrite。
- 候选在动作断言或反差机制上存在实际差异，不能只更换称呼、职业或状语。
- 编排器在 N13 前完成可确定的字面、ID、数量、路由和锚点校验。
- 最终结果来自已有合格候选。

### 6.3 人工反馈闭环

- StrategyPatch 能把人工反馈定位到正确节点。
- 补丁描述具体可执行的规则变化，而不是“提升质量”。
- 第二轮实际使用新规则。
- 若第二轮的对应行为与补丁一致，则证明反馈链路可执行；单次实验不证明长期质量必然提升。

## 7. 实验限制与记录要求

- 搜索引擎排序和网页内容随时间变化，所有发现记录检索日期。
- Subagent 不是 OpenAI 或 DeepSeek API，本实验验证提示词、上下文边界和状态编排，不验证具体供应商模型的一致性。
- 如果搜索入口无法访问，应记录为实验环境限制，不用离线夹具冒充真实搜索成功。
- 每个节点保存结构化产物、输入证据 ID、结论、重试和回退。
- 用户评价前不得预先假设反馈或更新策略。

## 8. 人工种子轮运行记录（已完成评价）

- 运行日期：2026-08-27
- 模式：人工种子
- 种子：`你说得对，但是`
- 当前状态：`COMPLETE_RUN`
- 正式梗库模拟标题列表：空

### 8.1 状态转移摘要

1. N01 将种子理解为“先认可，再用但是引出转折”，并生成原句、出处、梗名、改编等搜索概念。
2. N03 生成七类不同意图查询；N04 的 Bing/Baidu/Sogou 可用性或中文短语质量不稳定，360 搜索返回可核验结果。
3. N05 只选择一条原始梗：`你说的对,但是《原神》是由米哈游自主研发的一款全新开放世界冒险游戏。`
4. N06 对空正式梗库判定 `NOT_DUPLICATE`。
5. 第一次 N07 查询过度集中于原神原句及转载；第一次 N09 只得到原句和近似转载，判定 0 条有效变式并回退 N07。
6. 第二次 N07 根据失败原因改为固定骨架、跨对象替换、排除原神的查询；第二次 N09 判定 8 条有效变式、8 个不同 URL，证据充分。
7. 第一次 N10 将“对象描述”误设为必填且没有准确表达原始研发方语序；第一次 N11 覆盖率 77.8%，回退 N10。
8. N10 重试产物首次未通过 JSON Schema，触发一次同模型结构修复；修复后语义范围仍不准确，第二次 N11 覆盖率 44.44%，再次回退 N10。
9. 第三次 N10 区分“证据模板尾部可选”与“生成成品必须完整”，保留 S01 的研发方语序；第三次 N11 对 9 个案例覆盖率 100%，准确度 5/5，通过。
10. N12 生成 5 条完整候选；N13 独立评分后 C1、C2、C4 合格，C3、C5 不合格；N14 从合格候选中选择 C2，未改写候选。
11. N15 生成标题为“原神式宣传文案梗”的正式草稿；N16 对最新空标题库再次判定 `NOT_DUPLICATE`；N17 按人工准入进入 N18 等待评价。

### 8.2 已核验的核心来源与变式证据

- S01 原始/核心版本：<https://www.bilibili.com/read/cv21234240/>
- S02 火影忍者手游：<https://www.bilibili.com/video/BV1ps4y1b7pp/>
- S03 第五人格：<https://www.bilibili.com/video/av445759070/>
- S04 Procreate：<https://www.bilibili.com/video/av233896492/>
- S05 三国杀：<https://www.douyin.com/video/7444926194824351013>
- S06 第五人格扩写：<https://www.bilibili.com/video/BV1xk4y1G7eT/>
- S07 深岩银河：<https://www.bilibili.com/video/BV1MXvaenEuB/>
- S08 CSGO：<https://www.bilibili.com/video/BV17e4y1L71Z/>
- S09 千恋万花：<https://www.bilibili.com/video/BV1Bo4y1w7uR/>

这些来源证明搜索结果中存在共同骨架及跨对象改编；它们不证明最早出处、传播量或搜索标题省略号后的完整正文。

### 8.3 最终模板

```text
主结构：你说的/得对，但是{主题}是一款{后续描述}
允许语序：你说的对，但是{主题}是由{研发方}自主研发的一款{后续描述}
```

- `主题`：必填。
- `后续描述`：证据模板层可选，以容纳截断的搜索标题；候选生成层必须补成完整文案。
- `研发方`：只在允许语序中使用。

### 8.4 候选与 Agent 自评分

| ID | 候选 | 通顺 | 原梗辨识 | agu/凿自然 | 好笑 | 模板逻辑 | 均分 | 合格 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C1 | 你说得对，但是《凿 agu》是一款围绕矿洞勘探、石材凿刻与遗迹修复展开的模拟经营游戏。 | 5 | 4 | 3 | 2 | 4 | 3.6 | 是 |
| C2 | 你说的对，但是 agu 是由凿工作室自主研发的一款让玩家用石凿改造浮空岛地形的建造游戏。 | 4 | 5 | 3 | 3 | 5 | 4.0 | 是 |
| C3 | 你说得对，但是凿 agu 是一款让考古队根据岩层纹理判断机关、逐层凿开地下遗址的解谜游戏。 | 4 | 4 | 2 | 3 | 4 | 3.4 | 否 |
| C4 | 你说的对，但是《agu：凿星计划》是一款讲述工程师在陨石城里凿通能源管网、守住最后聚居地的策略游戏。 | 5 | 4 | 4 | 3 | 4 | 4.0 | 是 |
| C5 | 你说得对，但是 agu 凿刻社是一款让玩家收集各地石料、为街坊凿制印章并经营小店的休闲游戏。 | 3 | 4 | 3 | 3 | 3 | 3.2 | 否 |

### 8.5 Agent 最终选择与草稿

- 最终选择：C2。
- Agent 理由：最完整保留“由……自主研发的一款……”句法，并认为 `agu` 与“凿工作室”兼顾原梗辨识和融合自然度。
- 正式标题：`原神式宣传文案梗`
- 最终文案：`你说的对，但是 agu 是由凿工作室自主研发的一款让玩家用石凿改造浮空岛地形的建造游戏。`
- 该阶段曾停在人工评价前；收到真实评价和“入库”决定后，实验模拟新增 M001，详见 8.6。

### 8.6 真实人工评价摘要

- 处理链：原始梗传播度、适用性、搜索相关性、变式证据质量均为 5 分；模板提取准确度和整体合理性均为 4 分。
- 候选集：有效差异 5 分，但自然改写覆盖 3 分、整体可选水平 2 分。
- 核心语义纠正：`agu` 是人物；“凿”是直接施加于 agu 的动作，等价于“把 agu 凿”。
- 核心生成约束：必须完整沿用提取出的模板；尾部描述长度应接近原句，不应展开成长句。
- 最终选择：人工确认 C2 是当批相对最佳候选，但仍需修改。
- 主要问题节点：`候选生成/候选自评分`。
- 入库决定：`入库`。实验模拟正式梗库新增 `M001 | 原神式宣传文案梗`。

### 8.7 人工反馈形成的 Strategy V2

> 本节记录第一次反馈后的历史策略，不再代表当前节点设计。其中“必须保留所选原梗的完整结构”已被 N11.5 的适配路由取代：直接回填时保留完整模板，保结构改写时保留核心锚点、语气、节奏和笑点机制。

只修改 N12 与 N13；搜索、证据评价、模板提取和最终选择策略保持不变。

N12 新增：

- agu 必须明确作为人物。
- “凿”必须直接施加于 agu，等价于“把 agu 凿”。
- 不得把 agu 或凿仅作为作品名、工作室、计划、社团或世界观装饰。
- 必须保留所选原梗的完整结构。
- 尾部通常控制在 6～14 个汉字或等价短语。
- 禁止展开剧情、玩法或世界观长句。

N13 新增：

- 独立检查动宾语义、幽默和完整模板逻辑。
- 间接命名语境的 agu/凿自然度不得高于 1。
- 只做词面替换且没有反差时，幽默不得高于 1。
- 只保留开头或关键词时，模板逻辑不得高于 2。
- 采用保守评分，其他维度不得补偿关键约束失败。

## 9. 自主发现轮运行记录（等待人工评价）

- 运行日期：2026-08-27
- 模式：自主发现
- 注入正式梗标题：`M001 | 原神式宣传文案梗`
- 未注入：失败方向、被拒绝方向及其记录
- 当前状态：`WAIT_FOR_HUMAN_EVALUATION`

### 9.1 自主发现及回退

1. 方向一选择“我一进来就看见常威在打来福”。原句可检索，但两轮搜索后只有 2 条有效变式，N09 未达到 3 条门槛，回退 N02。
2. 方向二选择“你这个年纪怎么睡得着”。N06 首次误判与 M001 重复，经契约修复后判定 `NOT_DUPLICATE`；N07 又出现 Schema 错误和串题，节点级重试后恢复。最终仍只有 2 条有效变式，回退 N02。
3. 方向三选择“大胆妖孽，我一眼就看出你不是人”。N03 明确要求核对出处；N04 搜索证据指向赵文卓版《青蛇》相关片段，纠正 N02 中误写的《大话西游》归属。
4. N05 首次错误地把变式证据 ID 混入原句来源 ID，编排器拒绝；重试后只保留 O01、O02、O03。
5. N06 仅与 M001 标题比较，判定 `NOT_DUPLICATE`。
6. N09 认定 5 条有效变式、5 个不同 URL；原句转载和不满足共享锚点的“葫芦娃蛇精”证据被剔除。
7. N10 首次把多个 source ID 合并写入单个字段，编排器拒绝；重试后逐一引用。N11 对原句和 5 条变式覆盖率 100%，模板准确度 5 分，判定 `PASS`。
8. N12 首批候选虽满足 V2 的人物、直接动宾和完整模板要求，但全部使用生硬的“凿某职业阿古的家伙”呼语。N13 将 5 条全部判为不合格，集合差异 1 分、质量 2 分，回退 N12。
9. N12 根据本轮 N13 的确定性问题重新生成；第二次 N13 曾判定 5 条均合格，N14 选择 C2。
10. 编排器在进入人工评价前发现 5 条候选均把硬约束字面量 `agu` 改写为“阿古”。复现检查得到 5 个 `FAIL missing literal agu`，因此撤销该批 N13～N16 产物并回退 N12。
11. 根因是 N12 只收到“agu 是人物”的语义约束，未收到“必须原样保留小写 ASCII 字面量”的可机检契约；N13 也把“阿古”当语义等价物放行。修复后，N12 提示词新增字面硬约束，编排器在 N13 前检查每条同时包含 `大胆`、`我一眼就看出你不是`、`agu` 和 `凿`，5 条全部通过。
12. 修复后的 N13 只判定 C2、C5 合格；N14 从两条合格候选中选择 C5。N15 生成新草稿，N16 与 M001 再次查重为 `NOT_DUPLICATE`；N17 进入人工评价等待态。

### 9.2 已核验的原句与变式证据

原句来源：

- O01 优酷：<https://v.youku.com/v_show/id_XNDcwNzMzNDU5Mg==.html>
- O02 Bilibili：<https://www.bilibili.com/video/BV1KnSbYdEKd/>
- O03 腾讯视频：<https://v.qq.com/x/page/q3123mt60p5.html>

N09 认定的有效变式：

- V01 `大胆UP主！我一眼就看出你不是人！`：<https://www.bilibili.com/video/BV1th411o7jh>
- V02 `大胆妖孽，我一眼就看出你不是银`：<https://www.iqiyi.com/v_1pb54dszvi8.html>
- V03 `大胆！我一眼就看出你不是如来`：<https://www.bilibili.com/video/av413917772>
- V04 `19 我一眼就看出你不是ADC！大胆妖孽！`：<https://www.bilibili.com/video/BV1Dz411i7yy/>
- V05 `大胆up，住嘴，我一眼就看出你不是人`：<https://www.bilibili.com/opus/397778327404955946>

证据来自公开搜索结果标题或摘要，只证明检索时存在这些文案，不证明最早出处或全网传播量。360 PC 入口触发验证码后，本轮使用 360 移动端公开结果；Bing 中文结果质量不稳定。

### 9.3 已验证模板

```text
大胆{被呵斥对象}，我一眼就看出你不是{表面身份}！
```

- `被呵斥对象`：可选呼语，例如“妖孽”“UP主”“up”。
- `表面身份`：必填的被否定身份，例如“人”“银”“如来”“ADC”。
- 固定锚点：`大胆`、`我一眼就看出你不是`。
- 证据允许省略呼语、插入短呵斥语或前后调整，但候选生成仍优先使用完整标准结构。

### 9.4 N12 首批失败候选与 N13 结论

| ID | 候选 | 均分 | 结论 |
|---|---|---:|---|
| C1 | 大胆凿向导阿古的家伙，我一眼就看出你不是正经石匠！ | 2.6 | 不合格 |
| C2 | 大胆凿村民阿古的恶徒，我一眼就看出你不是雕刻师傅！ | 2.6 | 不合格 |
| C3 | 大胆凿学徒阿古的狂徒，我一眼就看出你不是工坊老师傅！ | 2.4 | 不合格 |
| C4 | 大胆凿守卫阿古的歹人，我一眼就看出你不是王城工匠！ | 2.6 | 不合格 |
| C5 | 大胆凿医师阿古的凶徒，我一眼就看出你不是修复专家！ | 2.4 | 不合格 |

共同失败：呼语生硬并有断句歧义；只更换职业标签，实质差异不足；幽默均为 1 分。这个结果证明 V2 的约束已被 N12/N13 执行，但第一次执行没有直接保证成品质量。

### 9.5 被字面契约拒绝的中间产物

N12 第一次重试生成了“阿古”版本。虽然独立评分认为内容质量提高，但它违反“候选必须包含字面量 `agu`”的硬契约，因此整批产物以及由它派生的 N13～N16 结果均作废，不进入人工评价。

这个问题说明仅靠 LLM 语义评分不足以执行可确定判断的约束；候选的必含词、ID、唯一原始梗锚点和模板固定片段应由编排器先做确定性校验。

### 9.6 修复后的候选与 Agent 自评分

| ID | 候选 | 通顺 | 原梗辨识 | agu/凿自然 | 好笑 | 模板逻辑 | 均分 | 合格 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C1 | 大胆理发师，我一眼就看出你不是把 agu 凿出酒窝的美容师！ | 3 | 5 | 3 | 2 | 2 | 3.0 | 否 |
| C2 | 大胆扫码员，我一眼就看出你不是把 agu 本人凿成二维码的石匠！ | 4 | 5 | 4 | 4 | 3 | 4.0 | 是 |
| C3 | 大胆报时人，我一眼就看出你不是昨夜三更凿醒 agu 的更夫！ | 4 | 5 | 2 | 3 | 3 | 3.4 | 否 |
| C4 | 大胆排号员，我一眼就看出你不是排队时把 agu 凿出队伍的急性子！ | 3 | 5 | 2 | 3 | 3 | 3.2 | 否 |
| C5 | 大胆房东，我一眼就看出你不是上门把 agu 凿进墙里的维修师傅！ | 4 | 5 | 4 | 4 | 4 | 4.2 | 是 |

N13 只放行 C2、C5。N14 排名：`C5 > C2`。

### 9.7 待人工评价的最终草稿

- 标题：`《青蛇》法海“大胆妖孽”识破身份梗`
- 原始梗：`大胆妖孽，我一眼就看出你不是人`
- 最终候选：`大胆房东，我一眼就看出你不是上门把 agu 凿进墙里的维修师傅！`
- N16 标题查重：`NOT_DUPLICATE`
- 准入状态：`WAIT_HUMAN`

本轮不得在收到结构化人工评价前执行 N19、模拟入库或进入下一轮。

## 10. “凿 agu”适配与保结构改写专项实验

- 实验日期：2026-08-27
- 实验性质：只验证新增适配节点及生成下游，不重跑搜索、原始梗选择、查重、变式搜索、模板提取与模板验证。
- 复用原始梗：`大胆妖孽，我一眼就看出你不是人`
- 复用已验证模板：`大胆{被呵斥对象}，我一眼就看出你不是{表面身份}！`
- 复用有效变式：V01～V05。
- 用户确认：模板完整度不再是绝对硬约束；若直接回填和保结构改写都不自然，允许放弃原始梗。

### 10.1 新增 N11.5 `ASSESS_AGU_ADAPTABILITY`

节点先把两侧语义角色显式化：

- `agu`：人物、动作受事，必须保留小写 ASCII 字面量。
- `凿`：直接施加于 agu 的及物动作。
- 目标断言：必须肯定“把 agu 凿”的动作关系，不能仅描述或否定某种身份。

节点输出：

- 直接回填适配度：`1/5`。
- 保结构改写适配度：`4/5`。
- 路由：`STRUCTURE_PRESERVING_REWRITE`。

直接回填被拒绝的原因：

1. 原模板只有呼语槽和身份槽，没有动作谓词槽。
2. 把“凿 agu”包装进 `{表面身份}` 后，会落入“不是”的否定范围，无法肯定动作发生。
3. 身份槽被迫同时承载施事、动作和受事，形成冗长身份短语并破坏节奏。

允许改写：将“你不是{表面身份}”改成肯定动作的谓词结构；保留“大胆”、`我一眼就看出`、先呵斥后识破的两拍节奏和短促语气。

### 10.2 新版 N12 候选

| ID | 改写机制 | 候选 |
|---|---|---|
| C1 | 已发生断言 | 大胆！我一眼就看出你已经凿了agu！ |
| C2 | 意图断言 | 大胆！我一眼就看出你就是要凿agu！ |
| C3 | 对象纠正 | 大胆！我一眼就看出你不是在凿石头，你是在凿agu！ |
| C4 | 把字处置 | 大胆！我一眼就看出你把agu凿开了！ |
| C5 | 证据归因 | 大胆！我一眼就看出这些凿痕正是你凿agu留下的！ |

编排器确定性检查确认五条均包含 `大胆`、`我一眼就看出`、`agu` 和 `凿`。

### 10.3 新版 N13 独立评分

评分维度改为：通顺度、原梗辨识度、agu/凿自然度、幽默、节奏保留、改写合理性。合格要求为六维平均不低于 3.5，三个关键维度不低于 3，且目标动作处于肯定范围。

| ID | 通顺 | 辨识 | 融合 | 幽默 | 节奏 | 改写合理 | 均分 | 合格 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| C1 | 4 | 5 | 4 | 3 | 5 | 4 | 4.17 | 是 |
| C2 | 3 | 5 | 4 | 3 | 5 | 4 | 4.00 | 是 |
| C3 | 5 | 5 | 4 | 4 | 3 | 5 | 4.33 | 是 |
| C4 | 5 | 5 | 4 | 4 | 5 | 4 | 4.50 | 是 |
| C5 | 3 | 4 | 4 | 3 | 2 | 3 | 3.17 | 否 |

N13 能识别 C5 的重复拗口和节奏过长，没有因为目标语义正确就放行。

### 10.4 N14 选择

- 排名：`C4 > C3 > C1 > C2`。
- 最终选择：`大胆！我一眼就看出你把agu凿开了！`
- 选择理由：动作肯定、受事明确、句子短促，同时保留呵斥和一眼识破结构。

### 10.5 与旧生成路径的对照

旧路径代表结果：

```text
大胆房东，我一眼就看出你不是上门把 agu 凿进墙里的维修师傅！
```

新路径代表结果：

```text
大胆！我一眼就看出你把agu凿开了！
```

改进点：

- 从否定“凿 agu 的身份”改为肯定“凿 agu 的动作”。
- 不再用长身份短语解释动作，槽位负担显著降低。
- 保留原梗的呵斥、视觉识破和短促节奏，而不是机械保留全部字面结构。
- 新评分能分别检查目标语义、节奏和改写合理性。

### 10.6 专项实验结论与限制

专项实验支持以下可行性结论：在模板验证和候选生成之间新增目标语义适配节点，可以识别“模板本身正确，但不适合直接回填”的情况，并能把下游路由到保结构改写或放弃原梗；本例中成功避免了旧流程的否定范围和长身份短语问题。

该实验仍不能证明长期生成质量必然提升：新版候选只有 Agent 自评分，尚无单独人工评分；“移除不是”后原梗辨识度是否符合真实用户感受，仍应在产品的人类评价数据中持续校准。
