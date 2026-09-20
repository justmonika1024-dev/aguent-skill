#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
AGUGENT_HOST="${AGUGENT_HOST:-127.0.0.1}"
AGUGENT_PORT="${AGUGENT_PORT:-8100}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${BACKEND_DIR}/.uv-cache}"

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "Missing ${PROJECT_DIR}/.env. Copy .env.example to .env first." >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/skill/SKILL.md" ]]; then
  echo "Missing ${PROJECT_DIR}/skill/SKILL.md." >&2
  exit 1
fi

cd "${PROJECT_DIR}"
uv sync --project "${BACKEND_DIR}" --frozen
exec uv run --project "${BACKEND_DIR}" uvicorn \
  --app-dir "${BACKEND_DIR}" \
  app.main:app \
  --host "${AGUGENT_HOST}" \
  --port "${AGUGENT_PORT}" \
  --workers 1
