# “凿 agugent”MVP 技术方案

- 文档版本：V1.0-draft
- 日期：2026-08-27
- 文档状态：待评审
- 对应 PRD：`outputs/凿agugent-PRD.md`
- 节点需求基线：`work/凿agugent-节点可行性实验方案.md`

## 1. 文档目标

本文档给出“凿 agugent”MVP 的固定开发方案。开发者应当能够仅依据本文档和对应 PRD：

1. 从源码启动前后端；
2. 创建 SQLite 数据库并执行迁移；
3. 接入 Exa Search、OpenAI 或 DeepSeek；
4. 实现单任务串行状态机、人工评价和策略反馈；
5. 完成单元测试、集成测试和浏览器端到端测试；
6. 根据文档中的验收命令完成本地自测。

本文档固定技术实现，不重新定义已经确认的节点业务职责。若本文与 PRD 冲突，产品行为以 PRD 和用户后续确认内容为准；若节点字段与临时实验文档冲突，以临时实验文档中并入 N11.5 后的最新版契约为基线。

## 2. MVP 范围与非目标

### 2.1 范围

- 中文纯文本文案梗；
- 来源可以是各种公开网页，但只检索和整理文字；
- 人工种子和自主发现两种模式；
- Exa Search API 搜索原始梗、出处和网友变式；
- 单一模型完成全部 LLM 节点，启动时选择 OpenAI 或 DeepSeek；
- 每轮生成 5 条候选，自评分后只选择一条；
- 每轮必须等待结构化人工评价；
- 评价后立即生成并应用下一版策略；
- 人工准入和自动准入两种正式梗入库方式；
- 支持暂停、继续、终止、重试节点、修正输出和切换有效分支；
- 单机、单用户、同一时间一个活动任务；
- 一个本地 SQLite 文件，两组业务表；
- 前后端分离，从源码启动。

### 2.2 非目标

- 不处理图片、视频画面、音频或表情包；
- 不做批量并发任务；
- 不做分布式部署、Redis、消息队列和容器编排；
- 不做应用崩溃后的活动任务恢复；
- 不做用户、组织、权限和多租户；
- 不做模型训练、微调或长期统计学习；
- 不做 MySQL 实际部署，只保证结构和 ORM 用法可迁移；
- 不保证搜索结果代表最早出处或真实全网传播量；
- 不实现 Google、Bing、Brave、Serper 等其他搜索 Provider。

### 2.3 后续确认对旧版 PRD 表述的覆盖

以下规则来自 PRD 完成后的进一步确认，开发时以本节为准：

- 自主发现查重只向模型注入正式梗库的 `id+title`；
- 失败、被拒绝和未入库的运行记录不参与标题查重，也不直接注入发现提示词；
- 这些失败经验只能经人工评价和 N19 StrategyPatch 间接影响后续搜索策略；
- 持续执行是一个开关：开启时本轮完成后自动开始下一轮，关闭时回到等待人工启动；不存在“本轮结束后暂停”这一独立功能；
- 第一次版本不实现活动任务恢复，数据库中的历史归档不能被用来自动续跑中断任务。

## 3. 总体技术栈

### 3.1 后端

| 项目 | 固定选择 |
|---|---|
| 语言 | Python 3.12 |
| Web 框架 | FastAPI |
| 数据模型 | Pydantic 2 |
| ORM | SQLAlchemy 2 |
| 数据库迁移 | Alembic |
| SQLite 异步驱动 | aiosqlite |
| HTTP 客户端 | httpx.AsyncClient |
| LLM SDK | openai.AsyncOpenAI |
| ASGI Server | Uvicorn |
| 依赖管理 | uv，提交 `uv.lock` |
| 测试 | pytest、pytest-asyncio、pytest-cov、respx |
| 质量检查 | Ruff、mypy |

`pyproject.toml` 使用主版本范围，首次实现时由 `uv lock` 固定全部精确版本。建议约束：

```toml
requires-python = ">=3.12,<3.13"

dependencies = [
  "fastapi>=0.115,<1",
  "pydantic>=2.10,<3",
  "pydantic-settings>=2.7,<3",
  "sqlalchemy>=2.0,<3",
  "alembic>=1.14,<2",
  "aiosqlite>=0.20,<1",
  "httpx>=0.27,<1",
  "openai>=1.60,<3",
  "uvicorn[standard]>=0.34,<1"
]
```

若当前 OpenAI Python SDK 的调用签名发生变化，以实现时的官方 OpenAI 文档和锁定版本为准，但 Provider 对状态机暴露的内部接口不得改变。

### 3.2 前端

| 项目 | 固定选择 |
|---|---|
| 框架 | React + TypeScript |
| 构建工具 | Vite |
| UI | Ant Design |
| 路由 | React Router |
| 服务端状态 | TanStack Query |
| API 类型 | OpenAPI schema + openapi-typescript 生成 |
| 单元测试 | Vitest + Testing Library |
| 端到端测试 | Playwright |
| 依赖管理 | pnpm，提交 `pnpm-lock.yaml` |

不引入 Redux。活动任务状态以服务端快照为准，SSE 事件用于增量刷新 TanStack Query 缓存。

### 3.3 数据库

- 文件：`data/zao_agugent.db`；
- SQLite WAL 模式；
- `PRAGMA foreign_keys=ON`；
- 单文件内使用 `run_*` 和 `meme_*` 两组表；
- UUID 在应用层生成，数据库统一保存为 36 位字符串；
- 时间统一保存 UTC；
- JSON 使用 SQLAlchemy `JSON` 类型；
- 不使用 SQLite FTS、触发器、数据库 ENUM 和专属 SQL。

### 3.4 通信方式

- REST：读取快照、提交任务、评价和控制命令；
- SSE：推送节点进度、状态变化和人工等待事件；
- 不使用 WebSocket；
- 不使用逐 Token LLM 流式输出。

## 4. 总体架构

```text
React Web
  ├── REST API ───────────────────────────────┐
  └── SSE EventSource ────────────────────────┤
                                               ▼
FastAPI
  ├── API Router
  ├── WorkflowEngine（单 asyncio 任务）
  │    ├── RunContext（活动任务内存态）
  │    ├── NodeRegistry
  │    ├── TransitionTable
  │    ├── CommandQueue
  │    ├── EventBus
  │    └── NodeResultValidator
  ├── Providers
  │    ├── ExaSearchProvider
  │    ├── OpenAIResponsesProvider
  │    └── DeepSeekChatProvider
  ├── AdmissionService
  ├── StrategyService
  ├── ArchiveService
  └── SQLAlchemy Repositories
         └── SQLite / 可迁移 MySQL
```

关键边界：

- LLM 不直接搜索、不访问数据库、不写状态；
- Exa 节点只检索和清洗，不判断哪个梗最好；
- Node 只返回 `NodeResult`，不能决定下一状态；
- `TransitionTable` 是唯一状态跳转来源；
- 活动任务以 `RunContext` 为准，数据库不用于恢复活动任务；
- 正式梗自动准入可以在 N17 立即落库，来源证据以独立快照保存。

## 5. 工程目录

```text
zao-agugent/
├── .env.example
├── README.md
├── data/
│   └── .gitkeep
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── migrations/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   ├── contracts/
│   │   │   ├── api/
│   │   │   └── nodes/
│   │   ├── workflow/
│   │   │   ├── engine.py
│   │   │   ├── context.py
│   │   │   ├── registry.py
│   │   │   ├── transitions.py
│   │   │   ├── commands.py
│   │   │   ├── events.py
│   │   │   ├── validators.py
│   │   │   └── nodes/
│   │   ├── providers/
│   │   │   ├── llm/
│   │   │   └── search/
│   │   ├── services/
│   │   ├── db/
│   │   │   ├── models/
│   │   │   ├── repositories/
│   │   │   └── session.py
│   │   └── prompts/
│   │       ├── common/
│   │       └── nodes/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contract/
│       └── fixtures/
└── frontend/
    ├── package.json
    ├── pnpm-lock.yaml
    ├── vite.config.ts
    ├── playwright.config.ts
    ├── src/
    │   ├── api/
    │   ├── components/
    │   ├── pages/
    │   ├── features/
    │   ├── hooks/
    │   └── types/generated/
    └── tests/
```

## 6. 配置与源码启动

### 6.1 `.env.example`

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
FRONTEND_ORIGIN=http://127.0.0.1:5173
DATABASE_URL=sqlite+aiosqlite:///../data/zao_agugent.db

LLM_PROVIDER=openai
LLM_MODEL=gpt-5
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=

SEARCH_PROVIDER=exa
EXA_BASE_URL=https://api.exa.ai
EXA_API_KEY=
EXA_TIMEOUT_SECONDS=30
```

DeepSeek 模板：

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
```

约束：

- `LLM_PROVIDER` 只能为 `openai` 或 `deepseek`；
- `SEARCH_PROVIDER` 在 MVP 只能为 `exa`；
- provider、model、base URL、API Key 启动后不可修改；
- 前端只能查看脱敏值、修改运行参数和执行连接测试；
- Key 不进入日志、SSE、数据库和错误详情；
- 必填项缺失时后端拒绝启动并输出字段名，不输出已有值。

### 6.2 启动命令

