#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
command -v python3 >/dev/null && command -v node >/dev/null && command -v npm >/dev/null || { echo 'Install Python 3, Node.js and npm first.' >&2; exit 1; }
python3 -m venv "$ROOT/backend/.venv"
"$ROOT/backend/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt"
(cd "$ROOT/frontend" && npm install)
echo 'Setup complete. Set OPERATIONAL_ADMIN_CREDENTIAL privately (16+ characters), then run ./start.sh.'
