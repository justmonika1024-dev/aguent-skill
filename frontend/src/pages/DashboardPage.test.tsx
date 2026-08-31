import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { DashboardPage } from './DashboardPage'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><DashboardPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url.endsWith('/runs/current')
        ? { run: null, engine_state: 'WAITING_START' }
        : { calls: 0, llm_calls: 0, search_calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0, latency_ms: 0 }
      return new Response(JSON.stringify(payload), { status: 200 })
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('requires a seed in manual mode and only enables continuous execution in auto mode', async () => {
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByText('启动一轮任务')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '人工种子' })).toBeRequired()
    expect(screen.getByRole('switch', { name: '持续执行' })).toBeDisabled()

    await user.click(screen.getByText('自主发现'))
    expect(screen.queryByRole('textbox', { name: '人工种子' })).not.toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '持续执行' })).toBeEnabled()
  })

  it('does not offer pause while awaiting evaluation and keeps continuous execution editable', async()=>{
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>new Response(JSON.stringify(String(input).endsWith('/runs/current')?{run:{run_id:'r1',run_version:4,mode:'AUTO_DISCOVERY',state:'WAITING_HUMAN_EVALUATION',current_node:'N18',continuous_enabled:true},engine_state:'WAITING_HUMAN_EVALUATION'}:{calls:0,llm_calls:0,search_calls:0,input_tokens:0,output_tokens:0,total_tokens:0,cost_usd:0,latency_ms:0}))))
    renderPage()
    expect(await screen.findByText('当前任务')).toBeInTheDocument()
    expect(screen.queryByRole('button',{name:/暂停/})).not.toBeInTheDocument()
    expect(screen.getByRole('button',{name:'前往评价'})).toBeInTheDocument()
    expect(screen.getByRole('switch',{name:'持续执行'})).toBeChecked()
  })
})
