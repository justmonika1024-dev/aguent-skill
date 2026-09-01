import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Form } from 'antd'
import { CandidateEvaluationCard } from './CandidateEvaluationCard'
import { EvaluationModuleCard } from './EvaluationModuleCard'
import { RunArtifactSummary, latestNodeArtifact, type ArtifactNode } from './RunArtifactSummary'

const latestEvidence = `LATEST_EVIDENCE_SUMMARY ${'摘要内容'.repeat(100)} LATEST_EVIDENCE_FULL_TAIL`
function node(
  nodeKey: string,
  attemptNo: number,
  startedAt: string,
  output?: unknown,
  branchId = 'b1',
  executionId = `${branchId}-${nodeKey}-${attemptNo}`,
  executionOrder?: number,
): ArtifactNode {
  return {
    execution_id: executionId,
    execution_order: executionOrder,
    branch_id: branchId,
    node_key: nodeKey,
    attempt_no: attemptNo,
    status: 'SUCCEEDED',
    output,
    error_code: null,
    error_message: null,
    started_at: startedAt,
    ended_at: startedAt,
  } as ArtifactNode
}

const nodes: ArtifactNode[] = [
  node('N03', 1, '2026-09-01T01:00:00Z', { artifact: { llm: { queries: [{ query_id: 'old', query: 'OLD_QUERY' }] } } }),
  node('N05', 1, '2026-09-01T01:01:00Z', { artifact: { llm: { original_text: 'OLD_ORIGINAL' } } }),
  node('N08', 1, '2026-09-01T01:02:00Z', { artifact: { sources: [{ source_id: 'old-source', title: 'OLD_SOURCE', url: 'https://old.example', text: 'OLD_EVIDENCE' }] } }),
  node('N09', 1, '2026-09-01T01:03:00Z', { artifact: { llm: { variants: [{ variant_text: 'OLD_VARIANT', source_url: 'https://old.example' }] } } }),
  node('N17', 1, '2026-09-01T01:04:00Z'),
  node('N03', 2, '2026-09-01T02:00:00Z', { artifact: { llm: { queries: [{ query_id: 'new', query: 'LATEST_QUERY' }] } } }),
  node('N05', 2, '2026-09-01T02:01:00Z', { artifact: { llm: { title: '最新原梗', original_text: 'LATEST_ORIGINAL' } } }),
  node('N08', 2, '2026-09-01T02:02:00Z', { artifact: { sources: [{ source_id: 'new-source', title: '最新证据', url: 'https://latest.example/evidence', text: latestEvidence }] } }),
  node('N09', 2, '2026-09-01T02:03:00Z', { artifact: { llm: { variants: [{ variant_text: 'LATEST_VALID_VARIANT', source_id: 'new-source', source_url: 'https://latest.example/evidence' }] } } }),
  node('N17', 2, '2026-09-01T02:04:00Z'),
]

it('returns only the last execution artifact in the active branch evaluation round', () => {
  expect(latestNodeArtifact([...nodes].reverse(), 'N03', 'b1')).toEqual({
    llm: { queries: [{ query_id: 'new', query: 'LATEST_QUERY' }] },
  })
})

it('uses execution time and the latest N17 window instead of array order or attempt noise', () => {
  const roundNodes = [
    node('N17', 2, '2026-09-01T03:09:00Z'),
    node('N03', 9, '2026-09-01T02:02:00Z', { artifact: { llm: { queries: [{ query: 'STALE_HIGH_ATTEMPT' }] } } }),
    node('N03', 11, '2026-09-01T03:04:00Z', { artifact: { llm: { queries: [{ query: 'CURRENT_RETRY' }] } } }),
    node('N17', 1, '2026-09-01T02:09:00Z'),
    node('N03', 10, '2026-09-01T03:01:00Z', { artifact: { llm: { queries: [{ query: 'CURRENT_FIRST_ATTEMPT' }] } } }),
  ]

  expect(latestNodeArtifact(roundNodes, 'N03', 'b1')).toEqual({
    llm: { queries: [{ query: 'CURRENT_RETRY' }] },
  })
})

