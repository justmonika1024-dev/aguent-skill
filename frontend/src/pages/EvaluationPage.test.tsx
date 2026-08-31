import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { EvaluationPage } from './EvaluationPage'

it('shows five structured candidate evaluations and keeps submission disabled until complete', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/record')) return new Response(JSON.stringify({ run:{run_id:'r1',mode:'MANUAL_SEED',state:'WAITING_HUMAN_EVALUATION',active_branch_id:'b1'},branches:[],sources:[],events:[],api_calls:[],evaluations:[],nodes:[{node_key:'N12',output:{artifact:{llm:{candidates:[1,2,3,4,5].map(i=>({candidate_id:`C${i}`,text:`候选${i}`}))}}}},{node_key:'N14',output:{artifact:{llm:{selected_candidate_id:'C2'}}}}] }))
    return new Response(JSON.stringify({run_id:'r1',run_version:17,mode:'MANUAL_SEED',state:'WAITING_HUMAN_EVALUATION',active_branch_id:'b1'}))
  }))
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/runs/r1/evaluation']}><Routes><Route path="/runs/:runId/evaluation" element={<EvaluationPage/>}/></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('人工结构化评价')).toBeInTheDocument()
  expect(screen.getByText('候选5')).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'提交评价'})).toBeDisabled()
})