后端：

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --port 5173
```

OpenAPI 类型生成：

```bash
cd frontend
pnpm openapi:generate
```

后端健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

## 7. LLM Provider 实现

### 7.1 统一接口

```python
class LLMProvider(Protocol):
    async def generate(self, request: NodeLLMRequest) -> LLMCallResult: ...
    async def connection_test(self) -> ConnectionTestResult: ...
```

`NodeLLMRequest` 至少包含：

```text
node_key
system_prompt
user_payload
output_schema
schema_name
parameter_profile
request_metadata
```

`LLMCallResult` 统一为：

```text
raw_text
parsed_json
provider_request_id
provider
model
input_tokens
output_tokens
total_tokens
latency_ms
finish_reason
```

### 7.2 OpenAI

使用 `AsyncOpenAI(base_url=..., api_key=...)` 的 Responses API。结构化输出通过 Responses 的 `text.format` JSON Schema 完成，且返回后仍执行本地 Pydantic 校验。官方参考：

- [Responses API](https://platform.openai.com/docs/api-reference/responses/create)
- [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

示意：

```python
response = await client.responses.create(
    model=settings.llm_model,
    input=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_json},
    ],
    text={
        "format": {
            "type": "json_schema",
            "name": schema_name,
            "schema": output_schema,
            "strict": True,
        }
    },
    max_output_tokens=params.max_output_tokens,
)
raw_text = response.output_text
```

实现必须以锁定 SDK 版本的类型定义和官方文档为准，不能只依赖上述示意代码。

### 7.3 DeepSeek

DeepSeek 使用同一 `AsyncOpenAI` SDK，但调用 Chat Completions：

```python
completion = await client.chat.completions.create(
    model=settings.llm_model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_json},
    ],
    response_format={"type": "json_object"},
    max_tokens=params.max_output_tokens,
    temperature=params.temperature,
)
```

DeepSeek 不假设支持 `/responses` 或严格 JSON Schema。Schema 以文本加入提示词，返回值由本地 Pydantic 完整校验。

### 7.4 参数档案

| 档案 | 节点 | temperature | 默认最大输出 Token |
|---|---|---:|---:|
| analysis | 规划、判断、模板处理 | 0.2 | 4000 |
| creative | N12 | 0.8 | 3000 |
| evaluation | N13、N14、N17、N19 | 0.1 | 4000 |

参数可以在运行时修改。节点开始执行时复制参数快照；修改只影响后续节点。若目标模型不支持某参数，Provider 必须省略该参数并在连接测试中展示“未使用”，不能转换为其他含义的参数。

### 7.5 结构化输出管线

```text
模型响应
→ 提取JSON文本
→ JSON解析
→ Pydantic模型校验（extra=forbid）
→ source_id等引用完整性校验
→ 节点确定性业务校验
→ NodeResult
```

每次节点最多三次 LLM 调用：

1. 初次生成；
2. 最多一次格式修复；
3. 最多一次确定性规则反馈后的重新生成。

格式修复只接收原输出、Schema和校验错误。业务重生成接收明确违规项。仍失败时进入 `WAITING_HUMAN_INTERVENTION`。

### 7.6 提示词版本

每个节点提示词分为：

```text
ImmutableNodePolicy
+ MutableNodeStrategy
+ NodeInputPayload
+ OutputSchema
```

提示词文件必须有独立版本号，例如 `n12.v3.md`。`run_node_executions.prompt_version` 记录实际版本。不可变规则不能由 N19 修改。

## 8. Exa Search Provider 实现

### 8.1 接口

```python
class SearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> SearchBatch: ...
    async def connection_test(self) -> ConnectionTestResult: ...
```

MVP 只有 `ExaSearchProvider`。请求：

```http
POST https://api.exa.ai/search
Content-Type: application/json
x-api-key: <secret>
```

原始梗默认：

```json
{
  "query": "...",
  "type": "auto",
  "numResults": 5,
  "contents": {"text": {"maxCharacters": 1500}}
}
```

变式默认每条最多 10 个结果，正文最多 1200 字符。

### 8.2 查询策略

- 原始梗：默认最多 4 条查询，至少一条 `keyword` 和一条 `auto`；
- 变式：默认最多 6 条查询，至少两条 `keyword` 和两条 `auto`；
- 禁止依赖 `site:`、多组引号、减号排除等 Google 专用语法；
- 排除原始梗转载由 N09 完成，不在 Exa 查询中强制处理；
- 不依赖 `resolvedSearchType`，实验中该字段可能为空；
- 保存 `requestId`、`searchTime` 和 `costDollars`。

### 8.3 清洗和去重

`canonical_url` 处理：

1. host 转小写；
2. 删除 fragment；
3. 删除 `utm_*`、`spm` 等已知跟踪参数；
4. 保留内容 ID、页码等业务参数；
5. 空内容 ID 等明显不完整 URL 标记 `INVALID_URL`；
6. 不跟随链接改写到另一个域名。

正文状态：

```text
VALID
EMPTY
NOT_FOUND_PAGE
LOGIN_REQUIRED
INVALID_URL
EXTRACTION_FAILED
```

证据类型：

```text
EXTRACTED_TEXT
TITLE_TEXT
TITLE_ONLY
```

同一 URL 只保存一份正文，同时记录全部 `query_id` 命中关系。

### 8.4 N09 输入裁剪

变式搜索最多得到 60 个结果，默认只向 N09 提供 30 个。排序加分项：

- 标题或正文命中固定锚点；
- 多条查询召回同一 URL；
- 正文有效；
- Exa 排名较高。

同时为每条查询保留至少一部分高排名结果，防止语义查询结果全部被关键词结果挤掉。完整原始结果仍保留在运行快照中。

### 8.5 重试

- 网络超时、429、5xx：最多重试 2 次，指数退避加随机抖动；
- 401：不重试，提示 API Key；
- 402：不重试，提示额度或计费；
- 单条查询失败：记录后继续其他查询；
- 全部查询失败：进入人工干预；
- 有结果但证据不足：走状态机业务回退，不作为服务异常。

## 9. 状态机实现

### 9.1 核心组件

```text
WorkflowEngine
├── RunContext
├── NodeRegistry
├── TransitionTable
├── NodeResultValidator
├── CommandQueue
├── EventBus
├── ArchiveService
└── AdmissionService
```

一个活动任务对应一个 `asyncio.Task`。节点串行执行，外部 I/O 异步等待。

### 9.2 RunContext

```text
run_id
run_version
mode
admission_mode
continuous_enabled
current_node
current_state
suspended_state
active_branch_id
branches
active_artifacts
strategy_version_id
strategy_snapshot
loop_counters
pause_requested
terminate_requested
pending_human_action
event_buffer
```

- 节点产物以 execution ID 不可变保存；
- `active_artifacts` 指向当前有效分支采用的产物；
- Node 不得直接修改 Context；
- 每次成功状态变化 `run_version + 1`；
- 应用崩溃后不恢复 RunContext。

### 9.3 Node 接口

```python
class WorkflowNode(ABC):
    key: NodeKey
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    async def execute(
        self,
        node_input: BaseModel,
        services: NodeServices,
    ) -> NodeResult:
        ...
