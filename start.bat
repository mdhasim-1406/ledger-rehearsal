@echo off
setlocal
set "ROOT=%~dp0"
if "%OPERATIONAL_PORT%"=="" set "OPERATIONAL_PORT=8765"
if "%LEDGER_FRONTEND_PORT%"=="" set "LEDGER_FRONTEND_PORT=28752"
if "%OPERATIONAL_DB%"=="" set "OPERATIONAL_DB=%ROOT%data\operational.sqlite3"
if "%OPERATIONAL_ADMIN_CREDENTIAL%"=="" (echo ERROR: Set OPERATIONAL_ADMIN_CREDENTIAL in your private shell environment; never put it in this file.& exit /b 1)
if not exist "%ROOT%backend\.venv\Scripts\python.exe" (echo ERROR: Run scripts\setup.bat first.& exit /b 1)
if not exist "%ROOT%frontend\node_modules\.bin\vite.cmd" (echo ERROR: Run scripts\setup.bat first.& exit /b 1)
set "VITE_OPERATIONAL_API=http://127.0.0.1:%OPERATIONAL_PORT%"
set "VITE_API_MODE=operational"
set "VITE_API_BASE=/api"
echo Operational API http://127.0.0.1:%OPERATIONAL_PORT% and UI http://127.0.0.1:%LEDGER_FRONTEND_PORT%
echo Close this window to stop services started here.
start "Operational API" /b "%ROOT%backend\.venv\Scripts\python.exe" -m uvicorn backend.operational_api_main:app --app-dir "%ROOT%" --host 127.0.0.1 --port %OPERATIONAL_PORT%
pushd "%ROOT%frontend"
call npm run dev -- --host 127.0.0.1 --port %LEDGER_FRONTEND_PORT% --strictPort
set "RC=%ERRORLEVEL%"
popd
echo Stop the API console window separately if it remains running.
exit /b %RC%
