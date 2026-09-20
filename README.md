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

## 要求

- macOS 或带桌面显示能力的运行环境；
- Python 3.12～3.14 和 [uv](https://docs.astral.sh/uv/)；
- 已安装并登录 `codex` CLI；
- Node.js 与 `npx` 可用；
- 已安装 Google Chrome；
- 只启动一个服务进程，不要修改为多 worker。

当前浏览器保持有头 Chrome 离屏运行方式。它仍可能在创建或切换标签页时短暂抢占前台，这是当前阶段保留的已知限制。

## 配置与启动

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

```bash
UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache \
  uv sync --project backend --extra dev --frozen

UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache \
  uv run --project backend pytest -q backend/tests

UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache \
  uv run --project backend python -m compileall -q backend/app backend/tests
```

默认测试使用 Fake Runner，不会调用 Codex、模型或网页。真实任务会产生模型调用和浏览器行为。
