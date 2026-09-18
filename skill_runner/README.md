# 凿agugent Skill Runner

这是一个独立、轻量的本地服务。它只提供 `POST /api/runs`，用于在全新的临时目录和 Codex CLI 对话中启动一轮 `zao-agugent-supervisor` Skill。支持人工种子 `MANUAL_SEED` 和自主搜索 `AUTO` 两种模式。

任务成功到达 `H02 / WAITING_HUMAN_EVALUATION` 后，运行结果立即写入 SQLite 正式梗库；是否能在后续 AUTO 轮次中作为动态示例，仍由 `dynamic_example_eligible` 字段控制，默认关闭。

服务每次启动时会幂等确保数据库中存在 5 组此前实验中已认可的运行结果，包含 4 条短梗和 1 条完整长梗。这些记录使用普通的 `AUTO` 或 `MANUAL_SEED` 运行结构，正式梗评价状态为 `PASSED`，并可直接参与 AUTO 的随机动态示例；已有数据库会补齐缺失记录，重复启动不会重复写入。

## 运行要求

- Python 3.12～3.14 和 [uv](https://docs.astral.sh/uv/)；
- 本机已安装并登录 `codex` CLI；
- Node.js 与 `npx` 可用，首次运行允许下载 `@playwright/mcp`；
- 当前实现使用有界面的 Playwright 浏览器，运行环境必须有桌面显示能力；
- `SKILL_PATH/SKILL.md` 必须存在且可读；
- 服务只能启动一个 worker。进程内只允许一轮任务运行，多 worker 会破坏这一约束。

## 安装与启动

从源码目录执行：

```bash
cd skill_runner
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

`.env.example` 假定 Skill 位于仓库根目录的 `.agents/skills/zao-agugent-supervisor`。如果从其他目录启动，需把 `SKILL_PATH` 改为对应的绝对路径或正确相对路径。

可配置项：

| 配置 | 默认示例 | 用途 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/skill-runner.db` | SQLite 数据库地址 |
| `RUN_ROOT` | `./data/runs` | 每轮独立运行目录的根目录 |
| `SKILL_PATH` | `../.agents/skills/zao-agugent-supervisor` | 要复制进运行目录的 Skill |
| `DYNAMIC_EXAMPLE_COUNT` | `3` | AUTO 最多随机注入的合格动态示例数 |
| `CODEX_COMMAND` | `codex` | Codex CLI 可执行文件 |

## 启动一轮任务

人工种子模式：

```bash
curl -sS -X POST 'http://127.0.0.1:8100/api/runs' \
  -H 'Content-Type: application/json' \
  --data '{"mode":"MANUAL_SEED","seed_text":"我怀疑你在开车，但我没有证据"}'
```

自主搜索模式：

```bash
curl -sS -X POST 'http://127.0.0.1:8100/api/runs' \
  -H 'Content-Type: application/json' \
  --data '{"mode":"AUTO"}'
```

接口返回 `202` 和任务 ID。服务没有查询、评价、日志或正式梗 HTTP 接口；当前阶段直接检查 SQLite 和运行目录。

同一进程已有任务时返回：

```json
{
  "error": {
    "code": "ACTIVE_RUN_EXISTS",
    "message": "another run is active"
  }
}
```

## 查看结果

每轮目录位于 `RUN_ROOT/{run_id}`，保留输入 Prompt、Skill 生成的机器记录、搜索记录和最终摘要。服务不会自动清理这些目录。

默认数据库可这样查看：

```bash
sqlite3 data/skill-runner.db \
  "SELECT id, mode, status, error_code, skill_stop_reason, created_at, finished_at FROM runs ORDER BY created_at DESC;"

sqlite3 data/skill-runner.db \
  "SELECT run_id, sequence, stream, event_type, raw_text FROM run_logs ORDER BY run_id, sequence;"

sqlite3 data/skill-runner.db \
  "SELECT id, source_run_id, original_title, final_title, final_text, evaluation_status, dynamic_example_eligible FROM formal_memes ORDER BY created_at DESC;"
```

只有 Codex CLI 退出码为零、且 `run-result.json` 合法停在 H02 的任务才会写入 `formal_memes`。证据不足等 Skill 合法停止会记为 `FAILED`，具体原因保留在 `runs` 和 `run_logs`。

## 自测

```bash
UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache uv run pytest -q
UV_CACHE_DIR=/private/tmp/zao-skill-runner-uv-cache uv run python -m compileall -q app tests
```

默认测试使用 Fake Runner，不会启动 Codex、Playwright、模型请求或网络访问。真实测试会产生模型费用和网页搜索行为，应在人工确认本机 Codex 登录、浏览器环境和 Skill 路径后，通过上述 HTTP 请求单独执行。
