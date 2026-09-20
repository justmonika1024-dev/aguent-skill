# 凿agugent Skill 服务

这是一个本地轻量服务，通过 Codex CLI 调用项目内的 `zao-agugent-supervisor` Skill，支持人工种子和自主搜索两种模式。服务只允许同时运行一个任务；任务成功到达人工评价阶段后，正式梗及完整运行记录会写入本地 SQLite。

## 目录

```text
.
├── skill/          # zao-agugent-supervisor Skill
├── backend/        # FastAPI、SQLite、Codex CLI Runner 和测试
├── start.sh        # 后端启动入口
├── .env            # 本机配置，不提交 Git
├── .env.example    # 配置示例
└── README.md
```

`backend/data/skill-runner.db` 保存任务、日志、评分和正式梗；`backend/data/runs/{run_id}` 保存每轮 Prompt、机器记录、搜索记录和最终摘要。`backend/data/` 不提交 Git。

## 平台支持

后端使用 FastAPI、SQLite 和跨平台 Python 接口，本身不依赖 macOS；完整任务还依赖 Codex CLI、Node.js、Git 以及有头 Chrome，因此“后端能够启动”不等于“AUTO 搜索链路已经验证”。当前支持状态如下：

| 环境 | 当前状态 | 说明 |
| --- | --- | --- |
| macOS | 已验证 | 已完成 Codex CLI、Playwright、Chrome 和真实 AUTO 全链路测试 |
| Linux 桌面 | 理论兼容，未验证 | 需要可用的 X11/Wayland 图形显示和 Google Chrome |
| Linux 无桌面服务器 | 需要额外配置 | 当前有头 Chrome 不能直接在无 `DISPLAY` 环境启动，可配置 Xvfb 等虚拟显示后再验证 |
| Windows 11 + WSL2/WSLg | 理论兼容，未验证 | 可使用现有 Bash 启动脚本，但 Codex CLI、Node.js、Git 和 Linux 版 Chrome 均须安装在 WSL 内 |
| Windows 原生 PowerShell | 暂未开箱支持 | Codex CLI 官方支持 Windows，但本项目尚未提供 `start.ps1`，也未验证 `codex.cmd`、`npx.cmd` 和离屏 Chrome 行为 |

