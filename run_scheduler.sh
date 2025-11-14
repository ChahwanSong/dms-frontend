#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

export DMS_SCHEDULER_URL="${DMS_SCHEDULER_URL:-http://127.0.0.1:9000}"

if [[ -z "${VIRTUAL_ENV:-}" && -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.venv/bin/activate"
fi

echo "Starting local scheduler stub on ${DMS_SCHEDULER_URL}" >&2
exec python3 -m uvicorn "cli.local_scheduler:app" --host 127.0.0.1 --port 9000
