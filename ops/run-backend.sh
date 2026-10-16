#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_HOST="${EASYSRT_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${EASYSRT_BACKEND_PORT:-8000}"
VENV_DIR="${REPO_ROOT}/backend/.venv"

cd "${REPO_ROOT}/backend"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Backend virtualenv not found at ${VENV_DIR}" >&2
  echo "Run the Ubuntu installer or create the backend venv before starting the service." >&2
  exit 1
fi

exec "${VENV_DIR}/bin/python" -m uvicorn app.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
