# 精简搜索执行与会话交接

## 目标与入口

在能启动隔离 Codex CLI 会话并提供搜索适配器的 CLI/API 环境中，使用外层程序：

```bash
python3 .agents/skills/zao-agugent-supervisor/scripts/compact_round_runner.py \
  --mode AUTO \
  --workdir /absolute/run-dir \
  --skill-root .agents/skills/zao-agugent-supervisor
```

人工种子增加 `--mode MANUAL_SEED --seed '原梗文本'`；显式长梗增加 `--adaptation-mode LONG_FORM`。外层程序自身不调用模型，标记 `orchestrator_kind=PROGRAMMATIC_NO_LLM_PARENT`。

**禁止由 LLM 主管会话递归启动并轮询**短生命周期子 CLI。真实实验中，网页上下文虽被隔离，父主管却在等待期间反复携带全部历史，导致总 raw Token 从旧版约 536 万上升到约 970 万。调用者应直接等待普通程序进程；最终主管只在搜索完成后启动一次。

无法从外层启动隔离会话时，可以回退单会话并记录 `search_execution_mode=SINGLE_SESSION_FALLBACK` 和原因，但不能声称取得本方案的 Token 优化效果，也不能更换用户指定的搜索提供方。

## 编排

```mermaid
flowchart LR
    D[一次性候选规划器] --> B[边界 worker]
    B --> V[首批变式 worker]
    V --> P[程序聚合与差异覆盖]
    P --> C[一次性覆盖审查器]
    C -->|MICRO| M[定向 micro-worker]
    M --> P
    C -->|PASS| G[全新无网络最终主管]
    G --> H[等待人工评价]
```

- 外层程序：维护候选循环和预算、启动/等待各会话、运行聚合脚本、在所有会话结束后汇总 Token；不做语言判断。
- 候选规划器：AUTO 才运行；给出 3～5 个具体钩子、两条疑似变式和凿agu映射假设，全部标 `HYPOTHESIS_NOT_EVIDENCE`。MANUAL_SEED 跳过。
- 边界 worker：只核验一个 `COMPLETE_MEME_UNIT`。
- 首批变式 worker：只发现并逐字核验变式；严格变式和宏观节奏变式分栏。
- 覆盖审查器：只读取不超过 16KB 的精简包，输出 PASS/MICRO/UNSUITABLE；不联网。
- 定向 micro-worker：只验证一个覆盖缺口的最多两条查询。
- 最终主管：只读取精简包、覆盖计划和失败候选摘要，加载完整 Skill，完成归纳、生成和 H02；禁止联网、禁止启动子会话。

搜索 worker **不得加载完整 Skill**。它们只接收本阶段紧凑契约和上游 JSON 路径，避免重复加载参考文档，也防止越级提取模板或生成。

## 产物

```text
search-handoff/
  discovery-result.json              # AUTO 才有
  boundary-result.json
  variants-initial-result.json
  compact-evidence-package.json
  coverage-plan.json
  variants-micro-result.json          # 需要时才有
  *-events.jsonl
  *-stderr.log
run-result.json
search-records.json
final.md
metrics.json
```

JSONL 和页面调试文件可保留供审计，但最终主管不得读取它们。最终主管只接收精简包、覆盖计划和失败摘要。

## 搜索输出上限

### 边界 worker

- 最多 3 个查询、3 个来源页；结果不超过 8KB。
- 搜索卡片最多 8 条，每条 snippet 最多 160 字。
- 来源仅读取命中附近 700～1600 字连续块；禁止 `browser_snapshot` 和整页 `body.innerText`。
- VERIFIED 必须含完整原梗、边界理由、来源标题、URL、定位和逐字文本。

### 首批变式 worker

- 最多 4 个查询、4 个来源页；结果不超过 12KB，严格与节奏变式各最多 4 条。
- 从完整原句、相隔固定锚点、改编/版本词和聚合来源召回，不先猜模板。
- `accepted_variants` 只放严格连续槽位替换；有增删或扩写的放 `rhythm_variants`，不能混入严格计数。
- 每条必须含 `verbatim_text/source_url/source_title/locator/content_group/acceptance_reason`，并逐字存在于已打开正文。`content_group` 表示独立发布内容而非语义类别；同一 URL 的多个例句只能算一个内容组，聚合脚本会再次强制合并。

