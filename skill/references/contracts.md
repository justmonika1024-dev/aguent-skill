# 主管输入输出契约

## 新对话最小输入包

调用 Skill 时提供：

```yaml
mode: AUTO | MANUAL_SEED
source_scope: COMPLETE_MEME_UNIT # AUTO 固定值
adaptation_mode: AUTO_ROUTE | STRICT_SLOT | LONG_FORM # AUTO 省略时 AUTO_ROUTE；MANUAL_SEED 省略时 STRICT_SLOT
seed: null | {title, text, source_url?, notes?}
formal_meme_titles: []
strategy:
  version: string
  directives: []
limits:
  max_search_calls: number
  max_template_expansion_rounds: number
  continuous_execution: boolean
tools:
  search_available: boolean
  source_page_fetch_available: boolean
  preferred_search_provider: CODEX_IN_APP_BROWSER | EXA | OTHER | null
```

这两个工具字段是期望能力，不是已验证事实。若字段缺失，主管可以使用保守默认值，但不得假装拥有搜索工具、数据库内容或人工评价；AUTO 必须由 S00 产生实测能力记录。

`source_scope` 与 `adaptation_mode` 正交：前者说明改编对象覆盖什么，后者说明怎样改。AUTO 必须使用 `COMPLETE_MEME_UNIT`；短句和长段都可能完整。AUTO 的 `AUTO_ROUTE` 在 V06 依据真实变式选择模式；MANUAL_SEED 尊重用户显式模式。最终解析出的模式必须在后续实际节点及人工评价包内标明，避免长梗候选被当作已通过 V/T 严格模板审核。

O05 的 `artifact.complete_reference` 必须完整实现 [完整原梗单元](complete-meme-unit.md) 的边界对象。后续每个结构、生成和评价节点增加 `complete_reference_ref`；只引用 `hook_text` 的输出不满足契约。

真实运行使用 `complete_reference.completeness_status`；fixture 测试使用同对象内的 `fixture_completeness_status`，并保持真实状态为 `INCOMPLETE` 或未验证。V04/V05 的版本绑定字段及 V06 的重选流转见 [搜索与证据](search-evidence.md)。

`preferred_search_provider` 也是期望而非能力证明。用户明确附加 `[@浏览器](plugin://browser@openai-bundled)` 时，将其视为 `CODEX_IN_APP_BROWSER` 的显式选择；若插件不可用必须阻塞，不得静默回退。浏览器调用记录格式见 [浏览器搜索适配器](browser-search.md)。

## 节点输出外壳

```json
{
  "node_key": "V05",
  "node_name": "严格验证变式证据",
  "outcome": "EVIDENCE_ACCEPTED",
  "facts": [],
  "hypotheses": [],
  "artifact": {},
  "evidence_refs": [],
  "decision_reason": "",
  "warnings": [],
  "next_action": "",
  "human_readable": {
    "purpose": "",
    "input_summary": "",
    "decision_summary": "",
    "result_summary": "",
    "evidence_summary": "",
    "warning_summary": "",
    "next_step": ""
  }
}
```

搜索调用另存 `query / purpose / derivation / provider / request_id / result_refs / cost / latency / error`。不得只输出一个最终结论而丢失过程。

每个实际执行或明确跳过的节点都必须有一份外壳；连续未到达节点可以用一份 `NOT_REACHED` 列表表示，但不能把不同节点合并成 `O01/O02`。AUTO 从 O02 开始，MANUAL_SEED 从 O01 开始。交付机器记录时，每个已执行节点都要输出独立完整对象，显式含 `execution_mode`、`tool_call_refs` 与 `human_readable` 七字段；不能用表格列、共同字段声明或“可映射为”代替对象字段。若只是简报，标明它不是合约记录，并单独保存完整对象。

## 执行真实性

每项结果增加：

```json
{
  "execution_mode": "TOOL_EXECUTED | SUPERVISOR_REASONED | PROVIDED_FIXTURE",
  "tool_call_refs": []
}
```

`execution_mode` 是所有已执行节点的必填机器字段，必须精确使用上述字面值；不能只在自然语言中写“主管推演式”等近义表达。跳过节点使用 `outcome=NOT_REACHED`，同时仍填写导致跳过判断的 `execution_mode`。

- `TOOL_EXECUTED`：必须存在可追溯工具调用及实际输出；
- `SUPERVISOR_REASONED`：主管依据文本人工推演，不能称为“程序实际校验”或“独立 Agent 审查”；
- `PROVIDED_FIXTURE`：结果来自测试或用户提供的数据，不得称为网络证据。

展示一段未运行的示例代码不构成程序校验。独立审查只有在发生另一模型/Agent 调用时才可标为独立；同一主管第二次阅读仍标为 `SUPERVISOR_REASONED`，并在 `artifact.review_kind=SAME_SUPERVISOR_SECOND_PASS` 中注明其并非独立审查。

## 人工评价包

页面或文本评价必须展示并分别评价：

1. 原始梗搜索计划；
2. 最终选定原始梗；
3. 变式搜索计划；
4. 最终变式搜索结果；
5. 模板提取与槽位契约；`LONG_FORM` 改为完整参照版本、节奏骨架、实证可变位与推断编辑位；
6. 正式梗候选集；
7. 最终正式梗。

每个模块提供 1～5 分结构化指标和可选文本意见。`STRICT_SLOT` 候选逐条评价通顺度、原梗辨识度、凿agu融合自然度、幽默度、模板逻辑、改编克制度、可用性；`LONG_FORM` 的模板逻辑改评参照节奏保留和推断编辑位诚实性，并额外关注施受关系。最终结果还评价是否为最佳候选。评价是下一轮的强制门槛，入库决定独立配置。

## 策略更新

从人工评价提取原子策略指令，每条包含：

```json
{
  "target_stage": "V01|T01|G02|G04|...",
  "issue": "",
  "directive": "",
  "evidence": "评价字段路径或原文意见",
  "priority": 1,
  "effective_from_next_round": true
}
```

每条指令只处理一个可验证的问题；若一条意见同时涉及适配性、生成长度和评分偏好，应拆成多条。按最早能够阻断根因的节点路由，而不是只发给暴露问题的下游节点：

- “用动作定语包装人物称谓等不兼容槽位”首先路由到 `G01` 作适用性否决；若还包含候选写法问题，再另建 `G02` 指令；
- “没有最小替换”路由到 `G02`，指令必须明确要求候选集**至少生成一条只替换关键槽位的最小替换型**，不能用“做删除检查”等间接说法代替；若同时有“解释过长”，必须建立另一条 G02 指令，禁止合并；
- “未优先选择最小替换”路由到 `G04`。即使文字意见只描述候选过度包装或解释过长，只要最终结果评分不高于 2 分，也应另建一条以该评分和意见为证据的 `G04` 指令：在通过硬审计的候选中提高最小替换、短长度和原梗辨识度的选择优先级；不得把它误写成新的硬边界；
- “解释过长”单独路由到 `G02`，不得与评分权重合成一条；
- 搜索查询重复路由到 `V01`，释义或转载误准入路由到 `V05`。

下一轮相关节点必须明确列出实际采用了哪些指令。若反馈与硬边界冲突，保留反馈但标记 `NOT_APPLIED_HARD_RULE_CONFLICT`，不得静默忽略或覆盖硬规则。

H03、H04、H05 也必须各自输出完整节点外壳，不能用一段汇总文字代替；每个对象都显式包含 `execution_mode`、`tool_call_refs`、`facts`、`hypotheses`、`artifact`、`evidence_refs`、`decision_reason`、`warnings`、`next_action` 和完整 `human_readable` 七字段。
