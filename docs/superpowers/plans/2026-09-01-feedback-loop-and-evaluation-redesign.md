# 人工反馈闭环与模块化评价实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让人工评价形成可审计并真实作用于下一轮节点的策略版本，同时修复变式证据、模板验证、运行状态持久化，并交付七模块结构化评价页面。

**Architecture:** 后端以 SQLite 中的策略版本为持久化真相，`RunContext` 保存当前轮快照；N19 生成建议，确定性规则补全最低质量操作，`StrategyService` 白名单校验后原子写入新版本。N07/N09/N11/N12/N13 显式消费策略；前端按七个业务模块读取当前轮最新节点输出并提交同形评价载荷。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2 async、SQLite、pytest；React 19、TypeScript、Ant Design、TanStack Query、Vitest、Testing Library。

**Spec:** `docs/superpowers/specs/2026-09-01-feedback-loop-and-evaluation-redesign.md`

## Global Constraints

- 每轮必须等待完整结构化评分；模块文本意见、候选修改建议、准入理由和总体意见均选填。
- 运行中任务只保存在内存，后端重启不恢复；所有已完成节点、证据、评价和策略版本必须落库。
- N05 后续只处理一个选定原始梗；变式证据不足时自搜索模式放弃该梗重新发现。
- 候选数固定为 C1～C5；不得修改预算、安全、候选数和状态机基本路由约束。
- 所有外部调用在自动测试中使用 Fake 或 HTTP mock，不消耗真实 API。
- 保留工作区中已有未提交改动，不重置、不覆盖无关文件。

---

### Task 1: 七模块评价后端契约

**Files:**
- Modify: `backend/app/contracts/evaluation.py`
- Modify: `backend/tests/unit/test_contracts.py`

**Interfaces:**
- Produces: `HumanEvaluationRequest`，顶层包含 `original_search_plan`、`selected_original_meme`、`variant_search_plan`、`variant_search_results`、`template_extraction`、`candidate_generation`、`final_result`、`main_problem_nodes`、`admission`、`overall_comment`。
- Produces: 所有 `comment`、`modification_advice`、`admission.reason`、`overall_comment` 默认 `""`；评分范围固定 1～5。

- [ ] **Step 1: 将现有契约测试改写为七模块失败测试**

```python
def module_score(**values):
    return {**values, "comment": ""}


def test_evaluation_requires_all_seven_modules_but_allows_empty_text_feedback():
    candidate = {
        "fluency": 4, "original_meme_recognition": 4,
        "agu_zao_naturalness": 4, "humor": 4, "template_logic": 4,
        "usability": "USABLE", "modification_advice": "",
    }
    payload = {
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
    request = HumanEvaluationRequest(**payload)
    assert request.variant_search_results.comment == ""
    assert request.candidate_generation.candidates["C1"].modification_advice == ""
```

- [ ] **Step 2: 运行测试并确认因旧字段契约失败**

Run: `cd backend && .venv/bin/pytest tests/unit/test_contracts.py::test_evaluation_requires_all_seven_modules_but_allows_empty_text_feedback -q`

Expected: FAIL，提示 `original_search_plan` 等字段未定义或 `processing_chain` 缺失。

- [ ] **Step 3: 实现具名模块 Pydantic 模型**

实现 `OriginalSearchPlanScores`、`SelectedOriginalMemeScores`、`VariantSearchPlanScores`、`VariantSearchResultsScores`、`TemplateExtractionScores`、`CandidateGenerationScores`。保留 `CandidateScores` 和 `FinalResultScores`，将文本字段设为 `str = ""`。`FinalResultScores` 继续执行“否且未指定候选时必须填写 comment”的交叉校验。

- [ ] **Step 4: 添加非法评分和候选集合测试并运行通过**

断言任一评分为 0 或 6 时 `ValidationError`，候选不是完整 C1～C5 时 `ValidationError`。

Run: `cd backend && .venv/bin/pytest tests/unit/test_contracts.py -q`