### 定向 micro-worker

- 最多 2 个查询、2 个来源页；结果不超过 6KB，最多 3 条严格变式。
- 中文精确短句显式使用 `https://www.baidu.com/s?wd=...`；本轮不得静默切换或重定向到 Google/Bing。
- 模型提出的值标 `RETRIEVAL_HYPOTHESIS`。**检索假设不是证据**；来源正文核验前不能成为观察值、模板槽位或生成参考。
- 优先短、句法同型、长度接近的查询假设；拒绝普通长句偶然匹配、释义和摘要命中。

## 程序化聚合与差异覆盖

外层调用：

```bash
python3 scripts/compact_search_handoff.py build \
  --boundary search-handoff/boundary-result.json \
  --worker search-handoff/variants-initial-result.json \
  --output search-handoff/compact-evidence-package.json
```

增加 micro 结果时追加一个 `--worker`。脚本负责：

1. 校验 VERIFIED 原梗和来源绑定；
2. 校验变式字段、规范化去重、最多保留 5 条；
3. 删除 DOM、页面正文、摘要和其他噪声字段；
4. 计算真实 `observed_change_spans`；
5. 保持精简包不超过 16KB。

程序差异不是提前提取模板。覆盖审查器结合原句句法输出 1～3 个 `generation_value_targets`，说明动作/事件、受事者、施事者或关键判断位置是否有真实差异覆盖。

STRICT_SLOT 的停止条件是原句之外至少 2 条非重复严格变式、至少 2 个内容组，并且至少一个适合承载凿agu的高价值位置有真实差异覆盖；差异值还须保持句法和节奏，不能是长句偶然匹配。已有两条但内容组不足或高价值位置未覆盖时可运行一次 micro；只有一条时不进入低收益 micro。复审仍不通过则 AUTO 换原梗、MANUAL_SEED 等待人工。LONG_FORM 不要求槽位覆盖，但仍使用短 worker 与精简交接。

## 最终主管接续

最终主管复核来源绑定、证据分类、去重、内容组数和覆盖计划。搜索事实标 `execution_mode=TOOL_EXECUTED` 并引用 worker 结果/JSONL，不能冒称本会话亲自搜索；程序聚合同样引用具体命令和输出。

模板、槽位契约、生成和评分只在这个全新无网络会话完成。它不得重新打开网页、读取全量事件日志或为了“更放心”扩大上下文；交接字段缺失时由外层程序重跑对应阶段。

形成正式梗后必须停在 `WAITING_HUMAN_EVALUATION`，不能代填人工评价、入库或进入下一轮。

## Token 与时间

每个阶段 JSONL 必须有最终 `turn.completed.usage`。外层程序在最终主管退出后读取各文件最后一个真实 usage，汇总 raw input、cached input、非缓存 input、output、reasoning output、会话数及墙钟时间到 `metrics.json`。

任何 LLM 会话不得读取自己的 JSONL、等待自己的 `turn.completed` 或估算自身 Token。外层必须统计所有候选失败、micro、审查和最终会话，不能只报告最便宜的部分。与旧版比较时固定模式和提供方，同时比较 raw、非缓存、质量与终态。

## 失败处理

| 现象 | 处理 |
|---|---|
| 阶段无 `turn.completed` 或结果 JSON | 阶段失败；保留 stderr，不把半成品当证据 |
| 边界未核验 | AUTO 换具体钩子；MANUAL_SEED 等待来源/fixture 授权 |
| 无合格变式 | AUTO 换候选；MANUAL_SEED 等待人工 |
| 数量够但高价值位置未覆盖 | 定向 micro 后重审一次 |
| micro 只命中普通长句 | 拒绝，不算覆盖 |
| Google 429 / Bing 泛化 | 中文精确短句显式使用百度，不重复浪费查询 |
| 精简包缺字段或超过 16KB | 程序失败；修复 worker 输出，禁止主管脑补 |
| 隔离 CLI 或搜索适配器不可用 | 显式回退单会话或按用户指定提供方阻塞 |