it('matches backend started_at then execution_id ordering at equal timestamps', () => {
  const sameTimeNodes = [
    node('N17', 2, '2026-09-01T03:09:00Z', undefined, 'b1', 'z-current-round-end'),
    node('N03', 10, '2026-09-01T03:09:00Z', { artifact: { llm: { queries: [{ query: 'BEFORE_EQUAL_TIME_END' }] } } }, 'b1', 'a-current-material'),
    node('N17', 1, '2026-09-01T02:09:00Z', undefined, 'b1', 'previous-round-end'),
  ]

  expect(latestNodeArtifact(sameTimeNodes, 'N03', 'b1')).toEqual({
    llm: { queries: [{ query: 'BEFORE_EQUAL_TIME_END' }] },
  })
})

it('uses the record execution order when equal timestamps make attempt-based comparison non-transitive', () => {
  const sameTimestamp = '2026-09-01T03:09:00Z'
  const orderedRecordNodes = [
    node('N17', 2, sameTimestamp, undefined, 'b1', 'n-current-round-end', 13),
    node('N03', 9, sameTimestamp, { artifact: { llm: { queries: [{ query: 'CURRENT_RETRY' }] } } }, 'b1', 'a-current-retry', 12),
    node('N17', 1, sameTimestamp, undefined, 'b1', 'z-previous-round-end', 10),
    node('N03', 8, sameTimestamp, { artifact: { llm: { queries: [{ query: 'CURRENT_FIRST_ATTEMPT' }] } } }, 'b1', 'm-current-first', 11),
  ]

  expect(latestNodeArtifact(orderedRecordNodes, 'N03', 'b1')).toEqual({
    llm: { queries: [{ query: 'CURRENT_RETRY' }] },
  })
})

it('falls back to monotonic per-node attempts for the current record shape without timestamps', () => {
  const persistedNodes: ArtifactNode[] = [
    { execution_id: 'n17-2', branch_id: 'b1', node_key: 'N17', attempt_no: 2, status: 'SUCCEEDED' },
    { execution_id: 'n03-1', branch_id: 'b1', node_key: 'N03', attempt_no: 1, status: 'SUCCEEDED', output: { artifact: { llm: { queries: [{ query: 'PERSISTED_OLD' }] } } } },
    { execution_id: 'n17-1', branch_id: 'b1', node_key: 'N17', attempt_no: 1, status: 'SUCCEEDED' },
    { execution_id: 'n03-2', branch_id: 'b1', node_key: 'N03', attempt_no: 2, status: 'SUCCEEDED', output: { artifact: { llm: { queries: [{ query: 'PERSISTED_CURRENT' }] } } } },
  ]

  expect(latestNodeArtifact(persistedNodes, 'N03', 'b1')).toEqual({
    llm: { queries: [{ query: 'PERSISTED_CURRENT' }] },
  })
})

it('switches material with activeBranchId and never selects a sibling branch', () => {
  const branchNodes = [
    node('N17', 1, '2026-09-01T04:04:00Z', undefined, 'b2'),
    node('N03', 1, '2026-09-01T04:00:00Z', { artifact: { llm: { queries: [{ query: 'BRANCH_TWO' }] } } }, 'b2'),
    node('N17', 1, '2026-09-01T03:04:00Z', undefined, 'b1'),
    node('N03', 1, '2026-09-01T03:00:00Z', { artifact: { llm: { queries: [{ query: 'BRANCH_ONE' }] } } }, 'b1'),
  ]

  expect(latestNodeArtifact(branchNodes, 'N03', 'b2')).toEqual({ llm: { queries: [{ query: 'BRANCH_TWO' }] } })
  expect(latestNodeArtifact(branchNodes, 'N03', 'b1')).toEqual({ llm: { queries: [{ query: 'BRANCH_ONE' }] } })
  expect(latestNodeArtifact(branchNodes, 'N03', 'unknown')).toBeUndefined()
})