- [ ] **Step 5: 提交本任务**

```bash
git add backend/app/contracts/evaluation.py backend/tests/unit/test_contracts.py
git commit -m "feat: define modular human evaluation contract"
```

---

### Task 2: 策略版本仓储与运行快照同步

**Files:**
- Modify: `backend/app/services/strategy.py`
- Modify: `backend/app/db/persistence.py`
- Modify: `backend/app/workflow/context.py`
- Modify: `backend/app/workflow/engine.py`
- Modify: `backend/tests/integration/test_persistence.py`
- Modify: `backend/tests/integration/test_workflow.py`

**Interfaces:**
- Produces: `default_strategy() -> dict[str, Any]`。
- Produces: `SQLiteRepository.ensure_active_strategy() -> tuple[str, dict[str, Any]]`。
- Produces: `SQLiteRepository.apply_strategy_patch(...) -> tuple[str, dict[str, Any]]`。
- Produces: `SQLiteRepository.sync_run_snapshot(context) -> None`。
- Consumes: `StrategyPatch.operations` 或持久化载荷 `patch_operations`，支持对象字段 `add/replace` 和数组末尾路径 `/-`。

- [ ] **Step 1: 写策略初始化、补丁持久化和等待评价状态红测**

```python
@pytest.mark.asyncio
async def test_repository_versions_strategy_and_syncs_waiting_state(tmp_path):
    repo = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'strategy.db'}")
    version_id, strategy = await repo.ensure_active_strategy()
    assert strategy["search"]["minimum_template_coverage"] == 0.6
    after_id, after = await repo.apply_strategy_patch(
        source_run_id="run-1", evaluation_id="eval-1",
        before_version_id=version_id,
        patch={
            "feedback_summary": "变式转载过多",
            "affected_nodes": ["N07", "N09"],
            "patch_operations": [{
                "op": "add", "path": "/search/variant_query_directives/-",
                "value": "排除原句转载",
            }],
            "next_round_hypotheses": ["真实变式比例提升"],
        },
    )
    assert after_id != version_id
    assert after["search"]["variant_query_directives"] == ["排除原句转载"]
```

另写引擎测试：运行到 N17 后查询 `RunRecord.status` 必须是 `WAITING_HUMAN_EVALUATION`，并且 `continuous_enabled` 与内存一致。

- [ ] **Step 2: 运行红测**

Run: `cd backend && .venv/bin/pytest tests/integration/test_persistence.py -k 'strategy or waiting_state' -q`

Expected: FAIL，方法不存在或数据库状态仍为 `WAITING_START`。

- [ ] **Step 3: 扩展 StrategyService**

实现默认策略常量、深拷贝返回、路径解析、数组 `/-` 追加、指令去重、布尔值和阈值范围校验。允许路径仅限 `search`、`generation`、`evaluation`、`admission`，继续禁止 `budgets`、`safety`、`candidate_count`、`routes`。

- [ ] **Step 4: 实现策略仓储事务**

`ensure_active_strategy()` 在空库中创建版本 1 和 `RunStrategyState(id=1)`；已有状态时读取激活版本。`apply_strategy_patch()` 在一个事务中校验父版本、生成版本号、写 `RunStrategyVersion`、写 `RunStrategyPatch` 并更新 `RunStrategyState`。

- [ ] **Step 5: 让 WorkflowEngine 初始化和同步策略**

`start_run()` 在创建 `RunContext` 前从仓储加载策略，将 ID 和快照写入上下文。新增 `_sync_context()`，在创建后进入运行态、命令接受、节点完成/失败、进入等待评价、暂停/恢复、完成/终止时调用 `sync_run_snapshot()`。

- [ ] **Step 6: 运行聚焦测试和完整持久化测试**

Run: `cd backend && .venv/bin/pytest tests/integration/test_persistence.py tests/integration/test_workflow.py -q`

- [ ] **Step 7: 提交本任务**

