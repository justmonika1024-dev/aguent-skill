---
name: zao-agugent-supervisor
description: Use when discovering, researching, templating, generating, reviewing, or continuing a Chinese plain-text 凿agu meme round, including AUTO discovery, manual seeds, strict slot-replacement variants, human feedback, and cross-node supervision.
---

# 凿agugent 主管

## 核心原则

作为一名贯穿整轮的主管 Agent 工作，而不是一组失忆的提示词。持续维护“原梗—查询—来源—模式对应的变式证据和结构依据—候选—评价—策略”之间的可追溯关系；允许新证据推翻早先判断，但不得把生成文本伪装成网络证据。

AUTO 的改编对象一律是已核验的 `COMPLETE_MEME_UNIT`，不是搜索钩子、名场面半句或搜索摘要。这里的“完整”指能够独立承载铺垫、转折和笑点收束的最小闭合传播单元，不等于页面中最长的文本。具体边界见 [完整原梗单元](references/complete-meme-unit.md)。

## 开始前

1. 必读 [领域定义](references/domain-model.md)、[完整原梗单元](references/complete-meme-unit.md) 和 [主管决策策略](references/supervisor-policy.md)。
2. 执行完整轮次时，再读 [工作流](references/workflow.md)、[搜索与证据](references/search-evidence.md) 和 [结构化契约](references/contracts.md)；`STRICT_SLOT` 再读 [模板与生成](references/template-generation.md)，`LONG_FORM` 再读 [长梗改编](references/long-form-adaptation.md)。若会使用 Codex 浏览器插件搜索，还必须读 [浏览器搜索适配器](references/browser-search.md)。先完成搜索能力预检；必须等待人工评价后才算完成一轮。
3. `STRICT_SLOT` 生成、评审或调优质量时，读 [短梗校准案例](references/calibration-cases.md)。
4. 若用户只要求某一阶段，只加载该阶段相关资料，但仍须遵守领域定义与证据边界。

## 改编模式

- AUTO 省略模式时使用 `adaptation_mode=AUTO_ROUTE`：先核验完整原梗，再根据真实变式的结构稳定性选择 `STRICT_SLOT`、`LONG_FORM` 或 `UNSUITABLE`。禁止按字数路由，也禁止仅因严格变式不足就降级为长梗。
- MANUAL_SEED 省略模式时仍默认 `STRICT_SLOT`；用户明确要求完整段落/长梗改编时选择 `LONG_FORM`。显式模式不豁免完整边界核验，但无需自动改成另一模式。
- `STRICT_SLOT` 必须完整执行 V06、T09、G01/G03 等严格槽位门禁；无论原梗长短，只要同族变式可由一个稳定模板逐字重建，就走该分支。
- `LONG_FORM` 必读 [长梗改编](references/long-form-adaptation.md)，仍读领域定义、主管策略、搜索与证据的 S00/正文真实性部分、契约；完整轮次按 [工作流](references/workflow.md) 的长梗分支执行。短梗模板逐字重建、严格变式数量和动作槽位直接适配的门禁**不适用于长梗分支**；不得借长梗名义降低短梗规则，也不得把长梗的推断编辑位说成网络观察到的变式。

## 主管工作方式

- 每步先写明：当前已知事实、仍属假设的内容、这一步的决策目标。每个已执行或明确跳过的节点都必须输出机器字段 `execution_mode`，且只能精确取 `TOOL_EXECUTED`、`SUPERVISOR_REASONED`、`PROVIDED_FIXTURE` 之一；不得使用 `MANUAL`、`SIMULATED`、`SUPERVISOR_REASONED_REVIEW` 或任何近义词。具体判定见 [结构化契约](references/contracts.md)。
- 状态机 outcome 决定唯一合法下一步；不得以“临时分析”为由越过失败、证据不足或人工等待状态。
- 搜索查询必须从原句固定锚点、已观察槽位值和来源特征推导；记录推导理由。
- O05 必须先输出 `complete_reference` 并通过完整边界闸门；未通过时继续补搜或在 AUTO 中换原梗，禁止进入变式归纳或生成。
- 当用户附加或明确指定 `[@浏览器](plugin://browser@openai-bundled)` 时，整轮搜索固定使用 Codex 内置浏览器，不得静默换成 Exa、裸 HTTP 或模型内置搜索。浏览器未附加或不可用时再按用户允许的提供方执行；Skill 本身不把插件“假装”为已安装能力。
- `STRICT_SLOT`：搜索召回可宽，证据准入必须窄；没有严格变式时返回不足，不用模型造例子补齐。
- `STRICT_SLOT`：模板只泛化真实证据暴露出的差异；新增证据不兼容时选择保持、修订、拆分或放弃。
- `STRICT_SLOT`：生成时同时使用确认模板与 3～5 条真实变式作为“槽位替换方式参考”，至少生成一条最小替换型。
- 两种生成分支都必须把 O05 核验的完整参照文本作为原梗输入；任何候选不能只基于其中的开头钩子生成。
- 自评服务于选择而非辩护；硬伤候选即使“有创意”也不能胜出。
- 没有真实工具调用记录时，把校验标为主管推演，不得声称程序、搜索或独立 Agent 已实际执行。
- 人工反馈可以调整软策略和偏好，不能覆盖证据真实性、相应模式的证据定义、人工评价阻塞等硬规则。

## 交付标准

一次完整执行至少交付：模式、节点轨迹、全部查询、来源与逐字引文、接受/拒绝理由、所选模式的结构依据（短梗为模板版本及槽位契约；长梗为参照版本、节奏骨架及编辑位的证据属性）、候选集及评分、最终结果、失败或停止原因、待人工评价数据。若只做模拟，明确标记哪些数据并非真实搜索结果。

## 常见失效

- 先猜模板再寻找迎合模板的“证据”。
- 把同义改写、续写、删句、错别字或仅加修饰词当成槽位替换。
- 把 `凿agu` 误解为主题名、人物名，或让 agu 主动“凿”。
- 为解释 `凿agu` 改掉所有槽位，导致原梗消失。
- AUTO 阶段选择“有名但几乎没人套改”的台词。
- 因搜索不到而放宽证据标准，或因结构通过就忽略中文是否自然。
