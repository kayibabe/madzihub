@echo off
setlocal EnableDelayedExpansion
title MadziHub - Stopping

rem Always act on the copy in this script's own folder.
cd /d "%~dp0"
set "APP_DIR=%CD%"

rem Options:
rem   stop.bat               stop this copy
rem   stop.bat --all         stop EVERY MadziHub/uvicorn server on this PC (any folder)
rem   stop.bat --port 8001   stop whatever this copy started on that port
rem   --silent               no prompts (used by start.bat)
set SILENT=0
set ALL=0
set "PORT="
:args
if "%~1"=="" goto args_done
if /i "%~1"=="--silent" set SILENT=1
if /i "%~1"=="--all" set ALL=1
if /i "%~1"=="--port" (
    set "PORT=%~2"
    shift
)
shift
goto args
:args_done

if not defined PORT if exist "data\madzihub.port" set /p PORT=<data\madzihub.port
if not defined PORT set "PORT=8000"
rem Strip any stray spaces read back from the file.
set "PORT=%PORT: =%"

if %SILENT%==0 (
    echo.
    echo  =====================================================
    echo    MadziHub - Stop
    echo    Folder: %APP_DIR%
    echo  =====================================================
    echo.
)

set STOPPED=0

rem -- 1. The PID this copy recorded when it started ---------------------------
call :stop_pidfile "data\madzihub.pid"

rem -- 2. Any Python server still listening on this copy's port ---------------
if %SILENT%==0 echo  Checking port %PORT%...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    tasklist /fi "PID eq %%p" /fo csv 2>nul | findstr /i "python" >nul
    if !errorlevel!==0 (
        taskkill /F /PID %%p >nul 2>&1
        if %SILENT%==0 echo  [OK] Stopped Python server on port %PORT% ^(PID %%p^).
        set STOPPED=1
    ) else (
        if %SILENT%==0 echo  [INFO] Port %PORT% is held by a non-Python program ^(PID %%p^) - left alone.
    )
)

rem -- 3. --all: every uvicorn app.main server, whichever folder it runs from --
if %ALL%==1 (
    if %SILENT%==0 echo  Stopping every MadziHub server on this PC...
    powershell -NoProfile -Command "$n = 0; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'app[.]main' } | ForEach-Object { Write-Host ('  [OK] Stopped PID ' + $_.ProcessId + ': ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; if ($n -eq 0) { Write-Host '  [INFO] None found.' }"
    set STOPPED=1
)

if %STOPPED%==0 (
    if %SILENT%==0 echo  [INFO] No running MadziHub server found for this folder.
) else (
    powershell -NoProfile -Command "Start-Sleep -Seconds 1"
)

if %SILENT%==0 (
    echo.
    echo  Done. Start again with:  start.bat
    echo.
    echo  This window closes in 5 seconds...
    timeout /t 5 >nul
)
endlocal
exit /b 0

rem ---------------------------------------------------------------------------
:stop_pidfile
if not exist "%~1" exit /b 0
set "SERVER_PID="
set /p SERVER_PID=<"%~1"
if defined SERVER_PID set "SERVER_PID=!SERVER_PID: =!"
if defined SERVER_PID (
    tasklist /fi "PID eq !SERVER_PID!" /fo csv 2>nul | findstr /i "python" >nul
    if !errorlevel!==0 (
        taskkill /F /PID !SERVER_PID! >nul 2>&1
        if %SILENT%==0 echo  [OK] Stopped server PID !SERVER_PID!.
        set STOPPED=1
    )
)
del "%~1" >nul 2>&1
exit /b 0
