@echo off
chcp 65001 >nul
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\hh-ai\.conda\envs\fasterwhisper\python.exe"

cd /d "%PROJECT_ROOT%"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] The required fasterwhisper Python executable was not found:
    echo   "%PYTHON_EXE%"
    exit /b 1
)

echo Using Python: "%PYTHON_EXE%"
"%PYTHON_EXE%" -c "import uvicorn, fastapi, faster_whisper"
if errorlevel 1 (
    echo [ERROR] The Python environment above is missing a required dependency.
    echo Install dependencies with:
    echo   "%PYTHON_EXE%" -m pip install -r "%PROJECT_ROOT%\requirements.txt"
    exit /b 1
)

set WHISPER_MODEL=turbo
set WHISPER_DEVICE=cuda
set WHISPER_DEVICE_INDEX=0
set WHISPER_COMPUTE_TYPE=float16
set WHISPER_BEAM_SIZE=5
set WHISPER_VAD_ENABLED=true
set WHISPER_VAD_MIN_SILENCE_MS=2000
set WHISPER_MODEL_CACHE_DIR=C:\models\faster-whisper
set WHISPER_CHUNK_SECONDS=3600
set WHISPER_CHUNK_OVERLAP_SECONDS=10
set WHISPER_CHUNK_TIMEOUT_SECONDS=7200
set WHISPER_QUEUE_MAX_TASKS=5
set WHISPER_MIN_FREE_DISK_GB=20
set WHISPER_WORKER_MAX_RSS_GROWTH_MB=2048
set PYTHONUNBUFFERED=1

"%PYTHON_EXE%" scripts\run_api.py --host 0.0.0.0 --port 18000
exit /b %ERRORLEVEL%
