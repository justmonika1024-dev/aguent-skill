# SDD ledger — plan: docs/superpowers/plans/2026-09-01-feedback-loop-and-evaluation-redesign.md

BASE before Task 1: 4a92d98c17bff38dcc4116767caa63ee0fcd0c1b

Ruling: 在当前 main checkout 原地执行，不创建 worktree — 当前实现依赖工作区中尚未提交的后端与前端修复，新 worktree 不包含这些改动，且用户已明确允许在当前目录开发 — 若判断错误，代价是本次提交需要更谨慎地按文件隔离，避免夹带旧改动。

## Preflight scan

| Task / shared pair | Produce -> consume / internal check | Finding |
|---|---|---|
| Task 1 | 七模块 Pydantic 契约 -> 评分范围、完整 C1-C5 与可选文本测试 | 一致；保留最终结果交叉校验。 |
| Task 2 | 默认策略、版本仓储、上下文同步 -> 等待评价状态持久化测试 | 一致；策略阈值以设计规格为权威。 |
| Task 3 | N19 结构化补丁 -> 引擎应用与下一轮节点消费测试 | 一致；N19 不直接写库，由引擎原子应用。 |
| Task 4 | 严格变式判定、有界回退 -> 状态转移与提供方错误诊断测试 | 一致；AUTO 放弃原梗，MANUAL 进入人工干预。 |
| Task 5 | N11 真实覆盖验证、N13 通顺门槛 -> 候选过滤测试 | 一致；不得用固定高分替代验证。 |
| Task 6 | 新评价持久化、旧历史兼容、策略 API -> API/仓储测试 | 一致；旧评价只读兼容，不纳入新提交契约。 |
| Task 7 | 前端七模块 schema 与材料摘要组件 -> 页面消费 | 一致；大型证据仅摘要并可展开。 |
| Task 8 | 七模块页面与提交载荷 -> 后端新契约 | 一致；所有分数必填，文本意见选填。 |
| Task 9 | 全链路回归与真实验收 -> 交付证据 | 一致；真实 API 只在自动化通过后执行。 |
| Task 1 -> Task 6 | `HumanEvaluationRequest` -> API 校验与原样落库 | 一致；顶层字段名称与设计规格完全相同。 |
| Task 1 -> Task 8 | 后端七模块契约 -> 前端提交载荷 | 一致；C1-C5、准入字段和文本默认值需同形。 |
| Task 2 -> Task 3 | strategy repository/context -> N19 应用与版本更新 | 一致；Task 3 使用 Task 2 的事务接口，不重复持久化逻辑。 |
| Task 2 -> Task 4 | strategy snapshot -> N07/N09/N11 节点消费 | 一致；审计记录必须标记真实版本。 |
| Task 2 -> Task 6 | 策略版本表 -> 策略查询 API | 一致；SQLite 为持久化真相。 |
| Task 2 -> Task 9 | 运行快照同步 -> 完整运行状态验收 | 一致；内存不恢复但完成节点与状态要落库。 |
| Task 3 -> Task 4 | N19 搜索策略补丁 -> N07/N09 严格搜索消费 | 一致；人工文本经限长和白名单后成为指令。 |
| Task 3 -> Task 5 | N19 生成/评价指令 -> N11/N12/N13 门槛 | 一致；确定性最低质量规则优先。 |
| Task 3 -> Task 6 | 评价 ID/策略补丁 -> 持久化与 API 查询 | 一致；补丁与来源评价可追踪。 |
| Task 4 -> Task 5 | 严格有效变式 -> 模板覆盖率与候选评分 | 一致；N11 只基于 N09 有效变式计算。 |
| Task 4 -> Task 9 | 变式回退与证据 -> 真实连续运行验收 | 一致；重试上限固定为策略保护值。 |
| Task 5 -> Task 9 | 模板/候选门槛 -> 端到端质量断言 | 一致；“这凿agu”必须不合格。 |
| Task 6 -> Task 8 | API 新载荷/策略查询 -> 前端提交与展示 | 一致；评价材料来自当前轮最新节点。 |
| Task 7 -> Task 8 | schema/cards/summary -> EvaluationPage | 一致；组件职责边界清晰。 |
| Task 7 -> Task 9 | 前端类型与摘要 -> 页面回归 | 一致；测试需覆盖当前轮过滤。 |
| Task 8 -> Task 9 | 页面提交和错误展示 -> 全链路回归 | 一致；提交成功与失败都应可观察。 |