it('inherits only pre-fork artifacts from declared ancestor branches', () => {
  const branchNodes = [
    node('N03', 1, '2026-09-01T05:00:00Z', { artifact: { llm: { queries: [{ query: 'ANCESTOR_BEFORE_FORK' }] } } }, 'root'),
    node('N10', 1, '2026-09-01T05:05:00Z', {}, 'root', 'fork-execution'),
    node('N03', 2, '2026-09-01T05:10:00Z', { artifact: { llm: { queries: [{ query: 'ANCESTOR_AFTER_FORK' }] } } }, 'root'),
    node('N03', 1, '2026-09-01T05:11:00Z', { artifact: { llm: { queries: [{ query: 'SIBLING' }] } } }, 'sibling'),
    node('N17', 1, '2026-09-01T05:20:00Z', undefined, 'child'),
  ]
  const branches = [
    { branch_id: 'root', parent_branch_id: null },
    { branch_id: 'child', parent_branch_id: 'root', forked_from_execution_id: 'fork-execution' },
    { branch_id: 'sibling', parent_branch_id: 'root', forked_from_execution_id: 'fork-execution' },
  ]

  expect(latestNodeArtifact(branchNodes, 'N03', 'child', branches)).toEqual({
    llm: { queries: [{ query: 'ANCESTOR_BEFORE_FORK' }] },
  })
  expect(latestNodeArtifact(branchNodes, 'N03', 'orphan', branches)).toBeUndefined()
})

it('renders the complete current-round material set for a corrected child branch', () => {
  const sameTimestamp = '2026-09-01T08:00:00Z'
  const branchNodes = [
    node('N03', 1, sameTimestamp, { artifact: { llm: { queries: [{ query: 'PREVIOUS_ROUND_QUERY' }] } } }, 'root', 'root-old-n03', 0),
    node('N17', 1, sameTimestamp, undefined, 'root', 'root-old-n17', 1),
    node('N03', 2, sameTimestamp, { artifact: { llm: { queries: [{ query: 'ROOT_CURRENT_QUERY' }] } } }, 'root', 'root-n03', 2),
    node('N05', 2, sameTimestamp, { artifact: { llm: { original_text: 'INHERITED_ORIGINAL' } } }, 'root', 'root-n05', 3),
    node('N07', 2, sameTimestamp, { artifact: { llm: { queries: [{ query: 'INHERITED_VARIANT_PLAN' }] } } }, 'root', 'root-n07', 4),
    node('N08', 2, sameTimestamp, { artifact: { sources: [{ title: 'INHERITED_EVIDENCE', url: 'https://evidence.example' }] } }, 'root', 'root-n08', 5),
    node('N09', 2, sameTimestamp, { artifact: { llm: { variants: [{ variant_text: 'INHERITED_VARIANT' }] } } }, 'root', 'root-n09', 6),
    node('N10', 2, sameTimestamp, { artifact: { llm: { template: 'INHERITED_TEMPLATE' } } }, 'root', 'root-n10', 7),
    node('N11', 2, sameTimestamp, { artifact: { llm: { decision: 'INHERITED_TEMPLATE_PASS' } } }, 'root', 'root-n11', 8),
    node('N12', 2, sameTimestamp, { artifact: { llm: { candidates: [{ candidate_id: 'C1', text: 'INHERITED_CANDIDATE' }] } } }, 'root', 'root-n12', 9),
    node('N13', 2, sameTimestamp, { artifact: { llm: { qualified_candidate_ids: ['C1'] } } }, 'root', 'root-n13', 10),
    node('N14', 2, sameTimestamp, { artifact: { llm: { selected_candidate_id: 'C1', selection_reason: 'INHERITED_SELECTION' } } }, 'root', 'root-n14', 11),
    node('N15', 2, sameTimestamp, { artifact: { llm: { final_agu_text: 'INHERITED_FINAL' } } }, 'root', 'root-n15', 12),
    node('N16', 2, sameTimestamp, {}, 'root', 'root-fork', 13),
    node('N17', 2, sameTimestamp, undefined, 'root', 'root-current-n17', 14),
    node('N03', 3, sameTimestamp, { artifact: { llm: { queries: [{ query: 'ROOT_AFTER_FORK' }] } } }, 'root', 'root-after-fork', 15),
    node('N03', 1, sameTimestamp, { artifact: { llm: { queries: [{ query: 'CHILD_RECOMPUTED_QUERY' }] } } }, 'child', 'child-n03', 16),
    node('N17', 1, sameTimestamp, undefined, 'child', 'child-n17', 17),
    node('N05', 1, sameTimestamp, { artifact: { llm: { original_text: 'SIBLING_ORIGINAL' } } }, 'sibling', 'sibling-n05', 18),
  ].reverse()
  const branches = [
    { branch_id: 'root', parent_branch_id: null, forked_from_execution_id: null },
    { branch_id: 'child', parent_branch_id: 'root', forked_from_execution_id: 'root-fork' },
    { branch_id: 'sibling', parent_branch_id: 'root', forked_from_execution_id: 'root-fork' },
  ]

  render(<RunArtifactSummary
    nodes={branchNodes}
    nodeKeys={['N03', 'N05', 'N07', 'N08', 'N09', 'N10', 'N11', 'N12', 'N13', 'N14', 'N15']}
    activeBranchId="child"
    branches={branches}
  />)

  expect(screen.getByText('CHILD_RECOMPUTED_QUERY')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_ORIGINAL')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_VARIANT_PLAN')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_EVIDENCE')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_VARIANT')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_TEMPLATE')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_TEMPLATE_PASS')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_CANDIDATE')).toBeInTheDocument()
  expect(screen.getByText('自评合格：C1')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_SELECTION')).toBeInTheDocument()
  expect(screen.getByText('INHERITED_FINAL')).toBeInTheDocument()
  expect(screen.queryByText(/PREVIOUS_ROUND_QUERY|ROOT_CURRENT_QUERY|ROOT_AFTER_FORK|SIBLING_ORIGINAL/)).not.toBeInTheDocument()
})

