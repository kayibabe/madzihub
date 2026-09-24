@echo off
setlocal EnableDelayedExpansion
title SRWB Operations Dashboard — Stopping

cd /d "C:\WebApps\opsapp"

:: Silent mode flag (used when called from start.bat --silent)
set SILENT=0
if "%1"=="--silent" set SILENT=1

if !SILENT!==0 (
    echo.
    echo  =====================================================
    echo    SRWB Operations Dashboard — Stop
    echo  =====================================================
    echo.
)

set STOPPED=0

:: ── Method 1: PID file ────────────────────────────────────────────────────
if exist "data\srwb.pid" (
    set /p SERVER_PID=<data\srwb.pid
    if defined SERVER_PID (
        :: Verify the PID is still a running python/uvicorn process
        tasklist /fi "PID eq !SERVER_PID!" /fo csv 2>nul | findstr /i "python" >nul
        if !ERRORLEVEL!==0 (
            if !SILENT!==0 echo  Stopping PID !SERVER_PID! ^(from PID file^)...
            taskkill /F /PID !SERVER_PID! >nul 2>&1
            if !ERRORLEVEL!==0 (
                if !SILENT!==0 echo  [OK] Process !SERVER_PID! terminated.
                set STOPPED=1
            ) else (
                if !SILENT!==0 echo  [WARN] Could not kill PID !SERVER_PID! — may have already exited.
                set STOPPED=1
            )
        ) else (
            if !SILENT!==0 echo  [INFO] PID !SERVER_PID! is no longer running.
            set STOPPED=1
        )
    )
    del "data\srwb.pid" >nul 2>&1
)

:: ── Method 2: Kill ALL Python processes on port 8000 ─────────────────────
if !SILENT!==0 echo  Scanning port 8000 for any remaining Python processes...

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    tasklist /fi "PID eq %%p" /fo csv 2>nul | findstr /i "python" >nul
    if !ERRORLEVEL!==0 (
        if !SILENT!==0 echo  Killing Python on port 8000 ^(PID %%p^)...
        taskkill /F /PID %%p >nul 2>&1
        if !SILENT!==0 echo  [OK] PID %%p terminated.
        set STOPPED=1
    )
)

:: ── Method 3: Widen search — any uvicorn process ─────────────────────────
if !SILENT!==0 echo  Searching for any uvicorn process...
for /f "tokens=2 delims=," %%p in (
    'wmic process where "commandline like ''%%uvicorn%%app.main%%''" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"'
) do (
    set PID_FOUND=%%p
    set PID_FOUND=!PID_FOUND: =!
    if defined PID_FOUND (
        if !SILENT!==0 echo  Found uvicorn process PID !PID_FOUND!. Stopping...
        taskkill /F /PID !PID_FOUND! >nul 2>&1
        if !SILENT!==0 echo  [OK] PID !PID_FOUND! terminated.
        set STOPPED=1
    )
)

:done
if !STOPPED!==0 (
    if !SILENT!==0 (
        echo  [INFO] No running dashboard process found. Nothing to stop.
    )
) else (
    :: Brief pause to let port release
    timeout /t 1 /nobreak >nul
)

if !SILENT!==0 (
    echo.
    echo  =====================================================
    echo    Dashboard stopped. Port 8000 is now free.
    echo    Run  start.bat  to restart.
    echo  =====================================================
    echo.
    pause
)

endlocal
