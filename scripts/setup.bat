@echo off
setlocal
set "ROOT=%~dp0.."
where py >nul 2>nul || (echo Install Python 3 with py launcher.& exit /b 1)
where node >nul 2>nul || (echo Install Node.js.& exit /b 1)
where npm >nul 2>nul || (echo Install npm.& exit /b 1)
py -3 -m venv "%ROOT%\backend\.venv" || exit /b 1
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%\backend\requirements.txt" || exit /b 1
pushd "%ROOT%\frontend"
call npm install
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" exit /b %RC%
echo Setup complete. Set OPERATIONAL_ADMIN_CREDENTIAL privately to at least 16 characters, then run start.bat.
