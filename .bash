@echo off
REM 激活 conda 环境
call C:\ProgramData\anaconda3\Scripts\activate.bat whisper2

REM 切换目录
cd /d c:\repo\whisperApp

REM 启动 python 程序，并给窗口设置标题 MyWhisperApp
start "MyWhisperApp" python app.py