```

NodeResult：

```text
node_key
status
outcome
artifact
human_summary
metrics
validation_report
```

Node 只能返回 outcome，不能返回或修改目标状态。

### 9.4 引擎循环

```text
处理CommandQueue
→ 检查pause/terminate
→ 构造当前节点白名单输入
→ NodeRegistry取得节点
→ 执行节点
→ 校验NodeResult
→ 原子提交到RunContext
→ 发布SSE事件
→ TransitionTable计算下一节点
→ run_version加一
```

### 9.5 系统状态

```text
WAITING_START
RUNNING
PAUSING
PAUSED
WAITING_HUMAN_EVALUATION
WAITING_HUMAN_INTERVENTION
ARCHIVING
COMPLETED
FAILED
TERMINATED
```

### 9.6 安全循环预算

| 循环 | 默认上限 |
|---|---:|
| 每个方向的原始搜索计划 | 2 |
| 每轮自主发现方向 | 5 |
| 每个原始梗的变式搜索计划 | 2 |
| 模板提取 | 3 |
| 候选批次 | 3 |
| 正式标题生成 | 2 |
| 单节点 LLM 调用 | 3 |

运行参数可以人工修改，但 N19 不得扩大这些上限。

### 9.7 主转移表

| 当前节点 | outcome/条件 | 下一节点 |
|---|---|---|
| START | MANUAL_SEED | N01 |
| START | AUTO_DISCOVERY | N02 |
| N01 | ACCEPTED | N03 |
| N02 | PLANNED | N03 |
| N03 | PLAN_READY | N04 |
| N04 | RESULTS_FOUND | N05 |
| N04 | NO_RESULTS且有预算 | N03 |
| N04 | NO_RESULTS无预算，AUTO | N02 |
| N04 | NO_RESULTS无预算，MANUAL | WAITING_HUMAN_INTERVENTION |
| N04 | ALL_QUERIES_FAILED | WAITING_HUMAN_INTERVENTION |
| N05 | SELECTED | N06 |
| N05 | NO_QUALIFIED_CANDIDATE且有预算 | N03 |
| N05 | NO_QUALIFIED_CANDIDATE无预算，AUTO | N02 |
| N05 | NO_QUALIFIED_CANDIDATE无预算，MANUAL | WAITING_HUMAN_INTERVENTION |
| N06 | NOT_DUPLICATE | N07 |
| N06 | SUSPECTED | N06详情阶段 |
| N06 | DUPLICATE，AUTO | N02 |
| N06 | DUPLICATE，MANUAL | N03 |
| N06 | HUMAN_REVIEW_REQUIRED | WAITING_HUMAN_INTERVENTION |
| N07 | PLAN_READY | N08 |
| N08 | RESULTS_FOUND | N09 |
| N08 | NO_RESULTS且有预算 | N07 |
| N08 | NO_RESULTS无预算，AUTO | N02 |
| N08 | NO_RESULTS无预算，MANUAL | WAITING_HUMAN_INTERVENTION |
| N08 | ALL_QUERIES_FAILED | WAITING_HUMAN_INTERVENTION |
| N09 | SUFFICIENT | N10 |
| N09 | INSUFFICIENT且有预算 | N07 |
| N09 | INSUFFICIENT无预算，AUTO | N02 |
| N09 | INSUFFICIENT无预算，MANUAL | WAITING_HUMAN_INTERVENTION |
| N10 | TEMPLATE_READY | N11 |
| N11 | PASS | N11.5 |
| N11 | REEXTRACT且有预算 | N10 |
| N11 | MORE_EVIDENCE且有预算 | N07 |
| N11 | REEXTRACT/MORE_EVIDENCE无预算，AUTO | N02 |
| N11 | REEXTRACT/MORE_EVIDENCE无预算，MANUAL | WAITING_HUMAN_INTERVENTION |
| N11.5 | DIRECT_SLOT_FILL | N12 |
| N11.5 | STRUCTURE_PRESERVING_REWRITE | N12 |
| N11.5 | ABANDON_ORIGINAL，AUTO | N02 |
| N11.5 | ABANDON_ORIGINAL，MANUAL | N03 |
| N12 | VALID_BATCH | N13 |
| N13 | HAS_QUALIFIED | N14 |
| N13 | ALL_UNQUALIFIED且有预算 | N12 |
| N13 | ALL_UNQUALIFIED无预算 | N11.5重新评估 |
| N14 | SELECTED | N15 |
| N15 | DRAFT_READY | N16 |
| N16 | NOT_DUPLICATE | N17 |
| N16 | SUSPECTED | N16详情阶段 |
| N16 | DUPLICATE且有预算 | N15 |
| N16 | DUPLICATE无预算 | WAITING_HUMAN_INTERVENTION |
| N16 | HUMAN_REVIEW_REQUIRED | WAITING_HUMAN_INTERVENTION |
| N17 | AUTO_DECIDED | N18 |
| N17 | WAIT_HUMAN_DECISION | N18 |
| N18 | EVALUATION_SUBMITTED | N19 |
| N19 | PATCH_VALID | N20 |
| N19 | PATCH_INVALID | WAITING_HUMAN_INTERVENTION |
| N20 | continuous=false | 当前run=`COMPLETED`；引擎=`WAITING_START` |
| N20 | continuous=true | 新一轮 AUTO_DISCOVERY |

`COMPLETED` 是不可逆的单轮运行终态，`WAITING_START` 是应用级引擎状态。关闭持续执行时不得把已经完成的 run 改回可运行状态；`GET /runs/current` 返回“无活动 run + engine_state=WAITING_START”。

N06/N16 的“详情阶段”是同一节点执行内部的第二次LLM判断，不创建新的业务节点。N13候选批次耗尽后的N11.5重新评估最多一次：只能把 `DIRECT_SLOT_FILL` 降级为 `STRUCTURE_PRESERVING_REWRITE` 并重置一次候选批次，或输出 `ABANDON_ORIGINAL`；不得维持原路由后无限重试。

## 10. N01～N20 具体实现

本节只规定技术执行方式。提示词和完整业务字段以节点实验文档为基线；每个输出模型均使用 `extra="forbid"`。

### N01 `ACCEPT_MANUAL_SEED`

- 类型：LLM analysis；
- 前置代码校验：非空、最长 2000 字、包含可识别中文线索；
- 输入：原始 seed、N01 策略；
- 输出：规范化 seed、核心表达、可能原句、歧义、查询概念；
- 禁止：搜索、判断真实出处；
- outcome：`ACCEPTED`；输入非法在创建任务 API 阶段直接返回 422。

### N02 `PLAN_DISCOVERY_DIRECTION`

- 类型：LLM analysis；
- 输入：正式梗全部 `{id,title}`、当前策略、本轮已尝试方向；
- 不输入失败库或未入库标题；
- 校验：不能与本轮方向或正式标题规范化完全相同；必须是中文文本梗方向；
- 输出仅为发现假设，不得声称已验证出处或传播度；
- outcome：`PLANNED`。

### N03 `BUILD_ORIGINAL_SEARCH_PLAN`

- 类型：LLM analysis；
- 输入：N01/N02产物、查询预算、已执行查询、失败摘要；
- Schema 允许 3～8 条，但不能超过运行预算；
- 每条含 `query_id/query/search_type/purpose/priority/expected_anchors/result_limit`；
- 至少一条 keyword 和一条 auto；
- 查询规范由代码校验，不合规则走业务重生成；
- outcome：`PLAN_READY`。

### N04 `SEARCH_ORIGINAL_CANDIDATES`

- 类型：确定性 Exa；
- 串行执行 N03 查询；
- 每条默认 5 个结果、正文 1500 字；
- URL 去重，证据编号 `O001...`；
- 输出批次、sources、费用、耗时、有效正文和域名数；
- 不调用 LLM，不选择原始梗；
- outcome：`RESULTS_FOUND/NO_RESULTS/ALL_QUERIES_FAILED`。

### N05 `EVALUATE_AND_SELECT_ONE_ORIGINAL_MEME`

- 类型：LLM analysis；
- 输入：N04真实证据和N05策略；
- 只能选择一条；
- 输出必须包含 `evidence_quotes[{source_id,quote}]`；
- 代码验证 quote 为标题或正文真实子串；
- original_text 必须等于引用或只做空白、标点规范化；
- 禁止拼接多个来源创造原句；
- outcome：`SELECTED/NO_QUALIFIED_CANDIDATE`。

### N06 `CHECK_ORIGINAL_DUPLICATION`

- 类型：代码预检查 + 两阶段 LLM；
- 第一阶段只输入正式梗 `{id,title}`；
- 规范化标题完全一致时代码直接判重复；
- LLM最多返回5个疑似ID；
- Repository只读取疑似记录的标题、原始梗、模板和最终文案；
- 第二阶段输出 `NOT_DUPLICATE/DUPLICATE/HUMAN_REVIEW_REQUIRED`；
- 所有请求ID必须存在；
- 只检查N05最终选择的一条。

### N07 `BUILD_VARIANT_SEARCH_PLAN`

- 类型：LLM analysis；
- 输入：唯一原始梗、固定锚点、来源、预算、上轮不足原因；
- Schema 允许 4～10 条，默认最多 6 条；
- 默认至少两条 keyword、两条 auto；
- 不强制使用排除词；
- 不重复已失败查询；
- outcome：`PLAN_READY`。

### N08 `SEARCH_VARIANTS`

- 类型：确定性 Exa；
- 每条默认10个结果、正文1200字；
- URL编号 `V001...`；
- 完整结果保存到RunContext，最多30条裁剪输入N09；
- 同一页面可在N09提取多个变式；
- outcome：`RESULTS_FOUND/NO_RESULTS/ALL_QUERIES_FAILED`。

### N09 `EVALUATE_VARIANT_EVIDENCE`

- 类型：LLM分类 + 代码统计；
- 分类：`VALID_VARIANT/ORIGINAL_REPOST/IRRELEVANT/INSUFFICIENT_CONTEXT/DUPLICATE_VARIANT`；
- 每条有效变式必须提供真实 source_id 和原文 quote；
- 代码验证 quote、文案去重并重新计算指标；
- 充分条件固定为：至少3条不同变式、至少2个URL、共享至少一个固定表达；
- `is_sufficient` 由代码生成，不接受LLM自报；
- outcome：`SUFFICIENT/INSUFFICIENT`。

### N10 `EXTRACT_TEMPLATE`

- 类型：LLM analysis；
- 输入：唯一原始梗和N09有效变式；
- 输出固定片段、槽位、语义、语法作用、必填性、例值和证据；
- 不得提前包含 agu 或凿；
- source_id和推导引用由代码校验；
- outcome：`TEMPLATE_READY`。

### N11 `VALIDATE_TEMPLATE`

- 类型：LLM evaluation + 代码指标；
- 对原句及每条有效变式逐条槽位绑定、重建；
- 每个输入案例必须且只能出现一次；
- coverage 由代码按通过案例数计算；
- 默认 PASS：原句匹配、覆盖率 >= 0.8、准确度 >= 4；
- outcome：`PASS/REEXTRACT/MORE_EVIDENCE`。

### N11.5 `ASSESS_AGU_ADAPTABILITY`

- 类型：LLM analysis；
- 固定目标语义：agu 是人物和动作受事，凿是直接施加于 agu 的及物动作，动作处于肯定范围；
- 分析槽位语义、否定范围、动作槽、节奏和笑点；
- route 只能为 `DIRECT_SLOT_FILL/STRUCTURE_PRESERVING_REWRITE/ABANDON_ORIGINAL`；
- direct 分数 >= 4 才能直接填槽；否则 structure 分数 >= 3 才能保结构改写；
- 蓝图只能描述结构，不能提前生成候选；
- outcome 等于经代码阈值校验后的 route。

### N12 `GENERATE_AGU_CANDIDATES`

- 类型：LLM creative；
- 一次严格生成5条，ID固定为 `C1...C5`；
- 每条必须原样含小写ASCII `agu` 和汉字“凿”；
- route 必须等于N11.5；
- DIRECT模式校验固定片段与槽位；STRUCTURE模式校验must_preserve和may_rewrite；
- 代码在N13前执行字面量、数量、ID、锚点、路由和可确定动作肯定性检查；
- 失败进入结构/业务重生成，不占候选批次；
- outcome：`VALID_BATCH`。

### N13 `SELF_SCORE_CANDIDATES`

- 类型：LLM evaluation；
- 输入只含候选文本、模板、原始梗、route、must_preserve和评分规则，不输入N12自我解释；
- 评分：通顺、辨识、agu/凿自然、幽默、节奏、改写合理性；
- 关键字段 `action_affirmed/qualified/critical_failures`；
- 默认合格：六维均分 >= 3.5，且通顺、辨识、自然度均 >= 3，action_affirmed=true；
- 代码重新计算平均值并校验推荐ID存在；
- outcome：`HAS_QUALIFIED/ALL_UNQUALIFIED`。

### N14 `SELECT_FINAL_CANDIDATE`

- 类型：LLM evaluation；
- 只输入合格候选；
- 只能从已有文本中选择，不允许改写；
- 代码验证 ranked IDs 完整无重复，selected ID位于合格集合；
- outcome：`SELECTED`。

### N15 `GENERATE_FORMAL_MEME_DRAFT`

- 类型：LLM analysis；
- 输入已选候选、原始梗、模板、route和主来源；
- 生成4～40字符的正式标题、normalized title和正式草稿；
- final_agu_text必须与N14选中文本完全一致；
- 不允许以运行编号作为标题；
- outcome：`DRAFT_READY`。

### N16 `FINAL_TITLE_DEDUP_CHECK`

- 实现复用N06两阶段查重器，但输入为执行时最新正式标题库；
- 当前任务因旧分支自动准入产生的正式记录不参与自我查重，其他任务的ACTIVE和UNPUBLISHED记录均参与；
- 只重新生成标题包装，不修改候选；
- outcome：`NOT_DUPLICATE/DUPLICATE/HUMAN_REVIEW_REQUIRED`。

### N17 `DECIDE_ADMISSION`

- 类型：AdmissionService + 一次内容安全结构化分类；
- 人工和自动模式都先完成内容安全分类；非PASS内容不能通过人工准入；
- 人工模式：输出 `WAIT_HUMAN_DECISION`，决定随N18评价提交；
- 自动模式：按第11节硬阈值决定并立即执行正式库写入或不入库；
- outcome：`AUTO_DECIDED/WAIT_HUMAN_DECISION`。

### N18 `WAIT_FOR_HUMAN_EVALUATION`

- 类型：等待节点，不调用LLM；
- 状态设为 `WAITING_HUMAN_EVALUATION`；
- 验证结构化评分、必填意见和准入决定/推翻字段；
- 自动准入被推翻时立即更新正式库并写状态历史；
- 人工修改模板、候选或最终结果不能直接覆盖评价对象，必须转成 `CORRECT_NODE_OUTPUT` 创建分支并重跑受影响的后续节点；
- 上游分支变化后，原评价草稿失效，重新到达N18时生成新的评价表；
- outcome：`EVALUATION_SUBMITTED`。

准入处理矩阵：

| N17模式与结论 | N18必填决定 | N18提交时的正式库动作 |
|---|---|---|
| 人工准入 | `ADMIT` | 内容安全为PASS时创建正式梗；否则拒绝评价提交并展示安全原因 |
| 人工准入 | `NOT_ADMIT` | 不创建正式梗 |
| 自动结论 `ADMIT` | `KEEP` | 保持N17已创建的ACTIVE正式梗 |
| 自动结论 `ADMIT` | `OVERRIDE_TO_NOT_ADMIT` | 将N17成果设为UNPUBLISHED并写准入、状态历史 |
| 自动结论 `NOT_ADMIT` | `KEEP` | 不创建正式梗 |
| 自动结论 `NOT_ADMIT` | `OVERRIDE_TO_ADMIT` | 仅在内容安全为PASS时创建ACTIVE正式梗并写准入历史 |

`REJECT/UNCERTAIN` 的内容安全结果禁止人工强制入库，但仍允许完成其他评价和选择 `NOT_ADMIT/KEEP`。

### N19 `UPDATE_STRATEGY`

- 类型：LLM evaluation + 受限补丁执行器；
- 输入完整有效分支、自评分、人工评价、人工修正和当前策略；
- 输出受限StrategyPatch；
- 校验反馈引用、路径白名单、旧值、不可变规则和StrategyModel；
- 生成新策略版本但先保存在RunContext待提交；
- outcome：`PATCH_VALID/PATCH_INVALID`。

### N20 `COMPLETE_RUN`

- 类型：确定性归档节点；
- 一个数据库事务内：归档运行记录、评价、分支、节点、策略补丁；创建并激活策略版本；补齐正式梗与运行证据关联；
- 事务失败则回滚，不开始下一轮；
- continuous=false：回到等待启动；
- continuous=true：事务成功后创建下一轮AUTO_DISCOVERY；
- outcome：`COMPLETED/NEXT_RUN`。

## 11. 自动准入实现

自动准入必须同时满足：

```text
N09证据充分
N11 decision=PASS
N11准确度 >= 4
N11覆盖率 >= 0.8
N11.5未ABANDON
N13最终候选qualified=true
action_affirmed=true
critical_failures为空
N16 NOT_DUPLICATE
内容安全PASS
```

最终候选阈值：

| 维度 | 最低分 |
|---|---:|
| 通顺度 | 4 |
| 原梗辨识度 | 4 |
| agu/凿自然度 | 4 |
| 好笑程度 | 3 |
| 节奏保留 | 3 |
| 改写合理性 | 4 |
| 六维平均分 | 4.0 |

任一硬条件失败即不自动入库。理由由代码根据失败规则生成，不让LLM自由编写准入逻辑。

内容安全结果：`PASS/REJECT/UNCERTAIN`。只有 PASS 可以自动入库。

自动入库在N17立即发生，人工评价仍然必须完成。N18可以明确维持或推翻；推翻必须填写原因，状态历史不得删除。

## 12. StrategyPatch 实现

### 12.1 格式

```json
{
  "feedback_summary": "...",
  "affected_nodes": ["N12", "N13"],
  "keep_rules": [],
  "changes": [
    {
      "node_key": "N12",
      "field_path": "/generation_preferences/tail_length",
      "operation": "SET",
      "old_value": {"min": 10, "max": 40},
      "new_value": {"min": 6, "max": 14},
      "feedback_evidence": [
        {
          "evaluation_path": "/candidates/C2/modification_advice",
          "quote": "后续描述长度应该和原文差不多"
        }
      ],
      "expected_effect": "减少冗长描述"
    }
  ],
  "next_round_hypotheses": []
}
```

只允许 `SET/APPEND_UNIQUE/REMOVE_VALUE`。

### 12.2 白名单

允许修改 N02、N03、N05、N07、N09、N10、N11、N11.5、N12、N13、N14、N15 的可变策略字段。

禁止修改：

- 状态图；
- Provider、模型、Base URL和Key；
- 数据库和API配置；
- 人工评价必做规则；
- agu/凿核心语义；
- 来源真实性；
- 查重范围；
- 内容安全；
- 循环和调用预算上限。

### 12.3 应用过程

```text
检查node_key和field_path
→ 检查评价引用真实存在
→ old_value与当前策略比较
→ 在副本上应用
→ StrategyModel校验
→ 不可变规则对比
→ 生成人可读diff
→ N20事务中创建版本并切换active指针
```

每个策略数组最多20项，单条最多500字符，APPEND_UNIQUE自动去重。

### 12.4 归因规则

- 人工只改选候选：默认只修改N14；
- 人工修改模板：可修改N10和N11，但需分别引用反馈；
- 动宾语义错误：优先N11.5、N12、N13；
- 搜索结果问题：N03、N05、N07、N09；
- 无相关评分或意见：不得修改对应节点。

## 13. 数据库字段设计

### 13.1 运行记录库

#### `run_records`

```text
id CHAR(36) PK
mode VARCHAR(32) NOT NULL
status VARCHAR(32) NOT NULL
seed_text TEXT NULL
admission_mode VARCHAR(32) NOT NULL
continuous_enabled BOOLEAN NOT NULL
initial_strategy_version_id CHAR(36) NOT NULL
final_strategy_version_id CHAR(36) NULL
active_branch_id CHAR(36) NOT NULL
selected_original_title TEXT NULL
selected_original_text TEXT NULL
selected_candidate_id VARCHAR(32) NULL
final_agu_text TEXT NULL
admission_decision VARCHAR(32) NULL
formal_meme_id CHAR(36) NULL
total_llm_input_tokens INTEGER NOT NULL DEFAULT 0
total_llm_output_tokens INTEGER NOT NULL DEFAULT 0
total_llm_cost_usd NUMERIC(12,6) NULL
total_search_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0
started_at DATETIME NOT NULL
ended_at DATETIME NULL
termination_reason TEXT NULL
created_at DATETIME NOT NULL
```

索引：status、mode、started_at、initial_strategy_version_id、admission_decision、selected_original_title。

#### `run_branches`

```text
id CHAR(36) PK
run_id CHAR(36) FK run_records.id
parent_branch_id CHAR(36) NULL
forked_from_execution_id CHAR(36) NULL
fork_reason TEXT NOT NULL
is_final_active BOOLEAN NOT NULL
created_at DATETIME NOT NULL
```

#### `run_node_executions`

```text
id CHAR(36) PK
run_id CHAR(36) FK
branch_id CHAR(36) FK
node_key VARCHAR(64) NOT NULL
attempt_no INTEGER NOT NULL
origin VARCHAR(32) NOT NULL       # AGENT/HUMAN_CORRECTION
status VARCHAR(32) NOT NULL
input_json JSON NOT NULL
output_json JSON NULL
human_summary TEXT NULL
next_state VARCHAR(64) NULL
prompt_version VARCHAR(64) NULL
strategy_version_id CHAR(36) NOT NULL
provider VARCHAR(32) NULL
model VARCHAR(128) NULL
parameter_snapshot_json JSON NULL
token_usage_json JSON NULL
cost_usd NUMERIC(12,6) NULL
started_at DATETIME NOT NULL
ended_at DATETIME NULL
error_code VARCHAR(64) NULL
error_message TEXT NULL
```

唯一约束：`(run_id, branch_id, node_key, attempt_no)`。

#### `run_source_evidence`

```text
id CHAR(36) PK
run_id CHAR(36) FK
branch_id CHAR(36) FK
node_execution_id CHAR(36) FK
source_id VARCHAR(32) NOT NULL
provider VARCHAR(32) NOT NULL
provider_result_id TEXT NULL
title TEXT NOT NULL
url TEXT NOT NULL
canonical_url TEXT NOT NULL
published_date DATETIME NULL
text TEXT NULL
evidence_type VARCHAR(32) NOT NULL
content_status VARCHAR(32) NOT NULL
rejection_reason TEXT NULL
retrieved_at DATETIME NOT NULL
```

唯一约束：`(run_id, branch_id, source_id)`。

`source_id` 在一个分支内使用单调递增计数器分配，节点重试时不重置，避免同一分支出现两个 `O001` 或 `V001`。

#### `run_search_batches`

每次 Exa API 调用保存一条，费用不能重复摊到每个搜索结果：

```text
id CHAR(36) PK
run_id CHAR(36) FK
branch_id CHAR(36) FK
node_execution_id CHAR(36) FK
query_id VARCHAR(32) NOT NULL
query_text TEXT NOT NULL
search_type VARCHAR(16) NOT NULL
purpose TEXT NOT NULL
result_limit INTEGER NOT NULL
provider_request_id TEXT NULL
request_json JSON NOT NULL          # 已脱敏，不含x-api-key
status VARCHAR(32) NOT NULL
http_status INTEGER NULL
raw_result_count INTEGER NOT NULL DEFAULT 0
latency_ms INTEGER NULL
cost_usd NUMERIC(12,6) NULL
error_code VARCHAR(64) NULL
error_message TEXT NULL
created_at DATETIME NOT NULL
```

#### `run_evidence_query_hits`

```text
id CHAR(36) PK
evidence_id CHAR(36) FK
search_batch_id CHAR(36) FK
query_id VARCHAR(32) NOT NULL
query_text TEXT NOT NULL
search_type VARCHAR(16) NOT NULL
purpose TEXT NOT NULL
rank INTEGER NULL
```

#### `run_human_evaluations`

```text
id CHAR(36) PK
run_id CHAR(36) FK UNIQUE
branch_id CHAR(36) FK
processing_chain_scores_json JSON NOT NULL
candidate_set_scores_json JSON NOT NULL
candidate_scores_json JSON NOT NULL
final_result_scores_json JSON NOT NULL
main_problem_nodes_json JSON NOT NULL
admission_decision VARCHAR(32) NULL
admission_override VARCHAR(32) NULL
admission_reason TEXT NULL
overall_comment TEXT NULL
submitted_at DATETIME NOT NULL
```

四个评分JSON列必须保存第14.4节 `HumanEvaluationRequest` 中对应对象的原始结构，不允许Repository自行改名、压平或遗漏字段。候选ID键集合必须与本轮N12有效候选严格相等。

#### `run_strategy_versions`

```text
id CHAR(36) PK
version_number INTEGER NOT NULL
parent_version_id CHAR(36) NULL
strategy_json JSON NOT NULL
source_run_id CHAR(36) NULL
source_evaluation_id CHAR(36) NULL
change_summary TEXT NOT NULL
created_at DATETIME NOT NULL
```

#### `run_strategy_patches`

```text
id CHAR(36) PK
source_run_id CHAR(36) FK
evaluation_id CHAR(36) FK
before_version_id CHAR(36) NOT NULL
after_version_id CHAR(36) NOT NULL
feedback_summary TEXT NOT NULL
affected_nodes_json JSON NOT NULL
patch_operations_json JSON NOT NULL
score_gaps_json JSON NOT NULL
next_round_hypotheses_json JSON NOT NULL
created_at DATETIME NOT NULL
```

#### `run_strategy_state`

单行表：

```text
id INTEGER PK CHECK(id=1)
active_strategy_version_id CHAR(36) NOT NULL
updated_at DATETIME NOT NULL
```

#### `run_model_parameter_profiles`

```text
profile_name VARCHAR(32) PK
parameters_json JSON NOT NULL
updated_at DATETIME NOT NULL
```

#### `run_audit_actions`

```text
id CHAR(36) PK
run_id CHAR(36) NULL
actor VARCHAR(32) NOT NULL DEFAULT 'local_user'
action_type VARCHAR(64) NOT NULL
target_type VARCHAR(64) NULL
target_id CHAR(36) NULL
detail_json JSON NOT NULL
created_at DATETIME NOT NULL
```

### 13.2 正式梗库

#### `meme_records`

```text
id CHAR(36) PK
title TEXT NOT NULL
normalized_title VARCHAR(255) NOT NULL UNIQUE
status VARCHAR(32) NOT NULL       # ACTIVE/UNPUBLISHED
original_meme_text TEXT NOT NULL
canonical_template_text TEXT NOT NULL
template_segments_json JSON NOT NULL
adaptation_route VARCHAR(64) NOT NULL
preserved_features_json JSON NOT NULL
rewritten_features_json JSON NOT NULL
final_agu_text TEXT NOT NULL
source_run_id CHAR(36) NOT NULL   # 软关联，N17时运行尚未归档
source_branch_id CHAR(36) NOT NULL
initial_admission_mode VARCHAR(32) NOT NULL
initial_admission_decision VARCHAR(32) NOT NULL
created_at DATETIME NOT NULL
updated_at DATETIME NOT NULL
```

`normalized_title` 在下架后也保持唯一，避免恢复冲突。

额外约束：`UNIQUE(source_run_id)`。一轮任务最多对应一个正式梗逻辑记录。若人工在 N18 修正上游产物并形成新分支，同一轮后续 N17 更新这一逻辑记录，而不是创建第二个正式梗。

#### `meme_sources`

保存独立不可变快照，不依赖运行库已经归档：

```text
id CHAR(36) PK
meme_id CHAR(36) FK
source_role VARCHAR(32) NOT NULL  # ORIGINAL/VARIANT/SUPPORTING
source_id VARCHAR(32) NOT NULL
title TEXT NOT NULL
url TEXT NOT NULL
evidence_quote TEXT NOT NULL
published_date DATETIME NULL
run_source_evidence_id CHAR(36) NULL
sort_order INTEGER NOT NULL
```

#### `meme_admission_history`

```text
id CHAR(36) PK
meme_id CHAR(36) FK
decision_source VARCHAR(32) NOT NULL  # AUTO/HUMAN/HUMAN_OVERRIDE
decision VARCHAR(32) NOT NULL
reason_json JSON NOT NULL
created_at DATETIME NOT NULL
```

#### `meme_status_history`

```text
id CHAR(36) PK
meme_id CHAR(36) FK
from_status VARCHAR(32) NOT NULL
to_status VARCHAR(32) NOT NULL
reason TEXT NOT NULL
created_at DATETIME NOT NULL
```

#### `meme_revision_history`

自动准入后仍可能发生人工修正。更新同一轮的正式梗前，必须保存完整旧版本：

```text
id CHAR(36) PK
meme_id CHAR(36) FK
source_branch_id CHAR(36) NOT NULL
revision_reason VARCHAR(64) NOT NULL
record_snapshot_json JSON NOT NULL
sources_snapshot_json JSON NOT NULL
created_at DATETIME NOT NULL
```

分支规则：

1. 已经过 N17 的分支被上游重试或修正取代时，将本轮正式梗设为 `UNPUBLISHED`，原因 `BRANCH_SUPERSEDED`；
2. 新分支执行 N16 查重时，忽略 `source_run_id` 等于当前 run 的记录，避免与自身旧版本重复；
3. 新分支到达 N17 前先写 `meme_revision_history`；
4. 新分支自动准入时更新同一 `meme_records` 并重新激活；
5. 新分支自动不准入时保持 `UNPUBLISHED`；
6. 任何旧内容和旧来源均可从 revision history 查看。

### 13.3 持久化时点

- 活动任务节点数据主要保存在RunContext；
- N17自动入库立即写 `meme_*`，来源使用快照；
- N18推翻自动结论时立即更新 `meme_*`；
- N17之后发生上游分支修正时，先保存正式梗revision并下架旧分支成果；
- N19只在内存生成待应用策略；
- N20将运行记录、新策略和关联补齐放在同一事务；
- 明确失败或人工终止时，ArchiveService归档已有分支；
- 应用崩溃导致未归档运行数据丢失，不尝试恢复。

## 14. REST API

统一前缀：`/api/v1`。

### 14.1 系统

```text
GET   /health
GET   /system/config
GET   /system/runtime-parameters
PATCH /system/runtime-parameters
POST  /system/connection-tests/llm
POST  /system/connection-tests/search
```

配置响应只返回 `api_key_configured: true/false`。

### 14.2 任务

```text
POST /runs
GET  /runs/current
GET  /runs/{run_id}
GET  /runs/{run_id}/branches
GET  /runs/{run_id}/nodes
GET  /runs/{run_id}/nodes/{execution_id}
POST /runs/{run_id}/commands
GET  /runs/{run_id}/evaluation-form
POST /runs/{run_id}/evaluation
GET  /runs/{run_id}/events
```

启动人工种子：

```json
{
  "mode": "MANUAL_SEED",
  "seed_text": "你说的对，但是",
  "admission_mode": "HUMAN",
  "continuous_enabled": false
}
```

启动自主发现：

```json
{
  "mode": "AUTO_DISCOVERY",
  "admission_mode": "AUTO",
  "continuous_enabled": true
}
```

同一时间已有活动任务时返回409。持续执行只允许自主发现模式。

### 14.3 命令

```json
{
  "command_id": "UUID",
  "type": "PAUSE",
  "expected_run_version": 12,
  "payload": {}
}
```

支持：

```text
PAUSE
RESUME
TERMINATE
RETRY_NODE
CORRECT_NODE_OUTPUT
SWITCH_ACTIVE_BRANCH
SET_CONTINUOUS_EXECUTION
```

所有命令进入单一CommandQueue。`command_id`幂等；版本不一致返回409。

暂停为协作式暂停：当前外部请求结束后、下一节点开始前进入PAUSED。终止同样在当前请求结束后归档，不强杀线程。

人工修正输出必须经过对应Pydantic、引用和确定性规则校验；通过后创建新分支和 `origin=HUMAN_CORRECTION` 执行记录，不覆盖原结果。

### 14.4 历史和正式梗

```text
GET  /runs
GET  /memes
GET  /memes/{meme_id}
POST /memes/{meme_id}/unpublish
POST /memes/{meme_id}/restore
GET  /strategies
GET  /strategies/{strategy_id}
POST /strategies/{strategy_id}/activate
```

策略恢复只允许在没有活动任务时执行。活动任务已经持有不可变策略快照，运行中切换全局策略既不会改变当前轮，也可能与N19新版本提交产生歧义，因此API在存在活动任务时返回409。持续执行场景下，用户应先关闭持续执行，等待本轮完成后再恢复策略。

评价提交规则：

- 只能在 `WAITING_HUMAN_EVALUATION` 状态提交；
- 同一有效分支只能成功提交一次；
- 不支持直接覆盖已提交评价；
- 如需修改评价对象，先通过人工修正创建新分支，旧评价草稿作废；
- 评价结构通过校验后才能把 `EVALUATION_SUBMITTED` 命令放入队列。

评价请求固定为以下结构；所有评分都是1～5的整数：

```json
{
  "expected_run_version": 38,
  "branch_id": "UUID",
  "processing_chain": {
    "original_meme_popularity": 5,
    "original_meme_applicability": 5,
    "search_result_relevance": 5,
    "variant_evidence_quality": 5,
    "template_extraction_accuracy": 4,
    "overall_chain_reasonableness": 4,
    "comment": ""
  },
  "candidate_set": {
    "effective_difference": 5,
    "natural_rewrite_coverage": 3,
    "overall_selectable_quality": 2,
    "comment": ""
  },
  "candidates": {
    "C1": {
      "fluency": 4,
      "original_meme_recognition": 3,
      "agu_zao_naturalness": 2,
      "humor": 1,
      "template_logic": 3,
      "usability": "UNUSABLE",
      "modification_advice": "需要重新处理凿与agu的动宾关系"
    },
    "C2": {
      "fluency": 4,
      "original_meme_recognition": 4,
      "agu_zao_naturalness": 3,
      "humor": 3,
      "template_logic": 4,
      "usability": "USABLE_AFTER_EDIT",
      "modification_advice": "缩短尾句"
    },
    "C3": {
      "fluency": 3,
      "original_meme_recognition": 3,
      "agu_zao_naturalness": 3,
      "humor": 2,
      "template_logic": 3,
      "usability": "USABLE_AFTER_EDIT",
      "modification_advice": ""
    },
    "C4": {
      "fluency": 3,
      "original_meme_recognition": 2,
      "agu_zao_naturalness": 2,
      "humor": 2,
      "template_logic": 2,
      "usability": "UNUSABLE",
      "modification_advice": ""
    },
    "C5": {
      "fluency": 4,
      "original_meme_recognition": 4,
      "agu_zao_naturalness": 4,
      "humor": 3,
      "template_logic": 4,
      "usability": "USABLE",
      "modification_advice": ""
    }
  },
  "final_result": {
    "is_best_candidate": true,
    "better_candidate_id": null,
    "fluency": 4,
    "original_meme_recognition": 4,
    "agu_zao_fit": 2,
    "humor": 3,
    "overall_satisfaction": 4,
    "comment": ""
  },
  "main_problem_nodes": ["N12", "N13"],
  "admission": {
    "decision": "ADMIT",
    "override": null,
    "reason": ""
  },
  "overall_comment": ""
}
```

枚举和交叉校验：

- `usability`：`USABLE/USABLE_AFTER_EDIT/UNUSABLE`；
- `main_problem_nodes`：N02～N17中允许人工评价的问题节点，或单独的 `NO_OBVIOUS_PROBLEM`；
- 人工准入时 `admission.decision` 必须是 `ADMIT/NOT_ADMIT`，`override=null`；
- 自动准入时 `decision=null`，`override` 必须是 `KEEP/OVERRIDE_TO_ADMIT/OVERRIDE_TO_NOT_ADMIT` 中与N17原结论相容的一项；
- `candidates` 必须包含且只包含本轮5个候选ID；
- `is_best_candidate=false` 时，必须选择一个不同于N14结果且存在的 `better_candidate_id`，或在 `final_result.comment` 说明全部不合适；
- 任一评分为1、推翻自动结论、或必填的替代候选缺失时，对应意见/原因不得为空；
- 内容安全不是PASS时，`ADMIT/OVERRIDE_TO_ADMIT` 返回422；
- `expected_run_version` 和 `branch_id` 必须同时匹配当前有效评价对象，否则返回409。

### 14.5 错误响应

```json
{
  "error": {
    "code": "RUN_VERSION_CONFLICT",
    "message": "任务状态已经变化，请刷新后重试",
    "details": {},
    "request_id": "UUID"
  }
}
```

| HTTP | 用途 |
|---:|---|
| 400 | 请求无法解析 |
| 404 | 资源不存在 |
| 409 | 状态或版本冲突 |
| 422 | 业务校验失败 |
| 429 | 本地频率限制 |
| 502 | 外部响应无法解析 |
| 503 | 外部服务不可用 |

## 15. SSE 事件

```http
GET /api/v1/runs/{run_id}/events
Accept: text/event-stream
```

```text
id: 109
event: node.completed
data: {"event_id":"...","sequence":109,"run_id":"...","run_version":17,"branch_id":"...","occurred_at":"...","type":"node.completed","state":"EVALUATE_VARIANT_EVIDENCE","human_message":"变式搜索完成","payload":{}}
```

事件：

```text
run.started
state.changed
node.started
node.progress
node.completed
node.failed
human.required
command.accepted
command.completed
command.rejected
run.pausing
run.paused
run.resumed
strategy.updated
admission.decided
run.completed
next_run.started
stream.reset
heartbeat
```

- RunContext保留最近1000条；
- 浏览器原生EventSource按事件ID自动重连；
- 缺失事件超出缓冲时发送 `stream.reset`，前端重新GET任务快照；
- 每15秒心跳；
- 不把完整原始LLM响应放入SSE。

## 16. 前端实现

### 16.1 页面

```text
/                         工作台
/runs/:runId              任务详情和节点时间线
/runs/:runId/evaluation   人工评价
/runs                     运行历史库
/memes                    正式梗库
/memes/:memeId            正式梗详情
/strategies               策略版本与diff
/settings                 脱敏配置、参数和连接测试
```

### 16.2 工作台

- 展示是否存在活动任务；
- 创建人工种子或自主发现任务；
- 设置准入方式和持续执行；
- 展示当前节点、状态、策略版本、搜索/LLM费用；
- 提供暂停、继续、终止入口；
- 持续执行开关在评价提交前始终可修改。

### 16.3 节点时间线

每个节点卡片展示：

```text
目标
输入摘要
策略版本
结构化输出
人可读结论
来源证据
确定性校验
下一状态
耗时、Token、费用
分支和尝试次数
```

来源原文、Agent归纳和生成文案使用不同标签及颜色。废弃分支可查看但明确标识。

### 16.4 人工修正

- 仅在暂停、等待或异常状态启用；
- JSON TextArea编辑结构化输出；
- 提交前做JSON语法检查，最终以后端校验为准；
- 显示创建新分支及需要重跑的后续节点；
- 评价页中的“修改模板/候选/最终结果”复用同一人工修正命令：提交后离开旧评价表，等待新分支重跑并重新进入N18；
- 如果旧分支已经自动入库，界面提示旧成果会以 `BRANCH_SUPERSEDED` 下架，历史版本仍保留；
- 不提供数据库记录直接编辑。

### 16.5 人工评价

- 按处理链、候选集、单候选、最终结果四段展示；
- 候选默认按Agent排名，但不默认勾选第一名；
- 1分、否定最佳但未给替代、推翻自动准入等情况要求意见；
- 自动准入展示原结论并要求明确“维持/推翻”；
- 所有必填评分完成后才能提交；
- 提交后展示N19策略diff和下一轮重点。

## 17. 异常处理与安全

### 17.1 异常分类

| 分类 | 示例 | 处理 |
|---|---|---|
| CONFIG_ERROR | Key缺失、Provider非法 | 启动失败或连接测试失败 |
| EXTERNAL_AUTH_ERROR | Exa 401、LLM 401 | 不重试，等待人工 |
| EXTERNAL_QUOTA_ERROR | Exa 402/429、模型额度 | 按类型退避或等待人工 |
| EXTERNAL_TIMEOUT | 网络超时 | 最多2次重试 |
| OUTPUT_PARSE_ERROR | 非JSON | 一次结构修复 |
| OUTPUT_SCHEMA_ERROR | 字段错误 | 一次结构修复 |
| NODE_RULE_VIOLATION | source_id不存在 | 一次业务重生成 |
| BUSINESS_INSUFFICIENT | 变式不足 | 状态机回退 |
| ARCHIVE_ERROR | SQLite写失败 | 整体事务回滚，禁止下一轮 |

### 17.2 秘密保护

- Pydantic Settings中SecretStr保存Key；
- 日志过滤 `authorization/x-api-key/api-key/token`；
- Provider异常先转成内部错误再返回API；
- `.env`加入 `.gitignore`；
- 前端永远不接收Key；
- 测试断言日志和API响应中不存在测试Key字面量。

### 17.3 外部内容

网页内容属于不可信输入：

- 作为JSON数据放入用户消息，不能拼入系统提示词；
- 公共系统提示词明确忽略网页中的命令和提示注入；
- 网页不能修改状态、策略和工具参数；
- 引用必须回指source_id和真实子串；
- 展示时进行HTML转义，不使用 `dangerouslySetInnerHTML` 渲染网页正文。

### 17.4 日志

使用结构化JSON日志，字段：

```text
request_id
run_id
branch_id
node_key
execution_id
provider_request_id
duration_ms
status
error_code
```

不记录完整Prompt和Key。开发调试需要查看Prompt时，由节点详情读取已脱敏输入和prompt_version，不直接打印生产请求。

## 18. 测试方案

### 18.1 测试原则

- 默认测试不得访问真实Exa或LLM，不产生费用；
- 测试专用 `FakeLLMProvider/FakeSearchProvider` 只存在于测试依赖注入，不暴露为生产配置；
- Provider合同测试使用respx模拟HTTP；
- 真实冒烟测试必须显式设置环境开关；
- 每个测试独立创建临时SQLite，不依赖其他用例执行顺序；
- 使用可复现的“你说的对，但是”和“大胆妖孽”证据夹具。

需求—用例追踪：

| 核心要求 | 主要用例 |
|---|---|
| 从源码启动、SQLite迁移、无Redis依赖 | DB-01、第19节启动命令 |
| 人工种子与自主发现 | WF-01、WF-02、Playwright完整链路 |
| N05以后只处理一个原始梗 | N05-01、N06-01、N08-01 |
| 正式标题查重及疑似详情二阶段判断 | N06-01、N06-02、DB-13 |
| N11.5适配路由与“凿作用于agu”语义 | N11.5-01、N11.5-02、N12-01、N13-01 |
| 五候选、自评分、只选合格项 | N12-02、N13-01、N14-01、N14-02 |
| 每轮必须等待结构化人工评价 | N18-01～N18-06、WF-20、WF-21 |
| 人工/自动准入及人工推翻 | N17-01～N17-03、N18-04～N18-06、DB-04、DB-05 |
| 评价形成下一轮策略 | N19-01～N20-02 |
| 暂停、终止、重试、人工修正和分支 | WF-11～WF-19、WF-22 |
| 运行记录库与正式梗库分开 | DB-04～DB-07、API-03、API-04 |
| 持续执行开关 | WF-20、WF-21、UI-07 |

### 18.2 配置与Provider用例

| ID | 场景 | 预期 |
|---|---|---|
| CFG-01 | 缺少LLM_API_KEY启动 | 明确报缺失字段，不打印其他配置 |
| CFG-02 | 非法LLM_PROVIDER | 启动校验失败 |
| CFG-03 | 前端读取配置 | 只返回api_key_configured |
| LLM-01 | OpenAI Responses正常JSON Schema | 解析为Pydantic模型 |
| LLM-02 | OpenAI返回非JSON | 执行一次结构修复 |
| LLM-03 | DeepSeek json_object正常 | 本地Schema通过 |
| LLM-04 | DeepSeek字段缺失 | 修复后通过或节点失败 |
| LLM-05 | 模型返回不存在source_id | 业务重生成，不能提交产物 |
| LLM-06 | 三次调用仍失败 | WAITING_HUMAN_INTERVENTION |
| LLM-07 | 参数运行时修改 | 当前节点使用旧快照，下一节点使用新值 |
| LLM-08 | 连接测试 | 返回模型、协议、延迟和结构化校验，不返回Key |
| EXA-01 | 正常中文搜索 | 解析results、requestId和costDollars |
| EXA-02 | 401 | 不重试，返回EXTERNAL_AUTH_ERROR |
| EXA-03 | 402 | 不重试，返回EXTERNAL_QUOTA_ERROR |
| EXA-04 | 429后成功 | 按退避重试并成功 |
| EXA-05 | 单查询失败、其余成功 | 节点继续并记录失败批次 |
| EXA-06 | URL跟踪参数 | canonical_url去除跟踪参数 |
| EXA-07 | 空内容ID URL | 标记INVALID_URL |
| EXA-08 | 404正文 | 标记NOT_FOUND_PAGE |
| EXA-09 | 相同URL多查询命中 | 一份正文、多条query hit |
| EXA-10 | 变式结果超过30 | 平衡裁剪且保留auto查询结果 |

### 18.3 状态机与人工干预用例

| ID | 场景 | 预期 |
|---|---|---|
| WF-01 | 人工种子启动 | START→N01 |
| WF-02 | 自主发现启动 | START→N02 |
| WF-03 | 同时启动第二任务 | HTTP 409 |
| WF-04 | N04无结果且有预算 | 回N03 |
| WF-05 | 自主方向耗尽 | WAITING_HUMAN_INTERVENTION |
| WF-06 | N09证据不足且有预算 | 回N07 |
| WF-07 | N11 REEXTRACT | 回N10并增加计数 |
| WF-08 | N11.5 ABANDON自动模式 | 回N02 |
| WF-09 | N13全不合格 | 回N12，最多三批 |
| WF-10 | N16标题重复 | 只回N15，不修改候选 |
| WF-11 | PAUSE发生在LLM调用中 | 当前调用完成后暂停，不进入下一节点 |
| WF-12 | RESUME | 从suspended_state继续 |
| WF-13 | TERMINATE | 不评价、不更新策略、不入库下一成果 |
| WF-14 | 重复command_id | 只执行一次 |
| WF-15 | expected_run_version过期 | HTTP 409 |
| WF-16 | RETRY_NODE | 新分支复用原输入，旧分支保留 |
| WF-17 | CORRECT_NODE_OUTPUT合法 | 新建HUMAN_CORRECTION执行记录 |
| WF-18 | 修正内容引用虚假source_id | HTTP 422，不建分支 |
| WF-19 | 切换分支 | 状态由分支尾部计算，客户端不能指定 |
| WF-20 | continuous=false完成 | 回WAITING_START |
| WF-21 | continuous=true完成 | 仅在N20事务成功后启动下一轮 |
| WF-22 | N17后修正N12 | 旧正式成果下架、保存revision、新分支重跑 |
| WF-23 | 活动任务期间恢复旧策略 | HTTP 409 |

### 18.4 节点合同用例

| ID | 节点 | 场景 | 预期 |
|---|---|---|---|
| N01-01 | N01 | 空种子 | API 422 |
| N01-02 | N01 | 正常文案线索 | 仅输出理解，不含虚构来源 |
| N02-01 | N02 | 方向与正式标题相同 | 业务重生成 |
| N02-02 | N02 | 重复本轮方向 | 拒绝 |
| N03-01 | N03 | 包含Google运算符 | 拒绝并重生成 |
| N03-02 | N03 | 缺少auto查询 | 拒绝 |
| N04-01 | N04 | 5条正文搜索结果 | 保存真实证据和费用 |
| N05-01 | N05 | 选择两条原始梗 | Schema/业务校验失败 |
| N05-02 | N05 | quote不是原文子串 | 拒绝 |
| N06-01 | N06 | normalized_title完全相同 | 代码直接DUPLICATE |
| N06-02 | N06 | 疑似ID不存在 | 拒绝请求详情 |
| N07-01 | N07 | 查询重复上一轮 | 拒绝 |
| N08-01 | N08 | 一页包含多个变式 | 保存一次页面，允许N09多引用 |
| N09-01 | N09 | 3变式、2URL、共享锚点 | 代码判SUFFICIENT |
| N09-02 | N09 | LLM自报充分但只有2条 | 代码判INSUFFICIENT |
| N09-03 | N09 | 跨站相同文案 | 只计1条变式 |
| N10-01 | N10 | 模板提前含agu | 拒绝 |
| N10-02 | N10 | 引用不存在证据 | 拒绝 |
| N11-01 | N11 | 模型自报100%但漏案例 | 代码重新计算并拒绝 |
| N11-02 | N11 | 原句不匹配 | 不得PASS |
| N11.5-01 | N11.5 | direct=3、structure=4 | 只能STRUCTURE路由 |
| N11.5-02 | N11.5 | 两项都低 | ABANDON |
| N12-01 | N12 | “阿古”替代agu | 确定性校验失败 |
| N12-02 | N12 | 少于5条 | Schema失败 |
| N12-03 | N12 | route不一致 | 拒绝 |
| N13-01 | N13 | action_affirmed=false但均分高 | 必须不合格 |
| N13-02 | N13 | 平均分计算错误 | 代码覆盖模型值 |
| N14-01 | N14 | 选择不合格候选 | 拒绝 |
| N14-02 | N14 | 输出新文案 | 拒绝 |
| N15-01 | N15 | 改写最终候选 | 拒绝 |
| N16-01 | N16 | 标题重复 | 回N15仅重写标题 |
| N17-01 | N17 | 所有自动阈值满足 | 立即ADMIT并写证据快照 |
| N17-02 | N17 | 自然度3 | 自动NOT_ADMIT |
| N17-03 | N17 | 内容安全UNCERTAIN | 自动NOT_ADMIT |
| N18-01 | N18 | 缺少必填评分 | HTTP 422 |
| N18-02 | N18 | 1分无意见 | HTTP 422 |
| N18-03 | N18 | 推翻自动准入无理由 | HTTP 422 |
| N18-04 | N18 | 人工准入选择ADMIT且安全PASS | 创建ACTIVE正式梗并写历史 |
| N18-05 | N18 | 推翻自动NOT_ADMIT为ADMIT且安全PASS | 创建ACTIVE正式梗并保留自动结论 |
| N18-06 | N18 | 内容安全UNCERTAIN但人工选择ADMIT | HTTP 422，不写正式库 |
| N19-01 | N19 | 补丁修改N12允许字段 | 产生新版本 |
| N19-02 | N19 | 补丁修改状态图 | 拒绝 |
| N19-03 | N19 | 反馈引用不存在 | 拒绝 |
| N19-04 | N19 | 只改选候选却修改N12 | 归因校验拒绝 |
| N20-01 | N20 | 全部写入成功 | 激活策略并完成 |
| N20-02 | N20 | 中途数据库错误 | 全事务回滚，不启下一轮 |

### 18.5 数据库用例

| ID | 场景 | 预期 |
|---|---|---|
| DB-01 | 空库执行Alembic | 创建全部表和初始策略 |
| DB-02 | 重复normalized_title | 唯一约束失败 |
| DB-03 | 下架后插入同标题 | 仍失败 |
| DB-04 | N17自动入库但运行未归档 | 正式梗可独立展示来源快照 |
| DB-05 | N18推翻入库 | status=UNPUBLISHED并写两类历史 |
| DB-06 | 终止任务归档 | 保存已完成分支，不产生策略版本 |
| DB-07 | 人工修正 | 原执行和新分支都存在 |
| DB-08 | 策略恢复 | active指针切换，历史版本不删除 |
| DB-09 | 外键开启 | 无效关联写入失败 |
| DB-10 | JSON字段往返 | Pydantic结构不丢失 |
| DB-11 | 一次Exa调用返回10条 | 只记录一笔search batch费用，不按结果重复累计 |
| DB-12 | 同一run新分支再次准入 | 更新同一meme记录并保存旧revision |
| DB-13 | 新分支N16查重 | 忽略当前run旧正式记录，不忽略其他run |

### 18.6 API、SSE和前端用例

| ID | 场景 | 预期 |
|---|---|---|
| API-01 | 创建人工任务 | 返回run_id和初始快照 |
| API-02 | 人工模式continuous=true | HTTP 422 |
| API-03 | 活动任务GET | 从内存返回 |
| API-04 | 历史任务GET | 从SQLite返回同形结构 |
| API-05 | 非法人工修正 | 标准422错误体 |
| SSE-01 | 节点开始到完成 | sequence严格递增 |
| SSE-02 | 断线重连且事件仍在缓冲 | 从Last-Event-ID补发 |
| SSE-03 | 游标过旧 | stream.reset后前端刷新快照 |
| SSE-04 | 15秒无事件 | 收到heartbeat |
| UI-01 | 工作台启动任务 | 显示当前节点并建立SSE |
| UI-02 | 节点卡片 | 来源、归纳、生成内容明确区分 |
| UI-03 | 暂停中 | 展示“等待当前节点结束” |
| UI-04 | 分支修正 | 明确提示后续节点将重跑 |
| UI-05 | 评价未完成 | 提交按钮禁用并定位缺失项 |
| UI-06 | 自动准入推翻 | 必须填写原因 |
| UI-07 | 持续执行关闭 | 本轮完成后不创建下一轮 |
| UI-08 | 正式梗下架和恢复 | 列表状态及时更新且历史可查 |

### 18.7 真实冒烟测试

真实调用默认跳过：

```bash
RUN_LIVE_EXA_TESTS=1 uv run pytest tests/live/test_exa_live.py -q
RUN_LIVE_LLM_TESTS=1 uv run pytest tests/live/test_llm_live.py -q
```

真实测试要求：

- 不打印Key；
- Exa只请求1～3个结果；
- 输出实际费用和request ID；
- LLM只执行最小结构化连接测试；
- CI永远不启用真实测试。

## 19. 本地自测命令与通过标准

后端：

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run ruff check app tests
uv run mypy app
uv run pytest -q --cov=app --cov-report=term-missing --cov-fail-under=85
```