```bash
git add backend/app/services/strategy.py backend/app/db/persistence.py backend/app/workflow/context.py backend/app/workflow/engine.py backend/tests/integration/test_persistence.py backend/tests/integration/test_workflow.py
git commit -m "feat: persist strategy versions and live run snapshots"
```

---

### Task 3: N19 评价翻译与下一轮策略应用

**Files:**
- Modify: `backend/app/workflow/real_registry.py`
- Modify: `backend/app/workflow/engine.py`
- Modify: `backend/tests/integration/test_real_registry.py`
- Modify: `backend/tests/integration/test_workflow.py`

**Interfaces:**
- Produces: N19 artifact 包含 `feedback_summary`、`affected_nodes`、`patch_operations`、`score_gaps`、`next_round_hypotheses`、`before_strategy_version_id`、`after_strategy_version_id`。
- Produces: `derive_required_patch_operations(evaluation, llm_patch) -> list[dict[str, Any]]`。
- Consumes: 七模块评价；低于 4 分的变式搜索计划/结果和模板模块触发确定性搜索质量指令。

- [ ] **Step 1: 写 N19 补丁派生红测**

```python
def test_low_variant_scores_force_search_quality_patch():
    evaluation = {
        "variant_search_plan": {
            "slot_replacement_targeting": 2, "query_diversity": 3,
            "ugc_orientation": 2, "noise_avoidance": 2,
            "comment": "结果基本都是原句转载",
        },
        "variant_search_results": {
            "relevance": 3, "real_variant_ratio": 1,
            "independent_evidence_quality": 2, "variant_diversity": 2,
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
```

- [ ] **Step 2: 写连续两轮策略消费红测**

使用 Fake N19 输出一个合法补丁，提交第一轮评价并让持续执行进入第二轮；断言第二轮 N07 节点执行记录的 `strategy_version_id` 等于新版本，N07 输出 `applied_directives` 包含第一轮意见。

- [ ] **Step 3: 运行红测**

Run: `cd backend && .venv/bin/pytest tests/integration/test_real_registry.py tests/integration/test_workflow.py -k 'patch or next_round_strategy' -q`

- [ ] **Step 4: 扩展 N19 提示与输出校验**

要求 LLM 输出 `patch_operations` 和 `score_gaps`。程序合并 LLM 建议与确定性操作；过滤重复指令并将用户文本限制为安全长度。N19 自身不直接写数据库，而由引擎在节点成功后调用仓储原子应用。

- [ ] **Step 5: 引擎应用补丁并更新上下文**

N19 `PATCH_VALID` 前应用补丁；失败时将 outcome 改为 `PATCH_INVALID` 并保留具体错误。成功时更新 `context.strategy_version_id`、`context.strategy_snapshot` 和 N19 artifact 的前后版本号，再持久化节点执行。

- [ ] **Step 6: 运行聚焦与完整工作流测试**

Run: `cd backend && .venv/bin/pytest tests/integration/test_real_registry.py tests/integration/test_workflow.py -q`

- [ ] **Step 7: 提交本任务**

```bash
git add backend/app/workflow/real_registry.py backend/app/workflow/engine.py backend/tests/integration/test_real_registry.py backend/tests/integration/test_workflow.py
git commit -m "feat: apply human feedback to next-round strategy"
```

---

### Task 4: 变式搜索、严格抽取和有界回退

**Files:**
- Modify: `backend/app/workflow/real_registry.py`
- Modify: `backend/app/workflow/transitions.py`
- Modify: `backend/app/workflow/context.py`
- Modify: `backend/app/providers/llm.py`
- Modify: `backend/tests/contract/test_providers_nodes.py`
- Modify: `backend/tests/integration/test_real_registry.py`
- Modify: `backend/tests/integration/test_workflow.py`

**Interfaces:**
- Produces: N07 `planning_mode="STRATEGY_GUIDED"`、`strategy_version_id`、`applied_directives`、带 `strategy_origin` 的查询。
- Produces: `is_substantive_variant(original, candidate, anchors) -> bool`。
- Produces: N09 最多 8 条严格变式；不足时 outcome `INSUFFICIENT`。
- Produces: `RunContext.loop_counters["variant_search:<original>"]`，最多 2 次补搜。