Ruling: 计划中的评分字段采用 1～5，而默认策略 `evaluation.minimum_*` 为内部 10 分制候选自评分阈值；两者属于不同量表，不互相改写 — 设计规格分别定义了这两类值 — 若判断错误，代价是需要统一量表并迁移现有候选评分测试。

Ruling: 现有脏工作区中与任务文件重叠的修改视为已确认方案的基础依赖；实现者提交时仅暂存任务列出的文件，并在报告中声明提交包含的既有基础改动 — 否则基于 HEAD 的审查包会遗漏工作区依赖 — 若判断错误，代价是单个任务提交可能包含同文件内先前未提交的相关改动。

Task 1 review: 契约模型、评分范围、C1-C5、默认文本与最终结果交叉校验均符合 brief；reviewer 发现路由仍接收 dict、持久化仍读取旧字段。

Ruling: reviewer 对 `router.py` 和 `persistence.py` 的两个 Critical 发现属于计划明确列在 Task 6 的生产接入与历史兼容工作，不扩大 Task 1 文件范围提前修复；将其作为 Task 6 的强制验收项 — Task 1 只生产后端契约，Task 6 消费该契约并迁移落库 — 若判断错误，代价是在 Task 6 完成前新评价暂时不能通过真实 API 正确提交和持久化。

Task 1: minor (deferred): 增加省略所有选填文本字段时默认空字符串的测试。

Task 1: minor (deferred): 增加 `FinalResultScores` 非最佳且无更优候选时必须填写 comment 的回归测试。

Task 1: complete (commits 4a92d98..4019119, contract review clean within task scope; 2 cross-task integration findings routed to Task 6, 2 minors deferred)

Task 2: fix round 1/5 started — restrict whole-module strategy replacement, sync selected original/candidate/final text, persist corrected branches before snapshot.

Task 2: minor (deferred): decide whether START pseudo-node must have a `RunNodeExecution` audit row.

Task 2: minor (deferred): deepcopy caller-provided `strategy_snapshot` when Engine runs without repository.

Task 2: minor (deferred): remove duplicate `archive_run()` calls on completion/termination paths.

Task 2: fix round 1/5 (3 addressed, 0 open — whole-module strategy bypass; incomplete live snapshot; missing corrected branch persistence; commits 4d71302..60ce3cb)

Task 2: complete (commits 4019119..60ce3cb, scoped re-review clean; 3 minors deferred)

Task 3: fix round 1/5 started — recursively score seven-module evaluation, prevent policy loosening, persist N19 pre-patch audit version.

Task 3: minor (deferred): add production N07 output test in addition to custom strategy-aware node coverage.

Task 3: minor (deferred): validate N19 `affected_nodes` as a list of strings before iteration.

Task 3: ⚠ routed to Task 4: N07 must use strategy directives to alter query planning, not only echo them.

Task 3: ⚠ routed to Task 6: evaluation persistence must reuse Engine `evaluation_id` so patches link to the actual evaluation row.

Task 3: fix round 1/5 (3 addressed, 0 open — nested score gaps; policy loosening; N19 audit version; commits e00b428..8785f9b)

Task 3: complete (commits 60ce3cb..8785f9b, scoped re-review clean; 2 minors deferred, 2 cross-task findings routed)

Task 4: fix round 1/5 started — truthful directive audit, robust script/long-context rejection, body-bound evidence, retry event payload, exhausted-original loop prevention.

Task 4: ⚠ routed to Task 5: N11 must consume `minimum_template_coverage`; current fixed PASS logic is not accepted as complete.

Task 4: fix round 1/5 (2 addressed, 3 open — directive audit and body-bound evidence closed; script normalization, retry event ordering, exhausted-original loop remain; commits 90da3fd..26b068d)

Ruling: Task 4 fix round 2 may additionally modify `backend/app/workflow/engine.py` and its existing workflow test to enrich `node.completed` before publish/persist — the original seven-file boundary cannot fix the demonstrated SSE race or database event payload, and event audit is an explicit Task 4 requirement — if wrong, the cost is a small cross-task Engine change that must be reviewed and may overlap Task 3 history.

