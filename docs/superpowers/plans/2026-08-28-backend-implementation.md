# 凿 agugent Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 按技术方案实现可从源码启动、可自测的完整 MVP 后端。

**Architecture:** FastAPI + SQLAlchemy 2 async + SQLite，采用单任务内存状态机；节点通过统一契约执行，Provider 通过适配器注入，REST/SSE 提供外部控制和可读进度。

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, aiosqlite, httpx, openai SDK, pytest, respx, Ruff, mypy。

**Spec:** `/Users/yimingjun/Documents/Codex/2026-08-26/wo-x/outputs/凿agugent-技术方案.md`

## Global Constraints

- 单任务串行；活动任务只保存在内存，崩溃不恢复。
- SQLite 单文件；不使用 Redis、消息队列或容器编排。
- LLM Provider 仅内置 OpenAI Responses 与 DeepSeek Chat；搜索 Provider 仅 Exa。
- N01～N20、N11.5 路由、五候选、结构化人工评价和策略反馈必须符合技术方案。
- 所有外部调用默认由测试 Fake/HTTP mock 替代，真实测试显式开启。

### Task 1: 项目骨架、配置、契约和数据库

**Files:** `backend/pyproject.toml`, `backend/app/config.py`, `backend/app/contracts/**`, `backend/app/db/**`, `backend/migrations/**`, `backend/tests/unit/test_config.py`, `backend/tests/unit/test_contracts.py`

- [ ] 初始化后端包、依赖、Settings、Pydantic 节点/API 契约、SQLAlchemy 模型和 Alembic 初始迁移。
- [ ] 先写配置/契约/迁移失败测试，再实现并运行通过。

### Task 2: Provider 与节点实现

**Files:** `backend/app/providers/**`, `backend/app/workflow/nodes/**`, `backend/app/prompts/**`, `backend/tests/contract/**`, `backend/tests/unit/test_nodes.py`

- [ ] 实现统一 LLM 接口、OpenAI Responses、DeepSeek Chat、Exa 搜索、Fake Provider。
- [ ] 实现 N01～N20 的输入输出校验及确定性规则；LLM 节点通过 Provider，不把外部调用写入节点逻辑。
- [ ] 先写合同测试覆盖结构化输出、重试、Exa 清洗、N11.5/N12/N13 核心约束。

### Task 3: 状态机、分支、人工评价与策略反馈

**Files:** `backend/app/workflow/**`, `backend/app/services/**`, `backend/tests/integration/test_workflow.py`

- [ ] 实现 RunContext、TransitionTable、CommandQueue、事件总线、分支修正、暂停/终止/重试。
- [ ] 实现 N17 准入矩阵、N18 评价等待、N19 StrategyPatch、N20 事务归档和持续执行。
- [ ] 先写 Fake Provider 全链路红测，再实现至人工种子/自主发现两条链路通过。

### Task 4: REST、SSE、归档和安全

**Files:** `backend/app/api/**`, `backend/app/main.py`, `backend/tests/api/**`, `backend/tests/integration/test_sse.py`

- [ ] 实现技术方案中的系统、任务、命令、评价、历史、正式梗和策略 API。
- [ ] 实现 SSE 事件、断线补发、stream.reset、心跳、错误响应和秘密脱敏。
- [ ] 增加 API/SSE 集成测试及 SQLite 事务回滚测试。

### Task 5: 自测、文档和交付

**Files:** `backend/README.md`, `backend/tests/**`, `.env.example`, `.gitignore`

- [ ] 补齐单元、合同、集成和真实冒烟测试入口。
- [ ] 执行迁移、Ruff、mypy、pytest 覆盖率和健康检查命令；修复失败后再交付。
- [ ] 记录尚未具备真实凭据时的未执行项，不将 mock 结果宣称为真实 Provider 验证。
