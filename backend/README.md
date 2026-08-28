# 凿 agugent 后端

## 本地启动

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
uv sync --dev
alembic upgrade head
uvicorn app.main:app --reload
```

复制根目录 `.env.example` 为 `.env` 后填写 Provider 配置。默认测试使用 Fake Provider，不产生外部费用。

## 自测

```bash
pytest -q
ruff check app tests
```
