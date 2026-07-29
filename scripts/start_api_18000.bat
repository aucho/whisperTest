@echo off
chcp 65001 >nul
setlocal

set "PROJECT_ROOT=%~dp0.."
set "CONDA_EXE=C:\ProgramData\anaconda3\Scripts\conda.exe"
set "ENV_NAME=fasterwhisper"

cd /d "%PROJECT_ROOT%"

if not exist "%CONDA_EXE%" (
    echo [ERROR] Conda was not found: "%CONDA_EXE%"
    echo Update CONDA_EXE in this file if Conda is installed elsewhere.
    exit /b 1
)

"%CONDA_EXE%" run -n "%ENV_NAME%" python -c "import uvicorn, fastapi, faster_whisper" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Conda environment "%ENV_NAME%" is missing or incomplete.
    echo Run scripts\setup_api_18000.bat once as Administrator.
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

"%CONDA_EXE%" run --no-capture-output -n "%ENV_NAME%" python scripts\run_api.py --host 0.0.0.0 --port 18000
exit /b %ERRORLEVEL%
