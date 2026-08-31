# 凿 agugent 前端

React + TypeScript 的状态机控制台。开发时通过 Vite 代理访问 `http://127.0.0.1:8000/api/v1`，不会读取或保存 LLM/Exa 密钥。

## 从源码启动

前置要求：Node.js 20+、pnpm 11，且后端已在 8000 端口启动。

```bash
pnpm install --frozen-lockfile
pnpm dev
```

访问 `http://127.0.0.1:5173`。

## 自测

```bash
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
pnpm exec playwright test
```

端到端测试会拦截 API 请求并使用固定响应，适合验证前端路由与核心交互；真实联调时不要启动 Playwright，直接同时启动前后端。

MVP 中策略激活、正式梗下架和恢复尚无后端能力，因此相应操作明确显示为禁用态。
