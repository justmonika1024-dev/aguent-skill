# 完整原梗单元

## 定义

`source_scope=COMPLETE_MEME_UNIT` 指网友能够作为同一个梗独立引用或改编的**最小闭合文本单元**。它可以是一句，也可以是一整段；“完整”由传播边界和语用闭合决定，不由字符数决定。

一个合格单元应同时满足：

1. 保留使原梗成立的主要铺垫、转折、重复和笑点/结论收束；
2. 脱离来源页面的解释正文仍能独立成立；
3. 起止边界有连续来源正文和可复核位置支持；
4. 没有为了缩短而截掉同一传播单元的后半段，也没有把百科解释、作者评论或无关续写并入正文。

因此，`大胆妖孽` 只是钩子，闭合单元通常至少到“我一眼就看出你不是人”；`我怀疑你在开车` 通常至少到“但我没有证据”。若某开场句既独立传播、又属于一个长段支系，应把它们记录为两个 `versions` 项，再以本轮真实变式所套用的边界选择参照，不能只凭“更长”取胜。

## O05 边界对象

O05 对唯一候选输出：

```yaml
source_scope: COMPLETE_MEME_UNIT
hook_text: 搜索时使用的线索，可短于完整梗
complete_reference_text: 本轮逐字参照全文
versions:
  - version_ref: string
    text: string
    boundary_start: 起始短引文或位置说明
    boundary_end: 结束短引文或位置说明
    closure_reason: 为什么到这里才形成独立闭合梗
    relationship: SHORT_BRANCH | LONG_BRANCH | WORDING_VARIANT
    source:
      title: string
      url: string
      locator: string
      evidence_ref: string
selected_version_ref: string
selection_reason: string
completeness_status: VERIFIED | INCOMPLETE | CONFLICTED
fixture_completeness_status: VERIFIED | INCOMPLETE | CONFLICTED | null
boundary_change_log:
  - from: string
    to: string
    reason: string
    evidence_refs: []
```

`versions[].version_ref` 在本轮内唯一；`selected_version_ref` 必须引用其中一项；`complete_reference_text` 必须逐字等于该版本的 `text`，作为后续节点的便捷物化字段。短、长支系并存时都放入 `versions`，不得用没有 ID 的自由文本充当备选版本。

`VERIFIED` 不表示找到了唯一官方原句，只表示“这个有来源的版本可作为本轮完整参照”。版本有争议时保留差异；只要能明确选择一个闭合传播支系即可。若连支系边界也无法判断，标 `CONFLICTED`。

## 边界核验动作

1. 先把候选文字视为 `hook_text`，用精确全文、开头与结尾锚点、`原文/完整版/完整台词/改编` 等查询寻找连续正文。
2. 打开来源页，读取钩子前后文；搜索摘要只能提示可能存在更长版本。
3. 至少取得一个包含逐字全文的可读来源，并满足以下之一：来源用引号、段落、列表项等显式标出边界；或另一条独立引用/改编线索支持相同起止点。只有一段边界不清的普通叙述时不能标 `VERIFIED`；单一来源若自身边界明确则可以，但要警告证据单薄。
4. 若后文仍在兑现前文铺垫、延续固定反复或承载公认收束，把它纳入；若后文转为解释、评论或自由续写，在此之前结束。
5. 保存所有扩展和裁剪决定，后续发现反证时回到 O05 建立新版本，不静默覆盖。

## 硬流转

- AUTO：`completeness_status != VERIFIED` 时继续补搜；预算耗尽则放弃该候选并回到 O02。所有候选耗尽才结束本轮。
- MANUAL_SEED：输入也先当线索；未核验时等待人工补充来源或授权 fixture 分析，不把记忆补全文当网络证据。
- 测试 fixture 可以输出 `fixture_completeness_status=VERIFIED` 验证规则行为；真实 AUTO 的 `completeness_status` 仍须由实际来源调用支持，两者不得互相替代。
- O05 通过前不得进入 V01、L01、L02、T01 或 G02。
- V/T/L/G 节点始终引用 `complete_reference_text`；可以在完整单元内选择锚点和槽位，但最终候选必须覆盖所选模式要求的整个参照范围。
