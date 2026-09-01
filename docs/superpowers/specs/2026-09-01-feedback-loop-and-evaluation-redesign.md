# 人工反馈闭环与模块化评价设计

## 1. 目标

修复连续执行流程中“人工评价只被总结、未形成可执行策略”的问题，提升变式搜索、变式抽取、模板验证和候选自评分的质量，并将人工评价页面改造成按业务处理模块展示材料和评分的结构化评价页。

本次改动完成后必须满足：

- 人工评价产生可审计、可验证、可应用的策略新版本。
- 下一轮相关节点明确读取该策略版本，节点输出可说明本轮采用了哪些反馈策略。
- 低质量变式不能仅凭数量和来源数通过质量门槛。
- 低覆盖模板不能进入候选生成。
- 运行主记录在等待评价等非终态也与内存状态一致。
- 人工评价页展示七个指定模块，模块评分必填、文本意见选填。

## 2. 现状与问题

当前 N19 只输出 `feedback_summary`、`affected_nodes` 和 `next_round_hypotheses`，没有产生或应用策略补丁。`RunContext.strategy_version_id` 保持为空，策略版本、补丁和当前策略状态表没有记录。N07 在执行时直接调用固定的 `_variant_search_plan()`，因此下一轮查询变化来自原始梗变化，而不是人工反馈。

N09 的真实 LLM 抽取发生 JSON 解析失败时会使用宽松规则兜底。兜底规则会把原句转载、页面标题、释义、繁简体或标点差异和包含原句的长文本计入变式，再以变式条数和独立网址数判断充分性。N11 只要至少两个文本匹配模板就无条件通过，并固定输出最高准确度，导致低覆盖模板进入后续节点。

运行主记录只在任务归档时同步，等待人工评价期间数据库状态仍可能是初始状态。评价页目前按“处理链、候选集、最终结果”分组，不能直接对具体节点材料逐模块评价，且文本意见被错误设为必填。

## 3. 方案选择

采用“结构化策略版本 + 确定性质量门槛 + LLM 策略建议”的混合方案。

- 不采用仅将评价文本追加到提示词的方案，因为无法审计修改内容，也无法确认哪些节点实际读取了反馈。
- 不采用完全由 LLM 自由生成和执行策略的方案，因为补丁路径、质量阈值和状态转移容易失控。
- LLM 负责理解人工评分和意见、提出策略建议；程序负责生成最低限度的确定性补丁、校验允许修改的路径、应用版本、控制质量门槛和状态回退。

## 4. 策略模型与生命周期

### 4.1 默认策略结构

每个新任务必须加载当前激活策略；首次启动且无策略时创建版本 1。策略至少包含以下结构：

```json
{
  "search": {
    "discovery_directives": [],
    "variant_query_directives": [],
    "prefer_ugc_sources": false,
    "exclude_exact_reprints": true,
    "require_slot_replacement": true,
    "max_variant_search_retries": 2,
    "minimum_valid_variants": 3,
    "minimum_independent_variant_sources": 2,
    "minimum_template_coverage": 0.6
  },
  "generation": {
    "directives": [],
    "prefer_minimal_replacement": true,
    "reject_awkward_demonstrative_phrase": true
  },
  "evaluation": {
    "directives": [],
    "minimum_fluency": 6,
    "minimum_recognition": 6,
    "minimum_agu_fit": 6
  },
  "admission": {
    "directives": []
  }
}
```

数值阈值和重试上限属于受保护配置。人工反馈可以增加指令和在预先允许的范围内收紧阈值，不得突破预算、安全、候选数和状态机路由约束。

### 4.2 N19 输出

N19 输出：

```json
{
  "feedback_summary": "...",
  "affected_nodes": ["N07", "N08", "N09"],
  "patch_operations": [
    {
      "op": "add",
      "path": "/search/variant_query_directives/-",
      "value": "优先寻找发生槽位替换的网友原句，排除原句转载和释义页"
    }
  ],
  "score_gaps": {},
  "next_round_hypotheses": ["..."]
}
```

程序根据结构化评分补充最低限度的确定性操作。例如变式搜索计划或结果低于 4 分时，确保启用 `prefer_ugc_sources`、`exclude_exact_reprints` 和 `require_slot_replacement`，并把模块文本意见作为策略指令保存。LLM 操作和确定性操作合并、去重后交给 `StrategyService` 校验。

### 4.3 应用与持久化

补丁通过后：

1. 写入 `run_strategy_versions` 新版本，保存完整策略快照和父版本。
2. 写入 `run_strategy_patches`，保存评价 ID、修改前后版本、反馈摘要、操作和下一轮假设。
3. 更新 `run_strategy_state.active_strategy_version_id`。
4. 更新当前 `RunContext.strategy_version_id` 和 `strategy_snapshot`。
5. N19 返回 `PATCH_VALID`，N20 根据持续执行开关决定结束或进入下一轮。