- [ ] **Step 1: 写变式分类表驱动红测**

```python
@pytest.mark.parametrize(("candidate", "expected"), [
    ("我猜中了开头，却猜不中这结局", False),
    ("我猜中了開頭，卻猜不中這結局", False),
    ("我猜中了开头，却猜不中这结局是什么意思", False),
    ("句子赏析：我猜中了开头，却猜不中这结局", False),
    ("我猜中了开头，却猜不中agu被谁凿了", True),
])
def test_substantive_variant_filter(candidate, expected):
    assert is_substantive_variant(
        "我猜中了开头，却猜不中这结局", candidate,
        ["我猜中了", "却猜不中"],
    ) is expected
```

- [ ] **Step 2: 写 N09 严格兜底不足红测**

让 LLM 连续解析失败，N08 只包含原句、繁体和释义；断言 N09 返回 `INSUFFICIENT`，而不是 `SUFFICIENT`。

- [ ] **Step 3: 写 N07 策略查询红测**

给上下文注入 `prefer_ugc_sources=true` 和一条 `variant_query_directives`；断言查询不再五条固定模板全量复用，至少一条 purpose 为槽位替换、一条为 UGC 方向，且输出列出已应用指令。

- [ ] **Step 4: 运行红测**

Run: `cd backend && .venv/bin/pytest tests/integration/test_real_registry.py -k 'substantive_variant or strict_fallback or strategy_query' -q`

- [ ] **Step 5: 实现策略引导 N07**

保留一条精确原句基线查询，其余查询由固定锚点、替换语境、UGC 方向和反馈指令组合。每条查询附 `strategy_origin`；验证 4～6 条、至少两个锚点和至少一个非完整原句查询。

- [ ] **Step 6: 缩小 N09 结构化请求并增强解析诊断**

最多向 LLM 提供 8 个来源、每个来源有限摘要，提示最多输出 8 条。`DeepSeekChatProvider` 的 JSON 解析异常加入 `finish_reason`、原始响应字符数和安全截断尾部，不记录认证信息。

- [ ] **Step 7: 实现严格变式过滤和充分性**

统一标准化简繁常见字、标点和空白；排除完整原句、标题/释义包裹和高相似无槽位变化。规则兜底与 LLM 输出通过同一验证函数。有效条数和独立来源数同时达标才返回 `SUFFICIENT`。

- [ ] **Step 8: 实现有界回退**

在引擎处理 N09 `INSUFFICIENT` 和 N11 `MORE_EVIDENCE` 时增加当前原始梗计数。未超上限走 N07；超上限时 AUTO_DISCOVERY 产生 `ABANDON_ORIGINAL` 并走 N02，MANUAL_SEED 进入人工干预。事件包含计数、门槛和回退原因。

- [ ] **Step 9: 运行 Provider、节点和工作流测试**

Run: `cd backend && .venv/bin/pytest tests/contract/test_providers_nodes.py tests/integration/test_real_registry.py tests/integration/test_workflow.py -q`

- [ ] **Step 10: 提交本任务**

```bash
git add backend/app/workflow/real_registry.py backend/app/workflow/transitions.py backend/app/workflow/context.py backend/app/providers/llm.py backend/tests/contract/test_providers_nodes.py backend/tests/integration/test_real_registry.py backend/tests/integration/test_workflow.py
git commit -m "fix: require substantive variant evidence"
```

---

### Task 5: 模板验证与候选自评分门槛

**Files:**
- Modify: `backend/app/workflow/real_registry.py`
- Modify: `backend/tests/integration/test_real_registry.py`

**Interfaces:**
- Produces: N11 `coverage`、`accuracy`、`matched_variant_count`、`problems` 基于真实验证推导。
- Produces: 低覆盖返回 `MORE_EVIDENCE`，模板不可重建返回 `REEXTRACT`。
- Produces: N13 在明显不通顺结构存在时强制候选不合格。

