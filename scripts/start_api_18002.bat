@echo off
chcp 65001 >nul
REM 启动 Whisper API 服务 - 端口 18002
REM 请根据实际情况修改 Python 环境路径

REM 设置项目根目录（脚本所在目录的上一级）
cd /d %~dp0\..

REM 激活 conda 环境（请根据实际情况修改路径和环境名称）
REM 如果使用 conda：
call C:\ProgramData\anaconda3\Scripts\activate.bat whisper
REM 如果使用 venv，取消注释下面这行并注释上面的 conda 行：
REM call venv\Scripts\activate.bat

REM 启动 API 服务
python scripts\run_api.py --port 18002

