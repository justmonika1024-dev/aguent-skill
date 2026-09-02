# 凿 agugent 后端

## 本地启动

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
uv sync --dev
alembic upgrade head
uvicorn app.main:app --reload --env-file ../.env
```

复制根目录 `.env.example` 为 `.env` 后填写 Provider 配置。启动命令必须加载根目录
`.env`；否则 Provider 会回退为 Fake，仅执行本地占位流程。默认测试使用 Fake Provider，
不产生外部费用。

## 反馈闭环与运行边界

- 每轮到达 `WAITING_HUMAN_EVALUATION` 后都要提交七模块评价：原梗搜索计划、
  原梗选择、变式搜索计划、变式搜索结果、模板提取、候选生成和最终结果。
  各模块评分必填，模块意见、候选修改建议和总体意见均可留空。
- 评价由 N19 转成可审计的策略补丁和新策略版本；连续自主发现时，下一轮 N07
  会读取新版本中的搜索指令。完整反馈保留用于审计，N07 将其转成简短搜索词，
  并记录指令、查询 ID 和搜索词之间的映射。策略版本、评价、节点、证据和 API
  用量均持久化到 SQLite。
- N09 与 N11 针对同一个原梗共享变式补搜计数，最多补搜 2 次；达到上限后，
  自主发现会放弃当前原梗并继续寻找，人工种子会进入人工干预。
- N09 只保留逐字存在于 Exa 证据中的实质槽位改编，并排除“下一句是什么”、站点
  尾缀、小说章节标题、释义页和原句转载等包装文本。
- 活动任务只存在于当前后端进程内。重启后历史记录仍可查询，但运行中、暂停中或
  等待评价的任务不能原地恢复，需要新建任务。

## 自测

```bash
pytest -q
ruff check app tests
```
