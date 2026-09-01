import { Button, Space, Tag, Typography } from 'antd'
import { useState } from 'react'

export interface ArtifactNode {
  execution_id?: string
  id?: string
  branch_id?: string
  node_key: string
  attempt_no?: number
  status?: string
  input?: unknown
  output?: unknown
  error_code?: string | null
  error_message?: string | null
  started_at?: string
  ended_at?: string | null
}

export interface ArtifactBranch {
  branch_id: string
  parent_branch_id?: string | null
  forked_from_execution_id?: string | null
}

type ArtifactRecord = Record<string, unknown>
const INITIAL_EVIDENCE_LIMIT = 5
const EXPANDED_EVIDENCE_LIMIT = 20
const TITLE_LABEL_LIMIT = 80
const URL_LABEL_LIMIT = 96

function asRecord(value: unknown): ArtifactRecord | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as ArtifactRecord
    : undefined
}

function records(value: unknown): ArtifactRecord[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is ArtifactRecord => Boolean(item)) : []
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function numberValue(value: unknown): string | undefined {
  return typeof value === 'number' ? String(value) : undefined
}

function payload(artifact: ArtifactRecord): ArtifactRecord {
  return asRecord(artifact.llm) ?? artifact
}

function excerpt(value: string, limit = 240): string {
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > limit ? `${compact.slice(0, limit)}…` : compact
}

function truncatedLabel(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

function isHttpUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}

function executionId(node: ArtifactNode): string {
  return node.execution_id ?? node.id ?? ''
}

function executionTime(node: ArtifactNode): number | undefined {
  const value = node.started_at ?? node.ended_at
  if (!value) return undefined
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? undefined : parsed
}

function compareExecutions(left: ArtifactNode, right: ArtifactNode): number {
  const leftTime = executionTime(left)
  const rightTime = executionTime(right)
  if (leftTime !== undefined && rightTime !== undefined && leftTime !== rightTime) return leftTime - rightTime
  if (left.node_key === right.node_key) {
    const attemptDifference = (left.attempt_no ?? 0) - (right.attempt_no ?? 0)
    if (attemptDifference) return attemptDifference
  }
  return executionId(left).localeCompare(executionId(right))
}

function unwrapArtifact(node: ArtifactNode | undefined): ArtifactRecord | undefined {
  const output = asRecord(node?.output)
  return output ? asRecord(output.artifact) ?? output : undefined
}

function currentRoundExecution(nodes: readonly ArtifactNode[], nodeKey: string): ArtifactNode | undefined {
  const ordered = [...nodes].sort(compareExecutions)
  const hasCompleteOrdering = ordered.every((node) => executionTime(node) !== undefined)
  const roundEnds = ordered.filter((node) => node.node_key === 'N17')
  let candidates = ordered.filter((node) => node.node_key === nodeKey)

  if (hasCompleteOrdering && roundEnds.length) {
    const end = roundEnds.at(-1)!
    const start = roundEnds.at(-2)
    candidates = candidates.filter((node) => (
      (!start || compareExecutions(node, start) > 0)
      && compareExecutions(node, end) <= 0
    ))
  } else if (!hasCompleteOrdering && roundEnds.length) {
    const roundAttempt = Math.max(...roundEnds.map((node) => node.attempt_no ?? 0))
    candidates = candidates.filter((node) => (node.attempt_no ?? 0) >= roundAttempt)
  }

  return candidates.sort(compareExecutions).at(-1)
}

function ancestorExecutionBeforeFork(
  nodes: readonly ArtifactNode[],
  nodeKey: string,
  branchId: string,
  forkedFromExecutionId: string,
): ArtifactNode | undefined {
  const branchNodes = nodes.filter((node) => node.branch_id === branchId)
  const cutoff = branchNodes.find((node) => executionId(node) === forkedFromExecutionId)
  if (!cutoff || executionTime(cutoff) === undefined || branchNodes.some((node) => executionTime(node) === undefined)) return undefined

  const ordered = [...branchNodes].sort(compareExecutions)
  const previousRoundEnd = ordered
    .filter((node) => node.node_key === 'N17' && compareExecutions(node, cutoff) < 0)
    .at(-1)
  return ordered.filter((node) => (
    node.node_key === nodeKey
    && (!previousRoundEnd || compareExecutions(node, previousRoundEnd) > 0)
    && compareExecutions(node, cutoff) <= 0
  )).at(-1)
}

// This pure selector is colocated with the only component that consumes its artifact shape.
// eslint-disable-next-line react-refresh/only-export-components
export function latestNodeArtifact(
  nodes: readonly ArtifactNode[],
  nodeKey: string,
  activeBranchId: string,
  branches: readonly ArtifactBranch[] = [],
): ArtifactRecord | undefined {
  const activeExecution = currentRoundExecution(
    nodes.filter((node) => node.branch_id === activeBranchId),
    nodeKey,
  )
  if (activeExecution) return unwrapArtifact(activeExecution)

  const branchMap = new Map(branches.map((branch) => [branch.branch_id, branch]))
  const visited = new Set<string>()
  let child = branchMap.get(activeBranchId)
  while (child?.parent_branch_id && child.forked_from_execution_id && !visited.has(child.branch_id)) {
    visited.add(child.branch_id)
    const inherited = ancestorExecutionBeforeFork(
      nodes,
      nodeKey,
      child.parent_branch_id,
      child.forked_from_execution_id,
    )
    if (inherited) return unwrapArtifact(inherited)
    child = branchMap.get(child.parent_branch_id)
  }
  return undefined
}

