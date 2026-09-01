import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { EvaluationPage } from './EvaluationPage'

const candidates = [1, 2, 3, 4, 5].map((index) => ({
  candidate_id: `C${index}`,
  text: `候选${index}`,
}))

const nodes = [
  { execution_id: 'e03', execution_order: 3, branch_id: 'b1', node_key: 'N03', output: { artifact: { llm: { queries: [{ query: '原始梗查询' }] } } } },
  { execution_id: 'e05', execution_order: 5, branch_id: 'b1', node_key: 'N05', output: { artifact: { llm: { original_text: '选定原始梗' } } } },
  { execution_id: 'e07', execution_order: 7, branch_id: 'b1', node_key: 'N07', output: { artifact: { llm: { queries: [{ query: '变式查询' }] } } } },
  { execution_id: 'e08', execution_order: 8, branch_id: 'b1', node_key: 'N08', output: { artifact: { sources: [{ source_id: 's1', title: '变式证据', url: 'https://example.com/evidence' }] } } },
  { execution_id: 'e09', execution_order: 9, branch_id: 'b1', node_key: 'N09', output: { artifact: { llm: { variants: [{ variant_text: '网友变式' }] } } } },
  { execution_id: 'e10', execution_order: 10, branch_id: 'b1', node_key: 'N10', output: { artifact: { llm: { template: '原句模板' } } } },
  { execution_id: 'e11', execution_order: 11, branch_id: 'b1', node_key: 'N11', output: { artifact: { llm: { decision: 'PASS' } } } },
  { execution_id: 'e12', execution_order: 12, branch_id: 'b1', node_key: 'N12', output: { artifact: { llm: { candidates } } } },
  { execution_id: 'e13', execution_order: 13, branch_id: 'b1', node_key: 'N13', output: { artifact: { llm: { qualified_candidate_ids: ['C2'] } } } },
  { execution_id: 'e14', execution_order: 14, branch_id: 'b1', node_key: 'N14', output: { artifact: { llm: { selected_candidate_id: 'C2', selection_reason: '综合得分最高' } } } },
  { execution_id: 'e15', execution_order: 15, branch_id: 'b1', node_key: 'N15', output: { artifact: { llm: { final_agu_text: '正式梗文案' } } } },
]

