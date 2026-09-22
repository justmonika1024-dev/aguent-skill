# 精简交接最终主管

本文件只供 `compact_round_runner.py` 的全新无网络 `FINAL` 会话使用。搜索 worker 已退出，程序已完成字段校验、去重、正文裁剪和差异覆盖；最终主管只读 `compact-evidence-package.json`、`coverage-plan.json` 与本文件，不回读 JSONL、DOM、stderr 或其他 reference，也不重新搜索。

## 不可变语义与证据边界

- `agu` 是人；`凿` 是施加在 agu 身上的动作，agu 始终是受事者。表层可用 `凿agu`、`agu被凿`、`agu的被凿` 或带明确施事者的等价形式。
- 搜索包中的逐字来源、查询和分类是外部 worker 的 `TOOL_EXECUTED` 交接；本会话的归纳、模板、编辑位、候选和评分是 `SUPERVISOR_REASONED`。生成物永远不是网络证据。
- `complete_reference.complete_reference_text` 必须等于 `selected_version_ref` 指向版本；最终候选必须覆盖该完整参照要求，不能只改开头钩子。
- 搜索包状态、来源字段或覆盖计划不合法时停止并写清原子原因，不脑补、不联网。
- `coverage-plan.json` 的 `adaptation_route` 是本会话唯一分支：`STRICT_SLOT` 或 `LONG_FORM`；`UNSUITABLE` 不得生成。

## `STRICT_SLOT`

1. 重新核对原句之外至少 2 条非重复严格变式、至少 2 个内容组，以及一个能承载凿agu的动作、事件、角色或关键判断位置已有真实差异覆盖。原句与两条变式形成三个同族实例；节奏变式不计入严格数量。
2. 提取能逐字重建原句和全部严格变式的最窄模板。只泛化证据实际变化的连续跨度；关系词、分句数量和顺序保持固定。证据不兼容时拆簇，不能用巨大槽位吞掉结构差异。
3. 为每个槽输出槽位契约：词法/句法类型、语义角色、例值、绑定和跨槽约束。区分“证据中观察到的表层节奏”与“目标事件必须遵守的硬句法”：目标事件的自然句法形态优先于机械复制原槽位的叠词或字数；原变式为“看看/尝尝”不能推出必须写成“凿凿agu”。只要 `去凿agu` 等形式仍属于同一动作谓词槽、固定锚点不变且 agu 为受事者，就可作为最小替换。先做程序式逐字重建审计，再做语言审查；审查失败可修订一次，仍失败则停止。
4. G01 判断：
   - 现有槽可自然直接承载事件：`SUITABLE_STRICT`，使用 `STRICT_FILL`；
   - 直接回填不自然，但存在一个实体槽及其相邻共指谓词，只需一次实体替换和一次共指局部谓词联动：`CONTROLLED_REWRITE_CANDIDATE`；
   - 否则 `NOT_SUITABLE`，停止。
5. `STRICT_FILL` 同时使用模板、槽位契约、完整参照和真实变式，至少生成一条只替换关键槽的最小替换型；槽位内部有可观察句法时再生成句法匹配型，但不得为了表面节奏制造不自然的 `凿凿agu`、`凿一凿agu` 等形式。固定文本不得润色，不要求所有槽位都解释凿agu。
6. `CONTROLLED_REWRITE` 最多替换一个已验证实体槽，并改写一个与其直接共指的局部谓词；不新增、删除或重排分句，不改无关锚点，不加入背景或第二笑点。候选须逐字对照预算审计。
7. 硬伤候选直接淘汰：不能由模板/许可计划重建、施受反转、中文不成立、固定锚点越界、重复槽不同值。再按通顺、句法匹配、辨识度、凿agu契合、克制度、节奏和幽默度评分，选择唯一最佳项。

## `LONG_FORM`

1. 冻结完整参照版本。真实 `rhythm_variants` 有几条用几条；只有一条时明确 `VARIANT_EVIDENCE_SPARSE`，不虚构更多变式。
2. 按原文顺序列出开场、转折/重复和结尾功能。分别记录：真实版本观察到的 `observed_variable_spans`，以及为了让 agu 保持受事者而推断的 `inferred_edit_spans`；后者标 `INFERRED_NOT_SEARCH_EVIDENCE`。
3. 至少生成一条保守候选和一条有依据的节奏扩展候选。保留完整参照的开场、相隔辨识锚点、原有重复/转折及结尾功能；连接句可以创作，但不得伪装成来源文本。
4. 逐句检查 agu 受事关系、通顺、原梗辨识度、因果链、反复层次与新增设定。需要靠无关故事、凭空角色反应或悬空反转制造笑点的候选淘汰。列明每条的保留、改写和新增范围，再按辨识度、通顺、幽默、施受关系、克制度、证据覆盖和因果连贯选择。

## 共同输出与人工门禁

- `run-result.json` 保存模式、节点轨迹、完整参照及版本、精简查询/来源引用、变式及分类、模板与槽位契约或节奏骨架/编辑位、全部候选及审计、唯一草稿、查重和准入建议。
- 顶层至少包含：`input.mode`、`selected_route`、`complete_reference`、`candidates`、`final_draft`、`node_trace`、`human_evaluation`、`final_state`、`stop_node`。`node_trace` 必须覆盖交接核验、所选 T/C/G 或 L 分支、G06-G08 与 H02；不得用自造的替代节点名隐藏这些职责。
- 正式标题只与输入的 `formal_meme_titles` 比较。清单覆盖范围不足时标 `UNVERIFIED`，不得宣称全库唯一；这只影响准入建议，不跳过评价。
- `search-records.json` 只索引精简查询、来源、worker 文件与执行模式，不复制网页噪声。
- `final.md` 简述证据限制、路线、候选选择和待评草稿。
- 形成草稿后终态必须是 `WAITING_HUMAN_EVALUATION`、`stop_node=H02`。人工评价字段保持空，不能代评、入库或开始下一轮。人工评价对象必须预建为：

```json
{
  "status": "PENDING",
  "modules": {
    "original_search_plan": {"rating": null, "comment": null},
    "selected_original": {"rating": null, "comment": null},
    "variant_search_plan": {"rating": null, "comment": null},
    "variant_search_result": {"rating": null, "comment": null},
    "reference_or_template": {"rating": null, "comment": null},
    "candidate_set": {"rating": null, "comment": null},
    "final_draft": {"rating": null, "comment": null, "is_best_candidate": null}
  },
  "admission_decision": null
}
```
