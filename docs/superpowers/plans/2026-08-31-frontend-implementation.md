# 凿 agugent 前端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现可从源码启动、能够操作现有 FastAPI 后端并完整展示状态机、人工评价、历史和正式梗的桌面端优先 Web 前端。

**Architecture:** 在 `frontend/` 建立 React 单页应用。TanStack Query 保存 REST 快照，原生 EventSource 只负责触发快照失效；页面按路由拆分，评价表单和状态机展示按 feature 拆分，所有 API 调用集中在类型化 client 中。

**Tech Stack:** React 19、TypeScript、Vite、Ant Design、React Router、TanStack Query、Vitest、Testing Library、Playwright、pnpm。

**Spec:** `outputs/凿agugent-技术方案.md`

## Global Constraints

- 前端固定使用 React + TypeScript、Vite、Ant Design、React Router、TanStack Query。
- 不引入 Redux；服务端快照是活动任务真相来源，SSE 事件仅触发缓存刷新。
- 前端不得接收或展示 API Key，只展示后端返回的 `api_key_configured` 布尔值。
- 每轮必须等待结构化人工评价；评价提交前所有必填项必须完成。
- 当前后端返回 404 的下架、恢复和策略操作必须显示为不可用，不伪造成功。
- 保留现有未提交后端改动，不重置、不覆盖、不顺带重构。

---

### Task 1: 前端工程、测试基线和开发代理

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/pnpm-lock.yaml`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/smoke.test.tsx`

**Interfaces:**
- Consumes: 后端开发地址 `http://127.0.0.1:8000/api/v1`。
- Produces: `pnpm dev`、`pnpm test --run`、`pnpm typecheck`、`pnpm build` 和 `/api` Vite 代理。

- [ ] 写一个渲染 `凿 agugent` 标题的失败 smoke test。
- [ ] 运行 `pnpm test --run`，确认因应用入口不存在而失败。
- [ ] 建立最小 React/Vite/Vitest 配置并让 smoke test 通过。
- [ ] 运行 `pnpm typecheck && pnpm test --run && pnpm build`。