function Link({ value }: { value?: string }) {
  if (!value) return null
  const label = truncatedLabel(value, URL_LABEL_LIMIT)
  return isHttpUrl(value)
    ? <Typography.Link href={value} target="_blank" rel="noreferrer">{label}</Typography.Link>
    : <Typography.Text>{label}</Typography.Text>
}

function QuerySummary({ artifact }: { artifact: ArtifactRecord }) {
  const queries = records(payload(artifact).queries)
  return queries.length
    ? <ul>{queries.map((query, index) => <li key={stringValue(query.query_id) ?? index}>{stringValue(query.query) ?? '未提供查询文本'}</li>)}</ul>
    : <Typography.Text type="secondary">未解析到查询计划。</Typography.Text>
}

function SearchEvidenceSummary({ artifact }: { artifact: ArtifactRecord }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [showMore, setShowMore] = useState(false)
  const material = payload(artifact)
  const sourceRecords = records(material.sources)
  const sources = sourceRecords.length ? sourceRecords : records(material.results)

  if (!sources.length) return <Typography.Text type="secondary">未解析到搜索证据。</Typography.Text>

  const visibleLimit = showMore ? EXPANDED_EVIDENCE_LIMIT : INITIAL_EVIDENCE_LIMIT
  const visibleSources = sources.slice(0, visibleLimit)
  return <div className="artifact-evidence-list">{visibleSources.map((source, index) => {
    const key = stringValue(source.source_id) ?? stringValue(source.url) ?? String(index)
    const title = stringValue(source.title) ?? `证据 ${index + 1}`
    const url = stringValue(source.url) ?? stringValue(source.canonical_url)
    const sourceText = stringValue(source.text)
    const isExpanded = expanded.has(key)
    return <div className="artifact-evidence-item" key={key}>
      <Typography.Text strong>{truncatedLabel(title, TITLE_LABEL_LIMIT)}</Typography.Text>
      {url && <div><Link value={url} /></div>}
      {sourceText && <Button
        type="link"
        size="small"
        onClick={() => setExpanded((current) => {
          const next = new Set(current)
          if (next.has(key)) next.delete(key)
          else next.add(key)
          return next
        })}
      >{isExpanded ? '收起证据' : '展开证据'}</Button>}
      {isExpanded && sourceText && <Typography.Paragraph>{excerpt(sourceText)}</Typography.Paragraph>}
    </div>
  })}
    {sources.length > INITIAL_EVIDENCE_LIMIT && <Button type="link" onClick={() => setShowMore((value) => !value)}>
      {showMore ? '收起其余证据' : '展开其余证据'}
    </Button>}
    {showMore && sources.length > EXPANDED_EVIDENCE_LIMIT && <Typography.Text type="secondary">
      仅显示前 {EXPANDED_EVIDENCE_LIMIT} 条，共 {sources.length} 条
    </Typography.Text>}
  </div>
}

function SelectedOriginalSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const title = stringValue(material.title)
  const original = stringValue(material.original_text)
  const url = stringValue(material.source_url)
  return <Space direction="vertical" size={4}>
    {title && <Typography.Text strong>{title}</Typography.Text>}
    {original && <Typography.Text>{original}</Typography.Text>}
    <Link value={url} />
    {!title && !original && !url && <Typography.Text type="secondary">未解析到选定原始梗。</Typography.Text>}
  </Space>
}

function VariantSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const variants = records(material.variants).length
    ? records(material.variants)
    : records(material.items).filter((item) => item.classification === 'VALID_VARIANT')
  return variants.length
    ? <ul>{variants.map((variant, index) => {
      const text = stringValue(variant.variant_text) ?? '未提供变式文本'
      const url = stringValue(variant.source_url) ?? stringValue(variant.url)
      return <li key={`${text}-${index}`}><Space direction="vertical" size={0}><Typography.Text>{text}</Typography.Text><Link value={url} /></Space></li>
    })}</ul>
    : <Typography.Text type="secondary">未解析到有效变式。</Typography.Text>
}

function TemplateSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const template = stringValue(material.canonical_template_text) ?? stringValue(material.template)
  const explanation = stringValue(material.template_explanation)
  return <Space direction="vertical" size={4}>
    {template && <Typography.Text code>{template}</Typography.Text>}
    {explanation && <Typography.Text type="secondary">{excerpt(explanation)}</Typography.Text>}
    {!template && !explanation && <Typography.Text type="secondary">未解析到模板材料。</Typography.Text>}
  </Space>
}

function TemplateValidationSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const decision = stringValue(material.decision)
  const coverage = numberValue(material.coverage)
  const accuracy = numberValue(material.accuracy)
  const problems = Array.isArray(material.problems) ? material.problems.filter((item): item is string => typeof item === 'string') : []
  return <Space direction="vertical" size={4}>
    <Space wrap>{decision && <Tag>{decision}</Tag>}{coverage && <Typography.Text>覆盖率：{coverage}</Typography.Text>}{accuracy && <Typography.Text>准确度：{accuracy}</Typography.Text>}</Space>
    {problems.length > 0 && <Typography.Text type="secondary">{problems.join('；')}</Typography.Text>}
    {!decision && !coverage && !accuracy && !problems.length && <Typography.Text type="secondary">未解析到模板验证结果。</Typography.Text>}
  </Space>
}

function CandidateSummary({ artifact }: { artifact: ArtifactRecord }) {
  const candidates = records(payload(artifact).candidates)
  return candidates.length
    ? <ul>{candidates.map((candidate, index) => <li key={stringValue(candidate.candidate_id) ?? index}>
      <Typography.Text strong>{stringValue(candidate.candidate_id) ?? `C${index + 1}`}：</Typography.Text>
      <Typography.Text>{stringValue(candidate.text) ?? '未提供候选文本'}</Typography.Text>
    </li>)}</ul>
    : <Typography.Text type="secondary">未解析到候选文案。</Typography.Text>
}

function CandidateScoreSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const scores = records(material.scores)
  const qualified = Array.isArray(material.qualified_candidate_ids)
    ? material.qualified_candidate_ids.filter((item): item is string => typeof item === 'string')
    : []
  return <Space direction="vertical" size={4}>
    {qualified.length > 0 && <Typography.Text>自评合格：{qualified.join('、')}</Typography.Text>}
    {scores.map((score, index) => <Typography.Text type="secondary" key={stringValue(score.candidate_id) ?? index}>
      {stringValue(score.candidate_id) ?? `C${index + 1}`}：通顺 {numberValue(score.fluency) ?? '-'}，辨识 {numberValue(score.recognition) ?? '-'}，契合 {numberValue(score.agu_fit) ?? '-'}，幽默 {numberValue(score.humor) ?? '-'}
    </Typography.Text>)}
    {!qualified.length && !scores.length && <Typography.Text type="secondary">未解析到候选自评分。</Typography.Text>}
  </Space>
}

function SelectionSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const selected = stringValue(material.selected_candidate_id)
  const reason = stringValue(material.selection_reason)
  return <Space direction="vertical" size={4}>
    {selected && <Typography.Text strong>选中 {selected}</Typography.Text>}
    {reason && <Typography.Text type="secondary">{excerpt(reason)}</Typography.Text>}
    {!selected && !reason && <Typography.Text type="secondary">未解析到选择结果。</Typography.Text>}
  </Space>
}

function FinalPackageSummary({ artifact }: { artifact: ArtifactRecord }) {
  const material = payload(artifact)
  const title = stringValue(material.title)
  const finalText = stringValue(material.final_agu_text)
  const url = stringValue(material.source_url)
  return <Space direction="vertical" size={4}>
    {title && <Typography.Text strong>{title}</Typography.Text>}
    {finalText && <Typography.Text>{finalText}</Typography.Text>}
    <Link value={url} />
    {!title && !finalText && !url && <Typography.Text type="secondary">未解析到正式包装。</Typography.Text>}
  </Space>
}

function NodeSummary({ nodeKey, artifact }: { nodeKey: string; artifact: ArtifactRecord }) {
  switch (nodeKey) {
    case 'N03':
    case 'N07': return <QuerySummary artifact={artifact} />
    case 'N04':
    case 'N08': return <SearchEvidenceSummary artifact={artifact} />
    case 'N05': return <SelectedOriginalSummary artifact={artifact} />
    case 'N09': return <VariantSummary artifact={artifact} />
    case 'N10': return <TemplateSummary artifact={artifact} />
    case 'N11': return <TemplateValidationSummary artifact={artifact} />
    case 'N12': return <CandidateSummary artifact={artifact} />
    case 'N13': return <CandidateScoreSummary artifact={artifact} />
    case 'N14': return <SelectionSummary artifact={artifact} />
    case 'N15': return <FinalPackageSummary artifact={artifact} />
    default: return <Typography.Text type="secondary">暂无该节点的摘要视图。</Typography.Text>
  }
}

export function RunArtifactSummary({
  nodes,
  nodeKeys,
  activeBranchId,
  branches = [],
}: {
  nodes: readonly ArtifactNode[]
  nodeKeys: readonly string[]
  activeBranchId: string
  branches?: readonly ArtifactBranch[]
}) {
  return <div className="run-artifact-summary">{nodeKeys.map((nodeKey) => {
    const artifact = latestNodeArtifact(nodes, nodeKey, activeBranchId, branches)
    return <section className="run-artifact-node" data-node-key={nodeKey} key={nodeKey}>
      <Typography.Title level={5}>{nodeKey}</Typography.Title>
      {artifact
        ? <NodeSummary nodeKey={nodeKey} artifact={artifact} />
        : <Typography.Text type="secondary">当前轮暂无材料。</Typography.Text>}
    </section>
  })}</div>
}