未经真实全链路测试的平台不视为正式支持。Codex 本身的平台安装与 Windows 沙箱能力参见 [Codex CLI](https://learn.chatgpt.com/docs/codex/cli) 和 [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox)。

## 共同要求

- Python 3.12～3.14 和 [uv](https://docs.astral.sh/uv/)；
- 已安装并登录 `codex` CLI；
- Node.js 与 `npx` 可用；
- Git 可用；
- 已安装 Google Chrome；
- 只启动一个服务进程，不要修改为多 worker。

当前浏览器固定使用有头 Chrome，并尝试把窗口移动到屏幕外。桌面环境中，它仍可能在创建或切换标签页时短暂抢占前台；Linux 服务器需要自行提供图形显示或虚拟显示。这是当前阶段保留的已知限制。

## 配置与启动

### macOS、Linux 桌面和 WSL2

首次使用：

```bash
cp .env.example .env
./start.sh
```

仓库内已经存在 `.env` 时，直接执行：

```bash
./start.sh
```

脚本会从任意当前工作目录定位项目根目录，按照 `backend/uv.lock` 同步依赖，然后以单 worker 启动：

```text
http://127.0.0.1:8100
```

如需临时修改监听地址或端口：

```bash
AGUGENT_HOST=0.0.0.0 AGUGENT_PORT=8200 ./start.sh
```

`start.sh` 使用 Bash，不能直接在 Windows PowerShell 中执行。Windows 原生启动脚本与完整搜索链路尚未实现和验证；如需在 Windows 上使用，当前优先建议 Windows 11 + WSL2/WSLg。

根目录 `.env` 支持：

| 配置 | 默认示例 | 用途 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./backend/data/skill-runner.db` | SQLite 数据库 |
| `RUN_ROOT` | `./backend/data/runs` | 每轮独立运行目录 |
| `SKILL_PATH` | `./skill` | Skill 目录 |
| `DYNAMIC_EXAMPLE_COUNT` | `3` | AUTO 动态示例数量 |
| `CODEX_COMMAND` | `codex` | Codex CLI 命令 |

## 接口

### POST /api/runs：启动任务

人工种子：

```bash
curl -sS -X POST 'http://127.0.0.1:8100/api/runs' \
  -H 'Content-Type: application/json' \
  --data '{"mode":"MANUAL_SEED","seed_text":"我怀疑你在开车，但我没有证据"}'
```

自主搜索：

```bash
curl -sS -X POST 'http://127.0.0.1:8100/api/runs' \
  -H 'Content-Type: application/json' \
  --data '{"mode":"AUTO"}'
```

成功返回 `202` 和 `run_id`。已有任务运行时返回 `409 ACTIVE_RUN_EXISTS`。

### GET /api/runs/{run_id}：查询任务实时状态

```bash
curl -sS 'http://127.0.0.1:8100/api/runs/{run_id}'
```

运行中会返回当前状态、已用时、Codex CLI 当前已经上报的 Token 统计、最近一条人类可读动态，以及已经确认的原始梗、模板和正式梗。尚未形成的产物为 `null`。

`token_usage.finalized=false` 表示 Codex CLI 尚未返回本轮最终用量；单次 Codex 调用通常只在 `turn.completed` 时上报精确统计。任务结束后 `finalized=true`，并一次返回终态产物；失败任务同时返回 `error` 和 `stop_reason`。

示例结构：

```json
{
  "run_id": "...",
  "mode": "AUTO",
  "status": "RUNNING",
  "elapsed_seconds": 42,
  "latest_activity": "已确认完整原梗，正在搜索严格变式。",
  "token_usage": {
    "input_tokens": 0,
    "cached_input_tokens": 0,
    "output_tokens": 0,
    "reasoning_tokens": 0,
    "total_tokens": 0,
    "finalized": false
  },
  "original_meme": {"title": "原梗标题", "text": "完整原梗"},
  "template": null,
  "formal_meme": null,
  "error": null,
  "stop_reason": null
}
```

### POST /api/runs/{run_id}/evaluation：提交整体评分

```bash
curl -sS -X POST 'http://127.0.0.1:8100/api/runs/{run_id}/evaluation' \
  -H 'Content-Type: application/json' \
  --data '{"score":12}'
```

分数为非负整数且不设最高分；重复提交覆盖原分数。

### GET /api/formal-memes：分页读取正式梗

```bash
curl -sS 'http://127.0.0.1:8100/api/formal-memes?page=1&page_size=20'
```

`page_size` 允许 `1～100`。结果按创建时间倒序返回。

## 数据检查

```bash
sqlite3 backend/data/skill-runner.db \
  "SELECT id, mode, status, error_code, created_at, finished_at FROM runs ORDER BY created_at DESC;"

sqlite3 backend/data/skill-runner.db \
  "SELECT run_id, sequence, stream, event_type, raw_text FROM run_logs ORDER BY run_id, sequence;"

sqlite3 backend/data/skill-runner.db \
  "SELECT id, source_run_id, original_title, final_title, final_text, score FROM formal_memes ORDER BY created_at DESC;"
```

## 自测

以下命令适用于 macOS、Linux 和 WSL，`/private/tmp` 是 Unix 临时目录：

```bash
UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache \
  uv sync --project backend --extra dev --frozen

UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache \
  uv run --project backend pytest -q backend/tests

UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache \
  uv run --project backend python -m compileall -q backend/app backend/tests
```

Windows PowerShell 可以仅验证后端代码与 Fake Runner，不代表真实浏览器搜索链路已受支持：

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP "zao-skill-runner-uv-cache"
uv sync --project backend --extra dev --frozen
uv run --project backend pytest -q backend/tests
uv run --project backend python -m compileall -q backend/app backend/tests
```

默认测试使用 Fake Runner，不会调用 Codex、模型或网页。真实任务会产生模型调用和浏览器行为。
