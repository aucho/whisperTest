@echo off
chcp 65001 >nul

cd /d %~dp0\..

call C:\ProgramData\anaconda3\Scripts\activate.bat whisper
REM call venv\Scripts\activate.bat

python scripts\run_api.py --port 18002