- [ ] **Step 1: 写 28.6% 覆盖率不得通过红测**

构造 20 条严格变式，仅 5 条匹配模板；策略门槛为 0.6。断言 N11 outcome 为 `MORE_EVIDENCE`、`accuracy < 5` 且 `problems` 非空。

- [ ] **Step 2: 写明显不通顺候选红测**

N13 的模型输出把“我猜中了开头，却猜不中这凿agu”评为高分合格；程序后校验必须把 `fluency` 限制到阈值以下、`qualified=false`，并在 `problems` 或评分理由中说明指示结构不通顺。

- [ ] **Step 3: 运行红测**

Run: `cd backend && .venv/bin/pytest tests/integration/test_real_registry.py -k 'coverage_threshold or awkward_candidate' -q`

- [ ] **Step 4: 实现 N11 决策推导**

先验证原句重建，再计算严格变式覆盖率；低于策略门槛返回 `MORE_EVIDENCE`，无有效模板返回 `REEXTRACT`，其余才 `PASS`。`accuracy` 从原句重建、覆盖率和槽位证据换算到 1～5。

- [ ] **Step 5: 实现 N13 后校验**

增加最小的明显语病规则：指示词“这”不能直接修饰裸动作事件短语；动作受事仍必须是 agu。后校验只降级明确违规项，不重写候选。

- [ ] **Step 6: 运行完整节点测试**

Run: `cd backend && .venv/bin/pytest tests/integration/test_real_registry.py -q`

- [ ] **Step 7: 提交本任务**

```bash
git add backend/app/workflow/real_registry.py backend/tests/integration/test_real_registry.py
git commit -m "fix: enforce template and candidate quality gates"
```

---

### Task 6: 新评价载荷落库、历史兼容与策略 API

