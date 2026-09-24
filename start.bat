@echo off
setlocal EnableDelayedExpansion
title MadziHub - Starting

rem Always run from the folder this script lives in, so every copy of
rem MadziHub starts its own code (never a hard-coded path).
cd /d "%~dp0"
set "APP_DIR=%CD%"

rem Port: first argument, else MADZI_PORT, else 8000.   e.g.  start.bat 8001
set "PORT=%~1"
if not defined PORT set "PORT=%MADZI_PORT%"
if not defined PORT set "PORT=8000"

echo.
echo  =====================================================
echo    MadziHub - Water Utility Performance Platform
echo    Folder: %APP_DIR%
echo    Port:   %PORT%
echo  =====================================================
echo.

if not exist logs mkdir logs
if not exist data mkdir data

rem -- Is something already listening on the port? --------------------------
set "BUSY_PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do set "BUSY_PID=%%p"
if defined BUSY_PID (
    echo  [WARN] Port %PORT% is already in use by PID !BUSY_PID!:
    powershell -NoProfile -Command "$c = (Get-CimInstance Win32_Process -Filter 'ProcessId=!BUSY_PID!').CommandLine; if ($c) { '         ' + $c } else { '         (process details unavailable)' }"
    echo.
    echo  It may be another copy of the dashboard, running from a different folder.
    set "CHOICE="
    set /p CHOICE="  Stop it and start THIS copy instead? (Y/N): "
    if /i not "!CHOICE!"=="Y" (
        echo  Keeping the existing server. To run this copy alongside it:  start.bat 8001
        pause
        exit /b 0
    )
    call "%APP_DIR%\stop.bat" --silent --port %PORT%
    timeout /t 2 /nobreak >nul
)

rem -- Python: this folder's own virtual environment --------------------------
echo  [1/5] Locating Python...
set "VENV_DIR="
if exist "venv\Scripts\python.exe" set "VENV_DIR=%APP_DIR%\venv"
if not defined VENV_DIR if exist ".venv\Scripts\python.exe" set "VENV_DIR=%APP_DIR%\.venv"

if not defined VENV_DIR (
    echo         No virtual environment here yet - creating venv\ ...
    set "BASE_PY="
    where py >nul 2>&1 && set "BASE_PY=py -3"
    if not defined BASE_PY where python >nul 2>&1 && set "BASE_PY=python"
    if not defined BASE_PY (
        echo  [ERROR] Python not found. Install Python 3.11+ from python.org and tick "Add to PATH".
        pause
        exit /b 1
    )
    !BASE_PY! -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
    set "VENV_DIR=%APP_DIR%\venv"
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
echo         Using: %PYTHON_EXE%

rem -- Dependencies: reinstall whenever requirements.txt changes -------------
echo  [2/5] Checking dependencies...
fc /b "requirements.txt" "%VENV_DIR%\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo         Installing requirements - this can take a few minutes the first time...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo  [ERROR] pip install failed. See the messages above.
        pause
        exit /b 1
    )
    copy /y "requirements.txt" "%VENV_DIR%\requirements.installed" >nul
)
echo         Done.

rem -- Database seed (idempotent - safe on every start) ----------------------
echo  [3/5] Initialising database...
"%PYTHON_EXE%" scripts\seed_fiscal_years.py >> logs\seed.log 2>&1
if errorlevel 1 (
    echo  [WARN] Seed script reported an issue - check logs\seed.log
) else (
    echo         Done.
)

rem -- Start the server in the background ------------------------------------
echo  [4/5] Starting server on http://localhost:%PORT% ...
rem UTF-8 + unbuffered output, so the log is readable and complete straight away.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
powershell -NoProfile -Command "$p = Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port','%PORT%','--log-level','info' -WorkingDirectory '%APP_DIR%' -RedirectStandardOutput '%APP_DIR%\logs\madzihub.log' -RedirectStandardError '%APP_DIR%\logs\madzihub-error.log' -PassThru -WindowStyle Hidden; $p.Id | Out-File -Encoding ascii '%APP_DIR%\data\madzihub.pid'"
if errorlevel 1 (
    echo  [ERROR] Failed to start the server. Check logs\madzihub-error.log
    pause
    exit /b 1
)
> "data\madzihub.port" echo %PORT%

echo         Waiting for the server to be ready...
set READY=0
for /l %%i in (1,1,30) do (
    if !READY!==0 (
        timeout /t 1 /nobreak >nul
        powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:%PORT%/health' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
        if !errorlevel!==0 set READY=1
    )
)
if !READY!==0 (
    echo  [WARN] The server did not respond within 30 seconds.
    echo         Check logs\madzihub-error.log for startup errors.
    pause
    exit /b 1
)
echo         Server is ready.

rem -- First run: the one-time admin password goes to the log, so show it ----
set "FIRST_PW="
for /f "usebackq delims=" %%w in (`powershell -NoProfile -Command "$m = Select-String -Path '%APP_DIR%\logs\madzihub.log' -Pattern 'Password : (\S+)' -ErrorAction SilentlyContinue; if ($m) { $m[0].Matches[0].Groups[1].Value }"`) do set "FIRST_PW=%%w"
if defined FIRST_PW (
    echo.
    echo  *****************************************************
    echo    FIRST RUN - a default admin account was created
    echo      Username:  admin
    echo      Password:  !FIRST_PW!
    echo    Copy it now. You will choose a new one at first login.
    echo  *****************************************************
)

rem -- Open the browser --------------------------------------------------------
echo  [5/5] Opening the dashboard in your browser...
powershell -NoProfile -Command "Start-Process 'http://localhost:%PORT%'"

set /p SERVER_PID=<data\madzihub.pid
echo.
echo  =====================================================
echo    MadziHub is running
echo    URL:     http://localhost:%PORT%
echo    Folder:  %APP_DIR%
echo    PID:     %SERVER_PID%
echo    Log:     logs\madzihub.log
echo    Stop:    stop.bat
echo  =====================================================
echo.
pause
endlocal
