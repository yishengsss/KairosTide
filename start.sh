#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
API_PYTHON="$PROJECT_ROOT/services/api/.venv/bin/python"
VITE_BIN="$PROJECT_ROOT/apps/web/node_modules/.bin/vite"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required to install and run the web app." >&2
  exit 1
fi

if [[ ! -x "$API_PYTHON" ]]; then
  python3 -m venv "$PROJECT_ROOT/services/api/.venv"
fi

if ! "$API_PYTHON" -c 'import fastapi, uvicorn, pydantic, PIL' >/dev/null 2>&1; then
  "$API_PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"
fi

if [[ ! -x "$VITE_BIN" ]]; then
  npm ci --prefix "$PROJECT_ROOT/apps/web"
fi

echo "Starting Kairos. Follow the Vite URL and API address printed below."
exec "$API_PYTHON" "$PROJECT_ROOT/scripts/dev.py"
