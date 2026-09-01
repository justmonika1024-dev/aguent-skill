import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Form } from 'antd'
import { CandidateEvaluationCard } from './CandidateEvaluationCard'
import { EvaluationModuleCard } from './EvaluationModuleCard'
import { RunArtifactSummary, latestNodeArtifact } from './RunArtifactSummary'

const latestEvidence = `LATEST_EVIDENCE_SUMMARY ${'摘要内容'.repeat(100)} LATEST_EVIDENCE_FULL_TAIL`
const nodes = [
  { node_key: 'N03', output: { artifact: { llm: { queries: [{ query_id: 'old', query: 'OLD_QUERY' }] } } } },
  { node_key: 'N05', output: { artifact: { llm: { original_text: 'OLD_ORIGINAL' } } } },
  { node_key: 'N08', output: { artifact: { sources: [{ source_id: 'old-source', title: 'OLD_SOURCE', url: 'https://old.example', text: 'OLD_EVIDENCE' }] } } },
  { node_key: 'N09', output: { artifact: { llm: { variants: [{ variant_text: 'OLD_VARIANT', source_url: 'https://old.example' }] } } } },
  { node_key: 'N03', output: { artifact: { llm: { queries: [{ query_id: 'new', query: 'LATEST_QUERY' }] } } } },
  { node_key: 'N05', output: { artifact: { llm: { title: '最新原梗', original_text: 'LATEST_ORIGINAL' } } } },
  { node_key: 'N08', output: { artifact: { sources: [{ source_id: 'new-source', title: '最新证据', url: 'https://latest.example/evidence', text: latestEvidence }] } } },
  { node_key: 'N09', output: { artifact: { llm: { variants: [{ variant_text: 'LATEST_VALID_VARIANT', source_id: 'new-source', source_url: 'https://latest.example/evidence' }] } } } },
]

it('returns only the last execution artifact for a node in the current run record', () => {
  expect(latestNodeArtifact(nodes, 'N03')).toEqual({
    llm: { queries: [{ query_id: 'new', query: 'LATEST_QUERY' }] },
  })
})

it('shows only latest-round summaries and defers large evidence text', async () => {
  const user = userEvent.setup()
  render(<RunArtifactSummary nodes={nodes} nodeKeys={['N03', 'N05', 'N08', 'N09']} />)

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
      nodes={[{ node_key: 'N03', output: { artifact: { llm: { queries: [{ query: '锚点查询' }] } } } }]}
      nodeKeys={['N03']}
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
