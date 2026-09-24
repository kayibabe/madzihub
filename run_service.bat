@echo off
cd /d C:\WebApps\OpsApp

if not exist logs mkdir logs

REM If you use a virtual environment, keep this line.
REM If not, remove it.
call .venv\Scripts\activate.bat

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info >> logs\service.log 2>> logs\service-error.log