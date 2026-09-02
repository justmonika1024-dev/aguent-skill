import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { RunDetailPage } from './RunDetailPage'

it('renders persisted nodes, evidence and API usage for a historical run', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/usage')) return new Response(JSON.stringify({ calls: 2, llm_calls: 1, search_calls: 1, input_tokens: 10, output_tokens: 5, total_tokens: 15, cost_usd: 0.01, latency_ms: 20 }))
    if (url.endsWith('/runs/r1')) return new Response(JSON.stringify({run_id:'r1',run_version:9,mode:'MANUAL_SEED',state:'WAITING_HUMAN_EVALUATION',active_branch_id:'b1'}))
    return new Response(JSON.stringify({
      run: { run_id: 'r1', mode: 'MANUAL_SEED', state: 'COMPLETED', seed_text: '你说的对，但是原神' },
      branches: [{ branch_id: 'b1', is_final_active: true }],
      nodes: [{ execution_id: 'e1', branch_id: 'b1', node_key: 'N10', status: 'SUCCEEDED', output: { template: '你说的对，但是{主题}' } }],
      sources: [{ source_id: 's1', title: '原神梗', url: 'https://example.com', text: '真实变式', evidence_type: 'VARIANT' }],
      evaluations: [], events: [], api_calls: [{ call_id: 'a1', api_type: 'llm', provider: 'deepseek', model: 'qwen', status: 'SUCCEEDED' }],
    }))
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/runs/r1']}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('你说的对，但是原神')).toBeInTheDocument()
  expect(screen.getByRole('button',{name:/人工评价/})).toBeInTheDocument()
  expect(screen.getByText('N10')).toBeInTheDocument()
  expect(screen.getByText('模板提取')).toBeInTheDocument()
  expect(screen.getByText('根据选定的原始梗和有效变式，抽取可复用的文案模板。')).toBeInTheDocument()
  await user.click(screen.getByText('来源与变式 (1)'))
  expect(screen.getByText('真实变式')).toBeInTheDocument()
  await user.click(screen.getByText('API 消耗 (1)'))
  expect(screen.getByText('deepseek')).toBeInTheDocument()
})

it('explains a failed node and retries it from the persisted failure point', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init
    const url = String(input)
    if (url.endsWith('/usage')) return new Response(JSON.stringify({ calls: 1, llm_calls: 1, search_calls: 0, input_tokens: 10, output_tokens: 5, total_tokens: 15, cost_usd: 0, latency_ms: 20 }))
    if (url.endsWith('/commands')) return new Response(JSON.stringify({ accepted: true, run_version: 13 }))
    if (url.endsWith('/runs/r1')) return new Response(JSON.stringify({run_id:'r1',run_version:12,mode:'MANUAL_SEED',state:'FAILED',current_node:'N12',active_branch_id:'b1'}))
    return new Response(JSON.stringify({
      run: { run_id: 'r1', mode: 'MANUAL_SEED', state: 'FAILED', seed_text: '没有未来的未来不是我想要的未来' },
      branches: [{ branch_id: 'b1', is_final_active: true }],
      nodes: [{ execution_id: 'e1', branch_id: 'b1', node_key: 'N11.5', status: 'SUCCEEDED', output: { route: 'STRUCTURE_PRESERVING_REWRITE' } }],
      sources: [], evaluations: [], api_calls: [],
      events: [{ sequence: 39, event_type: 'node.failed', state: 'FAILED', branch_id: 'b1', occurred_at: '2026-08-31T09:42:00Z', payload: { node_key: 'N12', error: 'N12 must treat agu as the person receiving the action 凿' } }],
    }))
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/runs/r1']}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

  expect(await screen.findByText('N12 候选生成失败')).toBeInTheDocument()
  expect(screen.getByText('候选中没有始终把 agu 作为“凿”动作的承受者。')).toBeInTheDocument()
  expect(screen.getByText('沿用 N01～N11.5 已有结果，从 N12 重新生成 5 条候选并再次校验。')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /从 N12 重试/ }))

  const commandCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/commands'))
  expect(commandCall).toBeDefined()
  expect(JSON.parse(String(commandCall?.[1]?.body))).toEqual(expect.objectContaining({
    type: 'RETRY_NODE',
    expected_run_version: 12,
    payload: { node_key: 'N12' },
  }))
})

it('shows timeout diagnosis and retry when the provider returned no error text', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/usage')) return new Response(JSON.stringify({ calls: 1, llm_calls: 0, search_calls: 1, input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0, latency_ms: 30000 }))
    if (url.endsWith('/runs/r2')) return new Response(JSON.stringify({run_id:'r2',run_version:4,mode:'MANUAL_SEED',state:'FAILED',current_node:'N08',retry_available:true,active_branch_id:'b2'}))
    return new Response(JSON.stringify({
      run: { run_id: 'r2', mode: 'MANUAL_SEED', state: 'FAILED', seed_text: '种子' },
      branches: [{ branch_id: 'b2', is_final_active: true }],
      nodes: [{ execution_id: 'e2', branch_id: 'b2', node_key: 'N08', status: 'FAILED', error_code: 'NODE_TIMEOUT', error_message: '', output: null }],
      sources: [], evaluations: [], api_calls: [], events: [],
    }))
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/runs/r2']}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

  expect(await screen.findByText('N08 变式搜索失败')).toBeInTheDocument()
  expect(screen.getByText('节点调用外部服务超时，本次没有得到完整结果。')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /从 N08 重试/ })).toBeInTheDocument()
})

it('renders both N07 attempts and the feedback directive from two persisted rounds', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/usage')) return new Response(JSON.stringify({ calls: 0, llm_calls: 0, search_calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0, latency_ms: 0 }))
    if (url.endsWith('/runs/r3')) return new Response(JSON.stringify({run_id:'r3',run_version:48,mode:'AUTO_DISCOVERY',state:'COMPLETED',continuous_enabled:false,active_branch_id:'b3'}))
    return new Response(JSON.stringify({
      run: { run_id: 'r3', mode: 'AUTO_DISCOVERY', state: 'COMPLETED', active_branch_id: 'b3' },
      branches: [{ branch_id: 'b3', is_final_active: true }],
      nodes: [
        { execution_id: 'n07-1', execution_order: 6, branch_id: 'b3', node_key: 'N07', attempt_no: 1, status: 'SUCCEEDED', strategy_version_id: 'strategy-v1', output: { applied_directives: [] } },
        { execution_id: 'n07-2', execution_order: 27, branch_id: 'b3', node_key: 'N07', attempt_no: 2, status: 'SUCCEEDED', strategy_version_id: 'strategy-v2', output: { applied_directives: ['排除原句转载，优先搜索网友槽位改编'] } },
      ],
      sources: [],
      evaluations: [{ evaluation_id: 'evaluation-1' }, { evaluation_id: 'evaluation-2' }],
      api_calls: [],
      events: [],
    }))
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/runs/r3']}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)

  expect(await screen.findAllByText('N07')).toHaveLength(2)
  expect(screen.getByText(/排除原句转载，优先搜索网友槽位改编/)).toBeInTheDocument()
  expect(screen.getByText('2', { selector: '.ant-statistic-content-value-int' })).toBeInTheDocument()
})
