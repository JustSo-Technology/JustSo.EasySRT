#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${REPO_ROOT}/frontend/dist"
FRONTEND_HOST="${EASYSRT_FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${EASYSRT_FRONTEND_PORT:-5173}"

if [[ ! -d "${DIST_DIR}" ]]; then
  echo "Frontend production bundle not found at ${DIST_DIR}" >&2
  echo "Run 'pnpm build' in ${REPO_ROOT}/frontend before starting the service." >&2
  exit 1
fi

exec /usr/bin/python3 "${REPO_ROOT}/ops/serve-frontend.py" \
  --root "${DIST_DIR}" \
  --host "${FRONTEND_HOST}" \
  --port "${FRONTEND_PORT}"