### Task 2: 类型化 API client、查询键和应用外壳

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/queries.ts`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/AppShell.tsx`
- Create: `frontend/src/app/providers.tsx`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/styles/global.css`
- Test: `frontend/src/api/client.test.ts`
- Test: `frontend/src/app/AppShell.test.tsx`

**Interfaces:**
- Produces: `api.get<T>(path)`, `api.post<T>(path, body)`, `queryKeys`, `AppShell`。
- Error contract: `{ error: { code: string; message: string; request_id?: string } }` 转为 `ApiError`。

- [ ] 先测试成功 JSON、标准错误体和空响应三类 client 行为。
- [ ] 实现 fetch client 与 API 类型。
- [ ] 先测试侧栏包含工作台、运行历史、正式梗库、策略、设置入口。
- [ ] 实现 QueryClient、BrowserRouter、Ant Design 中文 locale、响应式应用壳。
- [ ] 运行 client 和 AppShell 测试。

### Task 3: 工作台、启动任务、控制命令和 SSE 刷新

**Files:**
- Create: `frontend/src/features/runs/runApi.ts`
- Create: `frontend/src/features/runs/useRunEvents.ts`
- Create: `frontend/src/features/runs/RunStatus.tsx`
- Create: `frontend/src/pages/DashboardPage.tsx`
- Test: `frontend/src/pages/DashboardPage.test.tsx`
- Test: `frontend/src/features/runs/useRunEvents.test.tsx`

**Interfaces:**
- Produces: `createRun`, `sendRunCommand`, `useCurrentRun`, `useRunEvents(runId)`。
- `createRun` 请求严格使用 `MANUAL_SEED | AUTO_DISCOVERY`、`HUMAN | AUTO` 和模式匹配的持续执行值。

- [ ] 测试人工模式要求种子、自主模式才启用持续执行、活动任务时显示当前节点。
- [ ] 实现工作台表单、费用摘要、待评价入口、暂停/恢复/终止控制。
- [ ] 测试 SSE 的 `node.completed`、`state.changed`、`stream.reset` 会失效当前 Run 查询。
- [ ] 实现 EventSource 生命周期和回退轮询。
- [ ] 运行工作台和 SSE 测试。

### Task 4: 任务详情、节点输出、证据、分支和事件时间线

**Files:**
- Create: `frontend/src/features/runs/NodeCard.tsx`
- Create: `frontend/src/features/runs/ArtifactView.tsx`
- Create: `frontend/src/features/runs/SourceEvidence.tsx`
- Create: `frontend/src/pages/RunDetailPage.tsx`
- Test: `frontend/src/pages/RunDetailPage.test.tsx`

**Interfaces:**
- Consumes: `GET /runs/:id`、`/record`、`/nodes`、`/sources`、`/usage`。
- Produces: 来源原文、Agent 归纳、生成内容三类视觉标签和完整 N01～N20 时间线。

- [ ] 测试节点卡片展示节点、状态、尝试次数、结构化 JSON，来源区单独展示 URL 和证据类型。
- [ ] 实现详情头部、节点列表、选中节点详情、分支摘要、API 消耗和事件时间线。
- [ ] 实现加载、404、运行失败和待评价状态。
- [ ] 运行任务详情测试。

### Task 5: 完整结构化人工评价

**Files:**
- Create: `frontend/src/features/evaluation/schema.ts`
- Create: `frontend/src/features/evaluation/ScoreField.tsx`
- Create: `frontend/src/features/evaluation/CandidateEvaluationCard.tsx`
- Create: `frontend/src/pages/EvaluationPage.tsx`
- Test: `frontend/src/pages/EvaluationPage.test.tsx`

**Interfaces:**
- Produces: 与后端 `HumanEvaluationRequest` 同形的 `HumanEvaluationPayload`。
- 必须包含 `processing_chain`、`candidate_set`、C1～C5、`final_result`、`main_problem_nodes`、`admission` 和 `overall_comment`。

- [ ] 测试未完成五候选评分时提交禁用并显示缺项。
- [ ] 测试 `is_best_candidate=false` 时要求替代候选或说明。
- [ ] 测试人工准入要求决定，自动准入显示维持/推翻选项。
- [ ] 实现四段评价表、候选原文与 Agent 自评分并列展示、1～5 分、可用性和建议。
- [ ] 实现完整 payload 提交、409 刷新提示和提交后跳回任务详情。
- [ ] 运行评价页测试。

### Task 6: 运行历史与正式梗库

**Files:**
- Create: `frontend/src/pages/RunsPage.tsx`
- Create: `frontend/src/pages/MemesPage.tsx`
- Create: `frontend/src/pages/MemeDetailPage.tsx`
- Test: `frontend/src/pages/ArchivePages.test.tsx`

**Interfaces:**
- Consumes: `GET /runs`、`GET /memes`、`GET /memes/:id`。
- Produces: 本地筛选后的表格和详情跳转；下架/恢复显示后端未开放禁用态。

- [ ] 测试运行状态、模式、准入决定和原始梗筛选。
- [ ] 测试正式梗展示原文、模板、最终文案、来源及来源 Run 链接。
- [ ] 实现历史和正式梗页面、空态、错误态和复制文案按钮。
- [ ] 运行归档页面测试。

### Task 7: 策略只读页和脱敏设置页

**Files:**
- Create: `frontend/src/pages/StrategiesPage.tsx`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Test: `frontend/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: `/strategies`、`/system/config`、`/system/runtime-parameters`、两类 connection-tests。
- Produces: 脱敏配置状态、可编辑运行参数和连接测试结果。

- [ ] 测试页面只显示 Key 是否已配置，不显示或接受 Key 文本框。
- [ ] 测试连接测试成功和失败提示。
- [ ] 实现配置卡、参数表单、连接测试按钮和空策略状态。
- [ ] 运行设置页测试。

### Task 8: 端到端联调、可访问性和交付验证

**Files:**
- Create: `frontend/tests/e2e/app.spec.ts`
- Create: `frontend/README.md`
- Modify: `backend/app/main.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: 源码启动说明、Vite 代理联调、前端构建产物和 Playwright 主流程。

- [ ] 先写 Playwright 测试：工作台可打开、可创建任务、任务详情可显示、评价缺项时不能提交、历史与正式梗页面可访问。
- [ ] 若前后端分端口直接访问，给 FastAPI 增加仅允许 `FRONTEND_ORIGIN` 的 CORS；开发模式优先使用 Vite `/api` 代理。
- [ ] 修复键盘焦点、表单 label、窄屏布局和空白 JSON 溢出。
- [ ] 运行 `pnpm lint`、`pnpm typecheck`、`pnpm test --run`、`pnpm build`、`pnpm exec playwright test`。
- [ ] 重新运行后端 `pytest -q tests`，确认 CORS 或 OpenAPI 调整无回归。
