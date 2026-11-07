# Local operational startup

The launchers now start the secured operational API (`backend/operational_api_main.py`), not the synthetic demo backend. For setup and security requirements, follow [docs/OPERATIONAL_HANDOFF.md](docs/OPERATIONAL_HANDOFF.md). Use `scripts/setup.sh` or `scripts\\setup.bat` once, set `OPERATIONAL_ADMIN_CREDENTIAL` privately (16+ characters), then run `./start.sh` or `start.bat`. UI defaults to `http://127.0.0.1:28752`; operational API defaults to `http://127.0.0.1:8765`. They use separate `OPERATIONAL_DB` and `LEDGER_DEMO_DB`; never point one mode at the other's database. SQLite is single-workspace only. Health is not production readiness.

## One-time prerequisites (manual; no installer is run by launchers)

- Python 3.10+ and Node.js 18+ with npm. Confirm with `python3 --version` / `node --version` / `npm --version` in Linux, or `py --version` / `node --version` / `npm --version` in Windows.
- From the project root, create a backend virtual environment and install the declared Python requirements yourself:

  Linux / WSL:
  ```sh
  python3 -m venv backend/.venv
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
  ```
  Windows PowerShell:
  ```powershell
  py -3 -m venv backend\.venv
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
  ```
- Install frontend dependencies manually once:
  ```sh
  cd frontend
  npm install
  cd ..
  ```
  In Windows Explorer, Shift+right-click the project folder and open PowerShell there; use `cd frontend`, `npm install`, then `cd ..`.

The generated `backend/.venv`, `frontend/node_modules`, and SQLite database are local runtime data. Keep personal data out of this synthetic demo. Do not put credentials in environment variables or files.

## Ports, API, and database

Defaults: frontend `127.0.0.1:28752`, API `127.0.0.1:28751`. The frontend Vite proxy receives `LEDGER_API_URL` from the launcher, so changing backend port also changes API routing. Both servers bind to loopback only. If a default port is occupied, the launcher exits without affecting that service. Choose unused ports by setting `LEDGER_BACKEND_PORT` and `LEDGER_FRONTEND_PORT` before starting (Linux: `LEDGER_BACKEND_PORT=... LEDGER_FRONTEND_PORT=... ./start.sh`; Windows PowerShell: `$env:LEDGER_BACKEND_PORT='...'; $env:LEDGER_FRONTEND_PORT='...'; .\start.bat`). Use distinct numeric ports 1–65535. `LEDGER_DEMO_DB` may point to a different SQLite file; the default is `backend/ledger-demo.sqlite3` and persists between launches.

Check API identity at `http://127.0.0.1:<backend-port>/api/health` and frontend at `http://127.0.0.1:<frontend-port>`. Never delete or overwrite an existing database to troubleshoot startup.

## Troubleshooting

- A prerequisite error identifies the missing executable or local setup step. Install only after deciding to do so; launcher scripts do not install anything.
- A port-in-use error means choose another unused port; do not kill a process you do not recognize.
- If a service exits, read its console output. The Linux launcher stops only its own child processes. On Windows, closing the frontend launcher console stops the frontend; use Task Manager only after identifying the backend process started by that launch.
- WSL users can use the Linux commands in the project under `/home/...` or `/mnt/c/...`. For best filesystem performance, keep a WSL checkout in the Linux filesystem. A Windows browser can usually open the same localhost URL while WSL's servers are running; if that fails, use Windows-native `start.bat`.
