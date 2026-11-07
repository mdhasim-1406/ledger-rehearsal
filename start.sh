#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
API_PORT="${OPERATIONAL_PORT:-8765}"; UI_PORT="${LEDGER_FRONTEND_PORT:-28752}"
DB="${OPERATIONAL_DB:-$ROOT/data/operational.sqlite3}"
for cmd in python3 node npm; do command -v "$cmd" >/dev/null || { echo "ERROR: missing $cmd" >&2; exit 1; }; done
[[ "$API_PORT" =~ ^[0-9]+$ && "$API_PORT" -ge 1 && "$API_PORT" -le 65535 && "$UI_PORT" =~ ^[0-9]+$ && "$UI_PORT" -ge 1 && "$UI_PORT" -le 65535 && "$API_PORT" != "$UI_PORT" ]] || { echo 'ERROR: OPERATIONAL_PORT and LEDGER_FRONTEND_PORT must be distinct valid ports.' >&2; exit 1; }
[[ -x "$ROOT/backend/.venv/bin/python" && -x "$ROOT/frontend/node_modules/.bin/vite" ]] || { echo 'ERROR: run scripts/setup.sh first.' >&2; exit 1; }
[[ -n "${OPERATIONAL_ADMIN_CREDENTIAL:-}" && ${#OPERATIONAL_ADMIN_CREDENTIAL} -ge 16 ]] || { echo 'ERROR: Set OPERATIONAL_ADMIN_CREDENTIAL to a private value of at least 16 characters.' >&2; exit 1; }
export OPERATIONAL_PORT="$API_PORT" OPERATIONAL_DB="$DB" OPERATIONAL_HOST=127.0.0.1
# Gemini 3.8 Flash is the selected investigation model. Secrets stay in process environment.
export INVESTIGATION_LLM_MODEL="${INVESTIGATION_LLM_MODEL:-agy/gemini-3.8-flash-medium}"
if [[ -z "${INVESTIGATION_LLM_API_KEY:-}" && -z "${INVESTIGATION_LLM_BASE_URL:-}" && -n "${OMNIROUTE_API_KEY:-}" ]]; then
  export INVESTIGATION_LLM_API_KEY="$OMNIROUTE_API_KEY"
  export INVESTIGATION_LLM_BASE_URL="${INVESTIGATION_LLM_BASE_URL:-http://127.0.0.1:20128/v1}"
fi
# Never pass the credential through command arguments or print it.
mkdir -p "$(dirname "$DB")"
for p in "$API_PORT" "$UI_PORT"; do python3 - "$p" <<'PY'
import socket,sys
s=socket.socket(); s.settimeout(.2)
try: s.connect(('127.0.0.1',int(sys.argv[1])))
except OSError: pass
else: raise SystemExit(f'ERROR: port {sys.argv[1]} is occupied; no processes were stopped')
finally: s.close()
PY
done
export VITE_OPERATIONAL_API="http://127.0.0.1:$API_PORT"
export VITE_API_MODE=operational VITE_API_BASE=/api
cd "$ROOT"
PIDS=(); cleanup(){ for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; for p in "${PIDS[@]}"; do wait "$p" 2>/dev/null || true; done; }; trap cleanup EXIT INT TERM
"$ROOT/backend/.venv/bin/python" -m uvicorn backend.operational_api_main:app --host 127.0.0.1 --port "$API_PORT" & PIDS+=("$!")
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port "$UI_PORT" --strictPort) & PIDS+=("$!")
echo "Operational API: http://127.0.0.1:$API_PORT; UI: http://127.0.0.1:$UI_PORT"
while :; do for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null || { echo 'ERROR: service exited.' >&2; exit 1; }; done; sleep 1; done