补丁无效且无法由确定性补丁修正时返回 `PATCH_INVALID`，进入人工干预；不得无策略更新地静默开始下一轮。

### 4.4 节点消费策略

- N02：读取发现指令，避免上一轮明确指出的不适用原梗类别。
- N07：读取变式查询指令和 UGC 偏好，输出 `strategy_version_id`、`applied_directives` 和查询计划。
- N09：读取去噪、槽位替换和充分性要求。
- N11：读取最低模板覆盖率。
- N12：读取生成指令和最小替换偏好。
- N13：读取评分指令及最低合格阈值。

节点审计记录的 `strategy_version_id` 必须等于该节点真实消费的版本。

## 5. 变式证据与模板质量

### 5.1 N07 查询计划

查询计划保留一条原句精确查询作为出处基线，其余查询必须覆盖不同发现方向：

- 只保留固定锚点、不包含完整原句的槽位替换搜索。
- “改编、恶搞、仿写、接龙、下一句”等替换语境。
- 面向用户生成内容的来源方向。
- 根据上一轮反馈增加的专用查询指令。

每条查询标记 `strategy_origin`，说明来自默认规则或哪个反馈指令。查询仍必须围绕 N05 唯一选中的原始梗。

### 5.2 N09 抽取与失败处理

N09 只把满足以下条件的文本作为有效变式：

- 证据原文可在对应 N08 来源中逐字找到。
- 与原句存在共同固定结构，但至少一个可替换槽发生实质变化。
- 不是仅有繁简体、空白、标点或同义转写差异。
- 不是网页标题、导航、下载内容、梗释义、出处说明或包含原句的长上下文。
- 不是完整原句转载。

传给 LLM 的来源和候选片段设上限，输出最多 8 条变式，避免大输出被截断。解析失败时记录失败阶段和响应结束原因。规则兜底必须执行同一组严格质量规则；达不到门槛时返回 `INSUFFICIENT`，不能伪装为成功。

充分性要求同时满足：

- 有效变式不少于策略的 `minimum_valid_variants`。
- 独立来源不少于 `minimum_independent_variant_sources`。
- 每条变式均通过槽位替换验证。

### 5.3 回退与预算

N09 `INSUFFICIENT` 或 N11 `MORE_EVIDENCE` 时回到 N07，并增加当前原始梗的变式补搜计数。最多补搜两次：

- 自搜索模式超过上限后返回 `ABANDON_ORIGINAL`，回到 N02 发现新原始梗。
- 人工种子模式超过上限后进入人工干预，保留当前材料和失败原因。

### 5.4 N11 模板验证

N11 必须真实计算：

- 原句是否能由模板重建。
- 有效变式匹配数量。
- 有效变式覆盖率。
- 固定片段和槽位是否有证据支持。

覆盖率低于策略的 `minimum_template_coverage` 时返回 `MORE_EVIDENCE`；模板无法重建原句或槽位缺乏证据时返回 `REEXTRACT`。`accuracy` 由验证结果推导，不得固定为 5。

### 5.5 候选自评分

N13 除现有辨识度、克制度和最小替换效果外，必须检查明显不通顺的指示结构和动宾关系。存在“这凿agu”等无法成立的名词结构时，通顺度不得达到合格阈值，候选不得进入 N14。

## 6. 模块化人工评价

### 6.1 通用规则

- 所有指标均为 1～5 分，必须填写。
- 每个模块有一个 `comment` 文本意见，选填，未填写时提交空字符串或 `null`。
- 页面展示当前轮最新节点执行结果，不混入上一轮同名节点。
- 大型搜索证据使用摘要、链接和可展开详情，不在首屏直接渲染全部正文。

### 6.2 七个模块

#### 原始梗搜索计划

展示 N03 查询计划及 N04 搜索摘要。

- `anchor_accuracy`：锚点准确度。
- `query_coverage`：查询组合覆盖度。
- `plan_targeting`：计划针对性。
- `comment`：选填。

#### 最终选定原始梗

展示 N05。

- `popularity`：传播度。
- `applicability`：文案梗适用性。
- `adaptability`：可反复改编性。
- `evidence_reliability`：原始证据可靠性。
- `comment`：选填。

#### 变式搜索计划

展示 N07。

- `slot_replacement_targeting`：槽位替换导向。
- `query_diversity`：查询多样性。
- `ugc_orientation`：真实网友改编来源导向。
- `noise_avoidance`：噪声规避能力。
- `comment`：选填。

#### 最终变式搜索结果

展示 N09 有效变式，并以链接和摘要关联 N08 证据。

- `relevance`：结果相关性。
- `real_variant_ratio`：真实变式比例。
- `independent_evidence_quality`：独立证据质量。
- `variant_diversity`：变式多样性。
- `comment`：选填。

#### 模板提取结果