**Files:**
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/db/persistence.py`
- Modify: `backend/tests/integration/test_historical_api.py`
- Modify: `backend/tests/integration/test_persistence.py`

**Interfaces:**
- Consumes: `HumanEvaluationRequest` 作为 `/runs/{run_id}/evaluation` 请求模型。
- Produces: 历史 API 的新评价记录包含七模块具名字段；旧 JSON 记录仍按旧字段返回。
- Produces: `GET /strategies` 返回版本摘要，`GET /strategies/{id}` 返回策略快照和来源补丁。

- [ ] **Step 1: 写新载荷落库红测**

通过 API 提交完整七模块评价，读取 `/record` 后断言：

```python
evaluation = record["evaluations"][0]
assert evaluation["original_search_plan"]["anchor_accuracy"] == 4
assert evaluation["variant_search_results"]["comment"] == ""
assert evaluation["candidate_generation"]["candidates"]["C5"]["usability"] == "USABLE"
```

- [ ] **Step 2: 写策略 API 红测**

创建初始版本和一个补丁后，断言 `/api/v1/strategies` 返回两个版本且仅一个 active，详情接口返回完整 `strategy`、`feedback_summary` 和 `affected_nodes`。

- [ ] **Step 3: 运行红测**

Run: `cd backend && .venv/bin/pytest tests/integration/test_historical_api.py tests/integration/test_persistence.py -k 'modular_evaluation or strategy_api' -q`

- [ ] **Step 4: 实现评价请求校验和 JSON 列映射**

路由使用 `HumanEvaluationRequest`，调用 `model_dump()` 后交给引擎。仓储把前五模块保存进 `processing_chain_scores_json`，候选总体和单条分别保存到现有列；读取时识别具名新结构并重组七模块响应，旧结构保持原返回格式。

- [ ] **Step 5: 实现只读策略 API**

替换当前空列表和固定 404；运行中仍禁止激活其它版本，非活动状态允许激活已存在版本并更新 `run_strategy_state`。

- [ ] **Step 6: 运行历史、持久化和 API 测试**

Run: `cd backend && .venv/bin/pytest tests/integration/test_historical_api.py tests/integration/test_persistence.py tests/integration/test_workflow.py -q`

- [ ] **Step 7: 提交本任务**

```bash
git add backend/app/api/router.py backend/app/db/persistence.py backend/tests/integration/test_historical_api.py backend/tests/integration/test_persistence.py
git commit -m "feat: persist and expose modular evaluations"
```

---

### Task 7: 前端评价 schema 与七模块材料组件

**Files:**
- Modify: `frontend/src/features/evaluation/schema.ts`
- Modify: `frontend/src/features/evaluation/schema.test.ts`
- Create: `frontend/src/features/evaluation/EvaluationModuleCard.tsx`
- Create: `frontend/src/features/evaluation/RunArtifactSummary.tsx`
- Create: `frontend/src/features/evaluation/RunArtifactSummary.test.tsx`
- Modify: `frontend/src/features/evaluation/CandidateEvaluationCard.tsx`

**Interfaces:**
- Produces: 与后端新契约同形的 `EvaluationFormValues` 和 `HumanEvaluationPayload`。
- Produces: `latestNodeArtifact(nodes, nodeKey)`，只返回当前轮最后一次执行。
- Produces: `EvaluationModuleCard`，统一显示标题、说明、节点材料、评分和选填意见。

- [ ] **Step 1: 写新 payload 红测**

构造七模块表单值，断言 `buildEvaluationPayload()` 保留所有模块、将 `better_candidate_id` 标准化为 `null`、AUTO/HUMAN 准入字段互斥，空意见仍提交空字符串。

- [ ] **Step 2: 写材料摘要红测**

输入两轮 N03/N05/N09 节点，断言只显示最后一轮材料；N09 显示有效变式文本和链接，N08 大正文默认不渲染，点击“展开证据”后才出现摘要。

- [ ] **Step 3: 运行红测**

Run: `cd frontend && npm run test -- --run src/features/evaluation/schema.test.ts src/features/evaluation/RunArtifactSummary.test.tsx`

- [ ] **Step 4: 实现 TypeScript 契约与模块字段常量**

按设计文档定义七组指标常量和嵌套类型；`comment`、`modification_advice`、`reason`、`overall_comment` 均允许空字符串。

- [ ] **Step 5: 实现统一模块卡和材料摘要**

模块卡接收节点键、评分字段和表单路径。材料摘要针对 N03/N05/N07/N08/N09/N10/N11/N12/N13/N14/N15 提供简洁显示；搜索结果只显示标题、URL、短摘要和折叠详情。

- [ ] **Step 6: 修改候选卡文本规则**

移除 `modification_advice` 的 required rule，保留六项结构化必填评价。

- [ ] **Step 7: 运行组件测试、Lint 和类型检查**

Run: `cd frontend && npm run test -- --run src/features/evaluation && npm run lint && npm run typecheck`

- [ ] **Step 8: 提交本任务**

```bash
git add frontend/src/features/evaluation
git commit -m "feat: add modular evaluation components"
```

---

### Task 8: 七模块评价页面与提交流程

**Files:**
- Modify: `frontend/src/pages/EvaluationPage.tsx`
- Modify: `frontend/src/pages/EvaluationPage.test.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: Task 7 的七模块字段、`EvaluationModuleCard`、`RunArtifactSummary`。
- Produces: 七模块完整评分表；文本意见选填；缺失评分时 Form 标记字段且不发送 POST。

- [ ] **Step 1: 写七模块显示红测**

Fixture 提供 N03、N05、N07、N08、N09、N10、N11、N12、N13、N14、N15。断言页面存在以下标题：

```typescript
for (const title of [
  '原始梗搜索计划', '最终选定原始梗', '变式搜索计划',
  '最终变式搜索结果', '模板提取结果', '正式梗生成候选', '最终正式梗结果',
]) expect(await screen.findByText(title)).toBeInTheDocument()
```

- [ ] **Step 2: 写选填意见和必填评分红测**

