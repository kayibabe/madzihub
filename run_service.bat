@echo off
REM Run from this script's own folder, so each copy of MadziHub starts itself.
cd /d "%~dp0"

if not exist logs mkdir logs

REM Use the project's virtual environment when there is one.
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info >> logs\service.log 2>> logs\service-error.log