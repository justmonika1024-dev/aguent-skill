import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Form } from 'antd'
import { CandidateEvaluationCard } from './CandidateEvaluationCard'
import { EvaluationModuleCard } from './EvaluationModuleCard'
import { RunArtifactSummary, latestNodeArtifact, type ArtifactNode } from './RunArtifactSummary'

const latestEvidence = `LATEST_EVIDENCE_SUMMARY ${'摘要内容'.repeat(100)} LATEST_EVIDENCE_FULL_TAIL`
function node(nodeKey: string, attemptNo: number, startedAt: string, output?: unknown, branchId = 'b1', executionId = `${branchId}-${nodeKey}-${attemptNo}`): ArtifactNode {
  return {
    execution_id: executionId,
    branch_id: branchId,
    node_key: nodeKey,
    attempt_no: attemptNo,
    status: 'SUCCEEDED',
    output,
    error_code: null,
    error_message: null,
    started_at: startedAt,
    ended_at: startedAt,
  }
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
