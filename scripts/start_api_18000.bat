@echo off
chcp 65001 >nul

cd /d %~dp0\..

call C:\ProgramData\anaconda3\Scripts\activate.bat whisper
REM call venv\Scripts\activate.bat

set WHISPER_MAX_CACHED_MODELS=1
set WHISPER_MODEL_IDLE_TIMEOUT=60

python scripts\run_api.py --port 18000