it('shows only latest-round summaries and defers large evidence text', async () => {
  const user = userEvent.setup()
  render(<RunArtifactSummary nodes={[...nodes].reverse()} nodeKeys={['N03', 'N05', 'N08', 'N09']} activeBranchId="b1" />)

  expect(screen.getByText('LATEST_QUERY')).toBeInTheDocument()
  expect(screen.getByText('LATEST_ORIGINAL')).toBeInTheDocument()
  expect(screen.getByText('LATEST_VALID_VARIANT')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: 'https://latest.example/evidence' })).not.toHaveLength(0)
  expect(screen.queryByText(/OLD_QUERY|OLD_ORIGINAL|OLD_VARIANT|OLD_EVIDENCE/)).not.toBeInTheDocument()
  expect(screen.queryByText(/LATEST_EVIDENCE_SUMMARY/)).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '展开证据' }))

  expect(screen.getByText(/LATEST_EVIDENCE_SUMMARY/)).toBeInTheDocument()
  expect(screen.queryByText(/LATEST_EVIDENCE_FULL_TAIL/)).not.toBeInTheDocument()
})

it('bounds large source lists, truncates labels, and never links unsafe URLs', async () => {
  const user = userEvent.setup()
  const longTitle = `LONG_TITLE_${'题'.repeat(160)}_TITLE_TAIL`
  const longSafeUrl = `https://safe.example/${'path'.repeat(80)}/URL_TAIL`
  const sources = Array.from({ length: 60 }, (_, index) => ({
    source_id: `source-${index}`,
    title: index === 1 ? longTitle : index === 0 ? 'DANGEROUS_SOURCE' : `SOURCE_${index}`,
    url: index === 0 ? 'javascript:alert(document.domain)' : index === 1 ? longSafeUrl : `https://source.example/${index}`,
    text: `SUMMARY_${index} ${'正文'.repeat(180)} FULL_TAIL_${index}`,
  }))
  const evidenceNodes = [
    node('N08', 1, '2026-09-01T07:00:00Z', { artifact: { sources } }),
    node('N17', 1, '2026-09-01T07:10:00Z'),
  ]

  render(<RunArtifactSummary nodes={evidenceNodes} nodeKeys={['N08']} activeBranchId="b1" />)

  expect(screen.getByText('SOURCE_4')).toBeInTheDocument()
  expect(screen.queryByText('SOURCE_5')).not.toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: '展开证据' })).toHaveLength(5)
  expect(screen.queryByRole('link', { name: /javascript:/ })).not.toBeInTheDocument()
  expect(screen.getByText(/javascript:/)).toBeInTheDocument()
  const titleLabel = screen.getByText(/^LONG_TITLE_/)
  expect(titleLabel.textContent!.length).toBeLessThanOrEqual(81)
  expect(titleLabel).not.toHaveTextContent('TITLE_TAIL')
  const safeLink = screen.getByRole('link', { name: /^https:\/\/safe\.example/ })
  expect(safeLink).toHaveAttribute('href', longSafeUrl)
  expect(safeLink.textContent!.length).toBeLessThanOrEqual(97)
  expect(safeLink).not.toHaveTextContent('URL_TAIL')

  await user.click(screen.getByRole('button', { name: '展开其余证据' }))

  expect(screen.getByText('SOURCE_19')).toBeInTheDocument()
  expect(screen.queryByText('SOURCE_20')).not.toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: '展开证据' })).toHaveLength(20)
  expect(screen.getByText('仅显示前 20 条，共 60 条')).toBeInTheDocument()
  await user.click(screen.getAllByRole('button', { name: '展开证据' })[0])
  expect(screen.getByText(/SUMMARY_0/)).toBeInTheDocument()
  expect(screen.queryByText(/FULL_TAIL_0/)).not.toBeInTheDocument()
})