展示 N10 模板和 N11 验证结果。

- `accuracy`：模板准确度。
- `original_reconstruction`：原句重建能力。
- `variant_coverage`：变式覆盖度。
- `slot_rationality`：槽位合理性。
- `comment`：选填。

#### 正式梗生成候选

展示 N12 候选和 N13 自评分。

候选集指标：

- `effective_difference`：候选有效差异。
- `natural_rewrite_coverage`：自然改写思路覆盖。
- `overall_selectable_quality`：整体可选择性。
- `comment`：选填。

每个 C1～C5 保留以下必填项：通顺度、原梗辨识度、凿agu融合自然度、幽默度、模板逻辑、可用性。`modification_advice` 改为选填。

#### 最终正式梗结果

展示 N14 选择依据和 N15 正式包装。

- `is_best_candidate`：是否为最佳候选。
- `better_candidate_id`：选择否时可选；若未选择则必须在模块意见中说明。
- `fluency`：通顺度。
- `original_meme_recognition`：原梗辨识度。
- `agu_zao_fit`：凿agu契合度。
- `humor`：幽默度。
- `overall_satisfaction`：整体满意度。
- `comment`：选填；仅在否且未指定更合适候选时必填。

### 6.3 问题定位与准入

- `main_problem_nodes` 必填，可选择 `NO_OBVIOUS_PROBLEM`。
- HUMAN 模式的入库决定必填。
- AUTO 模式的自动准入复核必填。
- `admission.reason` 选填。
- `overall_comment` 选填。

### 6.4 API 载荷

新评价载荷使用以下顶层字段：

```json
{
  "expected_run_version": 1,
  "branch_id": "...",
  "original_search_plan": {},
  "selected_original_meme": {},
  "variant_search_plan": {},
  "variant_search_results": {},
  "template_extraction": {},
  "candidate_generation": {
    "overall": {},
    "candidates": {}
  },
  "final_result": {},
  "main_problem_nodes": [],
  "admission": {},
  "overall_comment": ""
}
```

数据库继续使用现有 JSON 列，避免为评分分组增加无必要列：

- `processing_chain_scores_json` 保存前五个模块的具名对象。
- `candidate_set_scores_json` 保存 `candidate_generation.overall`。
- `candidate_scores_json` 保存 C1～C5。
- `final_result_scores_json` 保存最终正式梗结果。

历史旧结构不重写；读取历史评价时同时支持旧结构和新结构。

## 7. 运行状态持久化

新增统一的运行快照同步方法，并在以下时机调用：

- 创建任务后进入运行态。
- 每个节点完成或失败后。
- 进入等待人工评价、等待人工干预、暂停或恢复时。
- 修改持续执行开关时。
- 应用策略版本时。
- 任务完成、失败或终止时。

同步字段至少包括状态、当前持续执行开关、激活分支、最终策略版本、已选原始梗、已选候选和当前正式文案。节点、事件和评价仍独立保存，保持审计粒度。

## 8. 错误处理与可观察性

- N09 JSON 解析失败需记录节点、尝试次数、结束原因和安全截断后的错误摘要。
- N09/N11 回退时事件记录当前补搜次数、失败质量指标和下一节点。
- N19 输出和策略补丁在运行详情中可读展示。
- 策略补丁无效时显示具体不允许的路径或值。
- 评价提交后页面提示生成的策略版本；持续执行开启时再开始下一轮。

## 9. 测试与验收

后端测试必须覆盖：

- 首次运行创建默认策略版本。
- 人工评价产生补丁、新策略版本和当前策略状态。
- 下一轮 N07 查询包含反馈指令且审计记录使用新版本。
- N09 排除原句转载、繁简体/标点差异、释义和长上下文。
- N09 解析失败且严格兜底不足时返回 `INSUFFICIENT`。
- N11 在 28.6% 覆盖率下返回 `MORE_EVIDENCE`。
- 超过补搜预算时自动发现模式放弃当前原梗。
- 等待人工评价时数据库主记录状态正确。
- 新评价载荷可校验、落库并通过历史 API 读取。

前端测试必须覆盖：

- 七个模块和对应节点材料均显示。
- 所有评分必填。
- 模块文本意见、候选修改建议、准入理由和总体意见均可留空。
- 缺少评分时不发送提交请求并显示字段错误。
- 完整载荷字段与后端契约一致。
- 大型变式证据默认折叠，展开后页面仍可操作。

最终验证命令：

```bash
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check app tests

cd ../frontend
npm run test -- --run
npm run lint
npm run typecheck
npm run build

cd ..
git diff --check
```

## 10. 实施影响

后端开发服务使用热重载且任务只存在内存。开始修改后端代码会使当前尚未提交的第二轮评价任务失效；已持久化的节点、证据和第一轮评价保留。该限制符合当前 MVP 不恢复运行中任务的既定边界。
