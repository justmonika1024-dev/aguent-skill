import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { MemesPage } from './MemesPage'
import { RunsPage } from './RunsPage'
import { SettingsPage } from './SettingsPage'

function renderPage(page: ReactNode) { const client=new QueryClient({defaultOptions:{queries:{retry:false}}}); return render(<QueryClientProvider client={client}><MemoryRouter>{page}</MemoryRouter></QueryClientProvider>) }

it('lists persisted run history', async()=>{ vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify([{run_id:'run-1',mode:'MANUAL_SEED',state:'COMPLETED',seed_text:'种子梗'}])))); renderPage(<RunsPage/>); expect(await screen.findByText('种子梗')).toBeInTheDocument() })
it('lists formal memes and clearly disables unsupported unpublishing', async()=>{ vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify([{id:'m1',title:'凿具介绍体',original_meme_text:'原梗',canonical_template_text:'模板',final_agu_text:'正式文案',status:'PUBLISHED',source_run_id:'r1'}])))); renderPage(<MemesPage/>); expect(await screen.findByText('凿具介绍体')).toBeInTheDocument(); expect(screen.getByRole('button',{name:'下架'})).toBeDisabled() })
it('shows provider presence without exposing secret inputs', async()=>{ vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>new Response(JSON.stringify(String(input).endsWith('runtime-parameters')?{values:{candidate_batches:3}}:{llm_provider:'deepseek',llm_model:'qwen-plus',api_key_configured:true,search_api_key_configured:true})))); renderPage(<SettingsPage/>); expect(await screen.findByText('qwen-plus')).toBeInTheDocument(); expect(screen.queryByLabelText(/API Key/i)).not.toBeInTheDocument() })
it('reports a 200 response with ok=false as a failed connection', async()=>{const user=userEvent.setup();vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{const url=String(input);if(init?.method==='POST')return new Response(JSON.stringify({ok:false,provider:'exa',error:'密钥无效'}));return new Response(JSON.stringify(url.endsWith('runtime-parameters')?{values:{candidate_batches:3}}:{llm_provider:'deepseek',llm_model:'qwen-plus',api_key_configured:true,search_api_key_configured:true}))}));renderPage(<SettingsPage/>);await user.click(await screen.findByRole('button',{name:/测试 Exa/}));expect(await screen.findByText('密钥无效')).toBeInTheDocument()})
