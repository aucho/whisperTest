@echo off
chcp 65001 >nul

cd /d %~dp0\..

call C:\ProgramData\anaconda3\Scripts\activate.bat fasterwhisper
REM call venv\Scripts\activate.bat

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

python scripts\run_api.py --port 18000