空表单点击提交不得 POST；填完所有评分、候选可用性、问题节点和准入决定，但所有文本框留空，点击提交必须产生一次 POST，载荷的文本字段为空字符串。

- [ ] **Step 3: 运行红测**

Run: `cd frontend && npm run test -- --run src/pages/EvaluationPage.test.tsx --testTimeout=15000`

- [ ] **Step 4: 重组评价页**

按七个模块顺序渲染；每个模块先显示相关材料，再显示评分和选填意见。候选模块显示 N12 文案、N13 自评分和人工评分。最终模块显示 N14 选择与 N15 正式文案。

- [ ] **Step 5: 更新问题定位和准入规则**

保留 `main_problem_nodes` 和准入选择 required；移除 `admission.reason`、`overall_comment` 的 required；`is_best_candidate=false` 且无替代候选时才要求最终模块 comment。

- [ ] **Step 6: 补充长证据和窄屏样式**

证据卡限制首屏高度，链接和长文本可换行，sticky 提交栏不遮挡最后一个表单错误。

- [ ] **Step 7: 运行评价页和完整前端测试**

Run: `cd frontend && npm run test -- --run && npm run lint && npm run typecheck && npm run build`

- [ ] **Step 8: 提交本任务**

```bash
git add frontend/src/pages/EvaluationPage.tsx frontend/src/pages/EvaluationPage.test.tsx frontend/src/styles/global.css
git commit -m "feat: redesign evaluation page around workflow modules"
```

---

### Task 9: 全链路回归与真实两轮验收

**Files:**
- Modify: `backend/tests/integration/test_workflow.py`
- Modify: `frontend/src/pages/RunDetailPage.test.tsx`
- Modify: `backend/README.md`
- Modify: `frontend/README.md`

**Interfaces:**
- Produces: Fake Provider 自动化两轮测试，证明第一轮评价产生策略版本且第二轮 N07 消费该版本。
- Produces: 真实 API 人工触发验收记录，不把外部效果作为单元测试前提。

- [ ] **Step 1: 增加完整两轮自动化验收测试**

测试流程：AUTO_DISCOVERY + continuous=true → 第一轮等待评价 → 提交低变式评分 → N19 新版本 → 第二轮 N07 → 关闭持续执行 → 第二轮等待评价。断言策略版本递增、查询计划包含反馈、两轮评价和节点记录可从历史 API 读取。

- [ ] **Step 2: 运行后端全部测试和静态检查**

```bash
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check app tests
```

- [ ] **Step 3: 运行前端全部测试和构建**

```bash
cd frontend
npm run test -- --run
npm run lint
npm run typecheck
npm run build
```

- [ ] **Step 4: 运行差异检查**

Run: `git diff --check`

- [ ] **Step 5: 使用当前 `.env` 执行一轮种子和两轮连续自搜索真实冒烟**

只在自动化验证全部通过后执行。检查：真实 Exa 结果、N09 严格变式、N11 门槛、评价落库、策略版本、下一轮 N07 `applied_directives`、运行主记录状态。真实调用失败时保留响应错误和已验证边界，不用 Fake 结果冒充真实成功。

- [ ] **Step 6: 更新启动和验收说明**

README 说明策略版本、七模块评价、文本意见选填、变式补搜上限，以及后端重启会丢失活动任务。

- [ ] **Step 7: 最终提交**

```bash
git add backend/README.md frontend/README.md backend/tests/integration/test_workflow.py frontend/src/pages/RunDetailPage.test.tsx
git commit -m "test: verify adaptive two-round workflow"
```

## 计划自检结果

- 规格中的反馈闭环、策略持久化、节点消费、变式严格性、模板门槛、候选评分、七模块页面、旧记录兼容和运行状态同步均有对应任务。
- 新增接口在首次出现的任务中定义，后续任务使用相同命名。
- 不新增数据库评分列；新旧评价通过现有 JSON 列兼容。
- 所有生产行为修改均有先失败、后实现、再全量验证步骤。
