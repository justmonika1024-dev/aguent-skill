import { expect, test } from '@playwright/test'

const emptyUsage = { calls:0,llm_calls:0,search_calls:0,input_tokens:0,output_tokens:0,total_tokens:0,cost_usd:0,latency_ms:0 }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let json: unknown = []
    if (path.endsWith('/runs') && route.request().method()==='POST') json = {run_id:'run-1',run_version:12,mode:'MANUAL_SEED',admission_mode:'HUMAN',state:'WAITING_HUMAN_EVALUATION',active_branch_id:'b1',seed_text:'你说的对，但是原神'}
    else if (path.endsWith('/runs/current')) json = { run:null,engine_state:'WAITING_START' }
    else if (path.endsWith('/runs/run-1/record')) json = {run:{run_id:'run-1',mode:'MANUAL_SEED',admission_mode:'HUMAN',state:'WAITING_HUMAN_EVALUATION',active_branch_id:'b1',seed_text:'你说的对，但是原神'},branches:[{branch_id:'b1'}],sources:[],events:[],api_calls:[],evaluations:[],nodes:[{node_key:'N12',status:'SUCCEEDED',output:{artifact:{llm:{candidates:[1,2,3,4,5].map(i=>({candidate_id:`C${i}`,text:`候选${i}`}))}}}},{node_key:'N14',status:'SUCCEEDED',output:{artifact:{llm:{selected_candidate_id:'C1'}}}}]}
    else if (path.endsWith('/runs/run-1')) json = {run_id:'run-1',run_version:12,mode:'MANUAL_SEED',admission_mode:'HUMAN',state:'WAITING_HUMAN_EVALUATION',active_branch_id:'b1',seed_text:'你说的对，但是原神'}
    else if (path.endsWith('/usage')) json = emptyUsage
    else if (path.endsWith('/system/config')) json = {llm_provider:'deepseek',llm_model:'qwen-plus',api_key_configured:true,search_api_key_configured:true}
    else if (path.endsWith('/system/runtime-parameters')) json = {values:{search_plan_budget:2,candidate_batches:3}}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(json)})
  })
})

test('starts a seed run, opens its persisted detail and enforces mandatory evaluation', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox',{name:'人工种子'}).fill('你说的对，但是原神')
  await page.getByRole('button',{name:'启动任务'}).click()
  await expect(page).toHaveURL(/\/runs\/run-1$/)
  await expect(page.getByRole('heading',{name:'任务详情'})).toBeVisible()
  await expect(page.getByText('N12')).toBeVisible()
  await page.getByRole('button',{name:/人工评价/}).click()
  await expect(page.getByRole('heading',{name:'人工结构化评价'})).toBeVisible()
  await expect(page.getByText('候选5')).toBeVisible()
  await expect(page.getByRole('button',{name:'提交评价'})).toBeDisabled()
})

test('switches run modes and navigates every management page', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'工作台'})).toBeVisible()
  await expect(page.getByRole('textbox',{name:'人工种子'})).toBeVisible()
  await page.getByText('自主发现',{exact:true}).click()
  await expect(page.getByRole('textbox',{name:'人工种子'})).toHaveCount(0)
  await expect(page.getByRole('switch',{name:'持续执行'})).toBeEnabled()
  for (const [label, heading] of [['运行历史','运行历史'],['正式梗库','正式梗库'],['策略版本','策略版本'],['设置','设置']] as const) {
    await page.getByText(label,{exact:true}).click()
    await expect(page.getByRole('heading',{name:heading})).toBeVisible()
  }
  await expect(page.getByText('qwen-plus')).toBeVisible()
  await expect(page.getByText('页面不会读取或显示 API Key')).toBeVisible()
})
