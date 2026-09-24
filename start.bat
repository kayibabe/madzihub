@echo off
setlocal EnableDelayedExpansion
title SRWB Operations Dashboard — Starting

cd /d "C:\WebApps\opsapp"

echo.
echo  =====================================================
echo    SRWB Operations Dashboard
echo    Southern Region Water Board
echo  =====================================================
echo.

:: ── Check if already running on port 8000 ─────────────────────────────────
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo  [WARN] Port 8000 is already in use.
    echo.
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
        echo  Running process PID: %%p
        tasklist /fi "PID eq %%p" /fo list 2>nul | findstr "Image Name"
    )
    echo.
    echo  If this is the dashboard, it is already running.
    echo  Open:  http://localhost:8000
    echo.
    set /p CHOICE="  Force restart? (Y/N): "
    if /i "!CHOICE!" NEQ "Y" (
        echo  Keeping existing instance. Done.
        pause
        exit /b 0
    )
    echo  Stopping existing instance...
    call stop.bat --silent
    timeout /t 2 /nobreak >nul
)

:: ── Ensure logs directory exists ───────────────────────────────────────────
if not exist logs mkdir logs

:: ── Locate Python interpreter ───────────────────────────────────────────────
echo  [1/4] Locating Python interpreter...
set PYTHON_EXE=

if exist "C:\Users\Cromwell Mhango\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    set "PYTHON_EXE=C:\Users\Cromwell Mhango\AppData\Local\Python\pythoncore-3.14-64\python.exe"
) else if exist "C:\Python314\python.exe" (
    set "PYTHON_EXE=C:\Python314\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    echo  [ERROR] Python not found. Ensure PyManager or Python 3.14 is installed.
    pause
    exit /b 1
)
echo         Using: !PYTHON_EXE!

:: ── Verify uvicorn is available ─────────────────────────────────────────────
"!PYTHON_EXE!" -c "import uvicorn" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] uvicorn not installed.
    echo         Run:  "!PYTHON_EXE!" -m pip install -r requirements.txt
    pause
    exit /b 1
)

:: ── Run DB migration / seed (idempotent — safe every startup) ─────────────
echo  [2/4] Initialising database and seeding fiscal years...
"!PYTHON_EXE!" scripts\seed_fiscal_years.py >> logs\seed.log 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [WARN] Seed script reported an issue — check logs\seed.log
) else (
    echo         Done.
)

:: ── Start uvicorn in background, capture PID via PowerShell ───────────────
echo  [3/4] Starting server on http://localhost:8000 ...

powershell -NoProfile -Command ^
  "$pyExe = '!PYTHON_EXE!'.Replace('\','\\'); ^
   $p = Start-Process -FilePath '!PYTHON_EXE!' ^
    -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000','--log-level','info' ^
    -WorkingDirectory '%CD%' ^
    -RedirectStandardOutput 'logs\srwb.log' ^
    -RedirectStandardError  'logs\srwb-error.log' ^
    -PassThru -WindowStyle Hidden; ^
   $p.Id | Out-File -Encoding ascii 'data\srwb.pid'"

if %ERRORLEVEL% NEQ 0 (
    echo  [ERROR] Failed to start the server. Check logs\srwb-error.log
    pause
    exit /b 1
)

:: ── Wait for server to be ready (up to 15 seconds) ────────────────────────
echo         Waiting for server to be ready...
set READY=0
for /l %%i in (1,1,15) do (
    if !READY!==0 (
        timeout /t 1 /nobreak >nul
        curl -s -o nul -w "%%{http_code}" http://localhost:8000/health 2>nul | findstr "200" >nul
        if !ERRORLEVEL!==0 set READY=1
    )
)

if !READY!==0 (
    echo  [WARN] Server did not respond within 15 seconds.
    echo         Check logs\srwb-error.log for startup errors.
) else (
    echo         Server is ready.
)

:: ── Open browser ──────────────────────────────────────────────────────────
echo  [4/4] Opening dashboard in browser...
start "" "http://localhost:8000"

:: ── Show PID and summary ──────────────────────────────────────────────────
set /p SERVER_PID=<data\srwb.pid
echo.
echo  =====================================================
echo    Dashboard is running
echo    URL:     http://localhost:8000
echo    PID:     %SERVER_PID%
echo    Log:     logs\srwb.log
echo    Stop:    Run  stop.bat
echo  =====================================================
echo.
pause
endlocal
