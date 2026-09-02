export interface NodeMetadata {
  name: string
  responsibility: string
}

const nodeMetadata: Record<string, NodeMetadata> = {
  N01: { name: '人工种子规范化', responsibility: '整理人工输入的种子，提取原句候选、核心表达和初始搜索概念。' },
  N02: { name: '自主发现规划', responsibility: '在没有人工种子时提出可搜索、可改编且不与正式库重复的中文文案梗方向。' },
  N03: { name: '原始梗搜索计划', responsibility: '根据种子或自主发现方向，制定用于找到原句和出处的搜索查询。' },
  N04: { name: '原始梗搜索', responsibility: '通过 Exa 执行原始梗搜索计划，收集真实网页文本和来源证据。' },
  N05: { name: '原始梗筛选', responsibility: '从真实搜索结果中只选出一条可被反复改编的原始文案梗。' },
  N06: { name: '原始梗查重', responsibility: '将选中原始梗与正式梗标题及必要的详细记录对比，判断是否重复。' },
  N07: { name: '变式搜索计划', responsibility: '只围绕选定的唯一原始梗，制定定向查找网友改编变式的查询。' },
  N08: { name: '变式搜索', responsibility: '通过 Exa 执行变式搜索计划，收集包含改编文案的真实网页证据。' },
  N09: { name: '变式证据筛选', responsibility: '从搜索结果中提取可逐字核验的网友变式，排除原文转载和无关内容。' },
  N10: { name: '模板提取', responsibility: '根据选定的原始梗和有效变式，抽取可复用的文案模板。' },
  N11: { name: '模板验证', responsibility: '验证提取的模板能否准确覆盖原始梗和多条有效变式。' },
  'N11.5': { name: '改编路线选择', responsibility: '判断应直接填充槽位还是保留结构改写，并给出凿agu改编约束。' },
  N12: { name: '候选生成', responsibility: '参考模板和真实变式，生成 5 条将 agu 作为“凿”动作承受者的候选文案。' },
  N13: { name: '候选自评分', responsibility: '对 5 条候选的通顺度、原梗辨识度、凿agu契合度和改编克制度等进行评分。' },
  N14: { name: '最佳候选选择', responsibility: '只从自评合格的候选中选出一条最佳文案，不再改写内容。' },
  N15: { name: '正式梗包装', responsibility: '为选中候选生成标题和标准化字段，保证正式文案与选中候选逐字一致。' },
  N16: { name: '正式梗查重', responsibility: '在准入前对最终标题和文案再次查重，避免写入重复的正式梗。' },
  N17: { name: '准入预判', responsibility: '根据准入模式和硬性阈值生成 Agent 准入建议，但仍必须进入人工评价。' },
  N18: { name: '人工评价', responsibility: '等待并接收人工对处理链、候选集、单条候选和最终结果的结构化评价。' },
  N19: { name: '反馈策略更新', responsibility: '将人工评价整理为受影响节点、策略调整摘要和下轮假设。' },
  N20: { name: '归档与收尾', responsibility: '保存完整运行记录和准入结果，并根据持续执行设置决定是否开启下一轮。' },
}

const unknownNode: NodeMetadata = {
  name: '未知节点',
  responsibility: '暂无该节点的职责说明，请根据节点输入和输出进一步核对。',
}

export function getNodeMetadata(nodeKey: string): NodeMetadata {
  return nodeMetadata[nodeKey] ?? unknownNode
}

export function humanizeNodeError(error: string, errorCode?: string): string {
  if (error.includes('must treat agu as the person receiving the action')) {
    return '候选中没有始终把 agu 作为“凿”动作的承受者。'
  }
  if (error.includes('template must contain reusable slots and meaningful fixed structure')) {
    return '提取的模板缺少可复用槽位或有意义的固定结构。'
  }
  if (error.includes('template does not reconstruct the selected original meme')) {
    return '提取的模板无法重建选定的原始梗。'
  }
  if (error.includes('insufficient verified variant evidence')) {
    return '当前通过核验的真实变式证据不足。'
  }
  if (error.includes('must return exactly five candidates') || error.includes('candidate ids must be C1..C5')) {
    return '候选生成结果不是完整的 C1～C5 五条文案。'
  }
  if (error.includes('node returned no result')) return '节点没有返回任何结果。'
  if (error.includes('node result must include outcome')) return '节点结果缺少状态机路由所需的 outcome 字段。'
  if (error === 'NODE_NOT_REGISTERED') return '当前节点没有注册可执行的实现。'
  if (errorCode === 'NODE_TIMEOUT') return '节点调用外部服务超时，本次没有得到完整结果。'
  if (errorCode === 'NODE_OUTPUT_VALIDATION_FAILED') return '节点输出未通过结构或业务规则校验，请根据下方技术错误修正生成结果。'
  return '节点执行过程中发生错误，请按重试建议重新执行该节点。'
}

export function retryGuidance(nodeKey: string): string {
  if (nodeKey === 'N12') return '沿用 N01～N11.5 已有结果，从 N12 重新生成 5 条候选并再次校验。'
  return `保留 ${nodeKey} 之前的已有结果，从 ${nodeKey} 重新执行该节点。`
}