前端：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
pnpm exec playwright test
```

完整通过标准：

1. 所有命令退出码为0；
2. 后端覆盖率不低于85%；
3. Alembic能在全新临时目录创建数据库；
4. Playwright使用Fake Provider完整走通人工种子轮和自主发现轮；
5. 人工评价未提交前不能进入N19；
6. 自动持续执行只在N20事务成功后启动下一轮；
7. 测试日志、API响应和前端产物不包含任何测试Key；
8. 默认测试不产生外部请求和费用。

## 20. 推荐开发顺序

1. 初始化前后端、配置和健康检查；
2. 建立Pydantic节点契约、NodeKey和TransitionTable；
3. 实现Fake Provider和WorkflowEngine基础循环；
4. 先完成一条全部Fake的N01～N20 happy path；
5. 实现分支、暂停、重试、修正和SSE；
6. 实现SQLite模型、Alembic和N20归档；
7. 接入Exa并完成N04/N08；
8. 接入OpenAI Responses和DeepSeek Chat适配器；
9. 实现N17自动准入和N19策略补丁；
10. 实现工作台、任务详情和评价页；
11. 实现历史库、正式梗库、策略页和设置页；
12. 完成单元、集成和Playwright测试；
13. 最后显式执行一次真实Exa和当前选定LLM的最小冒烟测试。

## 21. MVP 完成定义

满足以下条件才可认为MVP开发完成：

- 能从源码独立启动前后端；
- SQLite迁移和初始策略自动建立；
- OpenAI和DeepSeek配置模板均存在，至少当前配置的一个Provider真实连接测试通过；
- Exa真实中文最小查询通过；
- 人工种子和自主发现均能完整走到结构化评价；
- N11.5路由、N12硬校验和N13独立评分实际生效；
- 所有正常轮次必须评价后才能完成；
- 下一轮使用评价形成的新策略版本；
- 运行记录库和正式梗库分离；
- 自动准入可以被人工推翻并保留历史；
- 暂停、终止、节点重试和人工修正均创建可审计记录；
- 崩溃后不恢复活动任务，系统行为与MVP边界一致；
- 第19节全部本地自测命令通过。

## 22. 已知限制

- Exa语义搜索可能召回与目标模板无关的其他文案公式，必须依赖N09过滤；
- 单次变式搜索通常不足，需要多查询合并；
- 搜索正文可能是404、导航页、AI批量内容或未来日期，来源质量只能作为证据评分的一部分；
- LLM结构化输出在不同供应商上稳定性不同，本地Schema和确定性校验不可省略；
- 自动准入基于Agent自评分，人工评价仍是必要纠偏机制；
- 活动任务崩溃后丢失是MVP接受的风险；
- SQLite适合单任务本地运行，迁移MySQL前仍需执行目标数据库专项测试。