it('submits six required candidate fields while allowing empty modification advice', async () => {
  const user = userEvent.setup()
  const onFinish = vi.fn()
  const candidateScores = {
    fluency: 4,
    original_meme_recognition: 4,
    agu_zao_naturalness: 4,
    humor: 4,
    template_logic: 4,
    usability: 'USABLE',
  }
  render(<Form
    initialValues={{ candidate_generation: { candidates: { C1: candidateScores } } }}
    onFinish={onFinish}
  >
    <CandidateEvaluationCard id="C1" text="候选一" />
    <button type="submit">提交候选评价</button>
  </Form>)

  await user.click(screen.getByRole('button', { name: '提交候选评价' }))

  await waitFor(() => expect(onFinish).toHaveBeenCalledWith({
    candidate_generation: {
      candidates: { C1: { ...candidateScores, modification_advice: '' } },
    },
  }))
})

it('binds module scores and an empty optional comment to the requested form path', async () => {
  const user = userEvent.setup()
  const onFinish = vi.fn()
  render(<Form initialValues={{ original_search_plan: { anchor_accuracy: 4 } }} onFinish={onFinish}>
    <EvaluationModuleCard
      title="原始梗搜索计划"
      description="评价查询计划和搜索材料"
      nodes={[node('N03', 1, '2026-09-01T06:00:00Z', { artifact: { llm: { queries: [{ query: '锚点查询' }] } } })]}
      nodeKeys={['N03']}
      activeBranchId="b1"
      fields={[["anchor_accuracy", "锚点准确度"]]}
      formPath="original_search_plan"
    />
    <button type="submit">提交模块评价</button>
  </Form>)

  expect(screen.getByText('原始梗搜索计划')).toBeInTheDocument()
  expect(screen.getByText('评价查询计划和搜索材料')).toBeInTheDocument()
  expect(screen.getByText('锚点查询')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '提交模块评价' }))

  await waitFor(() => expect(onFinish).toHaveBeenCalledWith({
    original_search_plan: { anchor_accuracy: 4, comment: '' },
  }))
})