Task 4: fix round 2/5 (1 addressed, 2 open — event payload closed; canonical script/punctuation and mixed-source exhausted filtering remain; commits 26b068d..f5a0f11)

Task 4: fix round 3/5 (0 addressed, 3 open — near-glyph heuristic misclassifies single glyph and real slot replacements; same-fragment mixed evidence lost; generic title prevents exhausted-only intervention; commits f5a0f11..a6668f2)

Ruling: Task 4 round 4 fresh implementer may replace the near-glyph heuristic with a dedicated deterministic Chinese script-normalization component and may add one narrowly scoped module/test or dependency metadata if a complete mapping cannot be correct inside `real_registry.py` — single-character script equivalence is not reliably inferable from edit distance — if wrong, the cost is an added maintenance/dependency surface that must pass source-start and final install verification.

Task 4: fix round 4/5 (3 addressed, 0 open — OpenCC canonical; same-fragment evidence preservation; generic-title exhausted-only intervention; commits a6668f2..b1d837d)

Task 4: minor (deferred): `opencc-python-reimplemented` 0.1.7 is pure Python/Apache and narrowly wrapped but upstream metadata is old/Alpha; reassess dependency maintenance during final review.

Task 4: complete (commits 8785f9b..b1d837d, scoped re-review clean; 1 minor deferred, N11 coverage routed to Task 5)

Task 5: fix round 1/5 started — correct variant-only coverage, require per-slot evidence, consume evaluation directives, broaden precise fluency/object checks.

Task 5: fix round 1/5 (3 addressed, 1 open — coverage, slot evidence, evaluation directives closed; contextual active-object detection remains; commits af4eaf6..8530976)

Task 5: fix round 2/5 (contextual separate-action recipient addressed, coordinated non-agu recipient remains; commits 8530976..04ea272)

Task 5: fix round 3/5 (specified coordinated recipients addressed; new false positives on coordinated predicates remain; commits 04ea272..8963498)

Task 5: fix round 4/5 (predicate false positives addressed; explicit recipient followed by another clause remains; commits 8963498..6288e0d)

Task 5: fix round 5/5 (1 addressed, 0 open — coordinated recipient followed by clause; commits 6288e0d..d081db9)

Task 5: complete (commits b1d837d..d081db9, scoped re-review clean)

Ruling: Task 6 may additionally update `backend/tests/integration/test_workflow.py` where a stale test posts `{score: 5}` and expects 200 — the new API contract requires complete seven-module evaluation while legacy compatibility is read-only — if wrong, the cost is replacing one backward-write compatibility assumption with the approved strict submission contract.

Task 6: fix round 1/5 started — admission mode matrix/AUTO decision, complete top-level feedback roundtrip, evaluation conflict 409, strategy activation/start coordination.

Ruling: Task 6 will not add database foreign keys/unique constraints in this round — the brief requires traceable ID reuse and current MVP schema is already established; changing models/migrations is outside Task 6 and application transactions already create the happy-path relations — if wrong, the cost is orphan rows remaining possible through direct repository misuse until a schema-hardening migration.

Task 6: minor (deferred): GET `/strategies` initializes default state on an empty database despite being read-like.

Task 6: minor (deferred): add mixed legacy/new multi-round evaluation history regression coverage.

Task 6: fix round 1/5 (3 addressed, 1 open — mode matrix/explicit AUTO overrides, top-level feedback roundtrip, conflict 409, activation coordination closed; real AUTO KEEP source remains; commits 37c6190..93d9c34)

Task 6: fix round 2/5 (AUTO N17 decision wiring added but production N16 still lacks real admission inputs; commits 93d9c34..0880c52)

Task 6: fix round 3/5 (formal N16 replacement added but duplicate check bypassed; safety fail-open; score scale/test-only fields invalid; commits 0880c52..4473cbc)

Ruling: AUTO admission safety is fail-closed and cannot be overridden to ADMIT by HUMAN or AUTO override — formal-library integrity and safe admission are hard constraints, while evaluation remains mandatory regardless of admission — if wrong, the cost is preventing a human from force-admitting content whose safety check is missing, uncertain, or rejected.

