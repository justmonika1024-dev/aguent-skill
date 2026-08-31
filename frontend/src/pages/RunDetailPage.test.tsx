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
  await user.click(screen.getByText('来源与变式 (1)'))
  expect(screen.getByText('真实变式')).toBeInTheDocument()
  await user.click(screen.getByText('API 消耗 (1)'))
  expect(screen.getByText('deepseek')).toBeInTheDocument()
})