function mockEvaluationApi(
  admissionMode: 'HUMAN' | 'AUTO' = 'HUMAN',
  evaluationResponse: () => Response = () => new Response('{}'),
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/record')) return new Response(JSON.stringify({
      run: {
        run_id: 'r1',
        mode: 'MANUAL_SEED',
        state: 'WAITING_HUMAN_EVALUATION',
        admission_mode: admissionMode,
        active_branch_id: 'b1',
      },
      branches: [{ branch_id: 'b1', parent_branch_id: null, forked_from_execution_id: null }],
      sources: [],
      events: [],
      api_calls: [],
      evaluations: [],
      nodes,
    }))
    if (url.endsWith('/evaluation')) return evaluationResponse()
    return new Response(JSON.stringify({
      run_id: 'r1',
      run_version: 17,
      mode: 'MANUAL_SEED',
      state: 'WAITING_HUMAN_EVALUATION',
      admission_mode: admissionMode,
      active_branch_id: 'b1',
    }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderEvaluationPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/runs/r1/evaluation']}>
        <Routes>
          <Route path="/runs/:runId/evaluation" element={<EvaluationPage />} />
          <Route path="/runs/:runId" element={<div>任务详情</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function postCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
}

async function fillAllRequiredSelections(container: HTMLElement) {
  for (const group of container.querySelectorAll('.ant-radio-group')) {
    fireEvent.click(group.querySelector<HTMLInputElement>('input[type="radio"]')!)
  }

  await chooseSelectOption('主要问题节点', 'N02')
}

async function chooseSelectOption(label: string, option: string) {
  const input = screen.getByLabelText(label)
  const user = userEvent.setup()
  await user.click(input.closest('.ant-select')!.querySelector('.ant-select-selector')!)
  let visibleOption = Array.from(document.querySelectorAll<HTMLElement>('.ant-select-item-option-content'))
    .find((element) => element.textContent === option)
  if (!visibleOption) {
    fireEvent.change(input, { target: { value: option } })
    visibleOption = await waitFor(() => {
      const element = Array.from(document.querySelectorAll<HTMLElement>('.ant-select-item-option-content'))
        .find((item) => item.textContent === option)
      expect(element).toBeDefined()
      return element
    })
  }
  fireEvent.click(visibleOption!)
}

it('shows the seven evaluation modules in workflow order', async () => {
  mockEvaluationApi()
  renderEvaluationPage()

  const moduleTitles = [
    '原始梗搜索计划',
    '最终选定原始梗',
    '变式搜索计划',
    '最终变式搜索结果',
    '模板提取结果',
    '正式梗生成候选',
    '最终正式梗结果',
  ]
  for (const title of moduleTitles) expect(await screen.findByText(title)).toBeInTheDocument()

  const titleElements = moduleTitles.map((title) => screen.getByText(title))
  for (let index = 1; index < titleElements.length; index += 1) {
    expect(titleElements[index - 1].compareDocumentPosition(titleElements[index]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
})

it('marks missing structured fields and does not post an empty form', async () => {
  const fetchMock = mockEvaluationApi()
  renderEvaluationPage()

  await userEvent.setup().click(await screen.findByRole('button', { name: '提交评价' }))

  expect(await screen.findByText('请评价锚点准确度')).toBeInTheDocument()
  expect(postCalls(fetchMock)).toHaveLength(0)
})

it('posts the complete modular payload while keeping every text field optional', async () => {
  const fetchMock = mockEvaluationApi()
  const { container } = renderEvaluationPage()
  await screen.findByText('人工结构化评价')
  await fillAllRequiredSelections(container)

  fireEvent.submit(screen.getByRole('button', { name: '提交评价' }).closest('form')!)

  await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1), { timeout: 10_000 })
  const [, request] = postCalls(fetchMock)[0]
  const payload = JSON.parse(String((request as RequestInit).body))
  expect(payload).toMatchObject({
    original_search_plan: { comment: '' },
    selected_original_meme: { comment: '' },
    variant_search_plan: { comment: '' },
    variant_search_results: { comment: '' },
    template_extraction: { comment: '' },
    candidate_generation: {
      overall: { comment: '' },
      candidates: {
        C1: { modification_advice: '' },
        C2: { modification_advice: '' },
        C3: { modification_advice: '' },
        C4: { modification_advice: '' },
        C5: { modification_advice: '' },
      },
    },
    final_result: { comment: '' },
    main_problem_nodes: ['N02'],
    admission: { decision: 'ADMIT', override: null, reason: '' },
    overall_comment: '',
    expected_run_version: 17,
    branch_id: 'b1',
  })
  expect(payload).not.toHaveProperty('processing_chain')
  expect(payload).not.toHaveProperty('candidate_set')
}, 15_000)

it('keeps the evaluation form responsive after choosing a score', async () => {
  mockEvaluationApi()
  renderEvaluationPage()
  await screen.findByText('人工结构化评价')

  const firstScore = document.querySelector<HTMLInputElement>('input[type="radio"]')!
  fireEvent.click(firstScore)

  expect(firstScore).toBeChecked()
  expect(screen.getByRole('button', { name: '提交评价' })).toBeEnabled()
})

it('requires a final comment only when a non-best result has no replacement candidate', async () => {
  const fetchMock = mockEvaluationApi()
  const { container } = renderEvaluationPage()
  await screen.findByText('人工结构化评价')
  await fillAllRequiredSelections(container)
  fireEvent.click(screen.getByLabelText('否'))

  fireEvent.submit(screen.getByRole('button', { name: '提交评价' }).closest('form')!)

  expect(await screen.findByText('未选择更合适候选时，请说明最终结果的问题')).toBeInTheDocument()
  expect(postCalls(fetchMock)).toHaveLength(0)

  await chooseSelectOption('更合适候选（选填）', 'C1')
  fireEvent.submit(screen.getByRole('button', { name: '提交评价' }).closest('form')!)

  await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1), { timeout: 10_000 })
  const payload = JSON.parse(String((postCalls(fetchMock)[0][1] as RequestInit).body))
  expect(payload.final_result).toMatchObject({
    is_best_candidate: false,
    better_candidate_id: 'C1',
    comment: '',
  })
}, 15_000)

it('lets a concrete problem replace NO_OBVIOUS_PROBLEM so both values never coexist', async () => {
  mockEvaluationApi()
  renderEvaluationPage()
  await screen.findByText('人工结构化评价')

  await chooseSelectOption('主要问题节点', '无明显问题')
  await chooseSelectOption('主要问题节点', 'N02')

  const problemSelect = screen.getByLabelText('主要问题节点').closest('.ant-select')!
  expect(Array.from(problemSelect.querySelectorAll('.ant-select-selection-item-content'))
    .map((element) => element.textContent)).toEqual(['N02'])
}, 15_000)

it('shows the admission field that matches the run admission mode', async () => {
  mockEvaluationApi('AUTO')
  renderEvaluationPage()

  expect(await screen.findByText('自动准入复核')).toBeInTheDocument()
  expect(screen.queryByText('入库决定')).not.toBeInTheDocument()
})

it.each([
  {
    status: 409,
    title: '任务版本已变化（HTTP 409）',
    detail: { code: 'RUN_VERSION_CONFLICT', message: '运行版本已更新' },
    description: '请刷新评价材料后重新确认，当前填写内容仍保留。',
  },
  {
    status: 422,
    title: '评价内容未通过校验（HTTP 422）',
    detail: { code: 'VALIDATION_ERROR', message: '评价字段不完整' },
    description: '评价字段不完整',
  },
])('shows a clear HTTP $status submission error and keeps the form responsive', async ({ status, title, detail, description }) => {
  const fetchMock = mockEvaluationApi('HUMAN', () => new Response(
    JSON.stringify({ detail }),
    { status },
  ))
  const { container } = renderEvaluationPage()
  await screen.findByText('人工结构化评价')
  await fillAllRequiredSelections(container)

  fireEvent.submit(screen.getByRole('button', { name: '提交评价' }).closest('form')!)

  expect(await screen.findByText(title, {}, { timeout: 10_000 })).toBeInTheDocument()
  expect(screen.getByText(description)).toBeInTheDocument()
  expect(postCalls(fetchMock)).toHaveLength(1)
  expect(screen.getByRole('button', { name: '提交评价' })).toBeEnabled()
}, 15_000)