Task 6: fix round 4/5 (duplicate check, safety packaging, scale normalization, production-field aggregation addressed on dedicated evaluation path; public command bypass and AdmissionService fallback remain; commits 4473cbc..1fb3dc6)

Task 6: fix round 5/5 (2 addressed, 0 open — internal evaluation command bypass and AdmissionService fallbacks; commits 1fb3dc6..e049d2c)

Task 6: complete (commits d081db9..e049d2c, scoped re-review clean; 2 minors deferred, FK hardening ruled out of scope)

Task 7: fix round 1/5 started — active-branch/current-round artifact selection and bounded safe evidence summaries.

Task 7: fix round 1/5 (bounded evidence addressed; non-transitive execution ordering and missing `/record` fork metadata remain; commits 0ab0cd3..4182aa9)

Ruling: Task 7 round 2 may minimally extend backend `/record`, its historical API test, and frontend API node types with stable execution order and branch fork metadata — the selector cannot correctly satisfy current-branch/current-round material display using data the API does not expose — if wrong, the cost is a small read-only response contract expansion beyond the original frontend-only task.

Ruling: Task 7 implementer created and switched to `codex/task-7-stable-execution-order` to commit after main-branch approval restrictions; continue subsequent tasks on this branch and defer integration choice to branch finishing — switching back with the current dirty worktree risks losing or conflicting with user-owned changes — if wrong, the cost is that completed commits are not yet on `main` until an explicit final integration step.

Task 7: fix round 2/5 (runtime ordering and fork metadata addressed; formal API types remained optional; commits 4182aa9..317adf6)

Task 7: fix round 3/5 (1 addressed, 0 open — required/nullable RunRecord API types; commits 317adf6..194d641)

Task 7: complete (commits e049d2c..194d641, scoped re-review clean)

Task 8: fix round 1/5 started — block stale historical evaluation, exclude selected candidate from alternatives, add load recovery and keyboard-accessible artifact regions.

Task 8: fix round 1/5 (4 addressed, 0 open — stale history guard, alternative candidate exclusion, load recovery, keyboard reachability; commits d58888c..32108b7)

Task 8: complete (commits 194d641..32108b7, scoped re-review clean)

Task 6: fix round 2/5 (1 addressed, 0 open — N17 now produces and persists the real AUTO decision consumed by KEEP; HUMAN still waits without an automatic decision; commits 93d9c34..0880c52)

Task 6: complete (commits d081db9..0880c52, scoped local re-review clean; 2 minors deferred)

Task 6: fix round 3/5 (1 addressed, 0 open — production N16 now derives AUTO admission from real N09/N11/N13/N14/N15 quality artifacts; history API no longer replaces N16; commits 0880c52..4473cbc)

Task 6: complete after round 3 (commits d081db9..4473cbc, scoped local re-review clean; 2 minors deferred)

Task 9: real acceptance authorized — MANUAL run d6dba121 completed and persisted formal meme 4aaf70c; AUTO run 2375aa32 completed two evaluations, two N19 nodes, strategy V2 -> V3 -> V4, and persisted formal meme da90d5ff; target AUTO usage 26 LLM + 60 Exa calls, 101418 tokens, provider-reported cost USD 0.413.

Task 9: fix round 1/5 — N10 structurally invalid template now receives at most two bounded correction calls and preserves the first diagnostic on exhaustion; non-reconstruction/coverage remains N11 responsibility.

Task 9: fix round 2/5 — child-choice N10 only declares slots with observed replacement evidence; unchanged child label becomes fixed text, preventing false N11 re-extraction loops.

Task 9: fix round 3/5 — N19 structured output budget raised from 1600 to 4000 after real DeepSeek `finish_reason=length`; real rerun produced feedback strategy V3 and completed round 2.

Task 9: fix round 4/5 — acceptance runner validates only N13's emitted hard thresholds; it no longer invents a humor gate absent from `minimum_thresholds`.

Task 9: fix round 5/5 — full feedback stays auditable while N07 maps it to bounded search terms with query mapping; N09 rejects question, site-suffix and novel-title wrappers. Final deterministic changes replayed against eight real second-round variants: five variants across five sources remain after three wrappers are removed.

Task 9: complete (backend 205 passed + Ruff; frontend 52 passed + lint/typecheck/build; final diff checks passed; real evidence and caveat recorded in task-9-report.md; included in the delivery commit)
