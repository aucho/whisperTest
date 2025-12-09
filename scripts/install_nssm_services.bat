@echo off
chcp 65001 >nul
REM NSSM 服务安装脚本
REM 将三个 Whisper API 服务注册为 Windows 服务

setlocal enabledelayedexpansion

REM 设置项目根目录（脚本所在目录的上一级）
set PROJECT_ROOT=%~dp0\..

REM 设置 NSSM 路径（请根据实际情况修改）
REM 如果 NSSM 在系统 PATH 中，可以直接使用 nssm
REM 否则需要指定完整路径，例如：C:\tools\nssm\nssm.exe
set NSSM_CMD=nssm

REM 检查 NSSM 是否可用（直接尝试运行命令）
%NSSM_CMD% --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    REM 尝试使用 nssm.exe
    nssm.exe --version >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [错误] 未找到 NSSM，请先安装 NSSM
        echo.
        echo 下载地址: https://nssm.cc/download
        echo 安装后，请将 NSSM 添加到系统 PATH，或修改此脚本中的 NSSM_CMD 变量
        pause
        exit /b 1
    ) else (
        set NSSM_CMD=nssm.exe
    )
)

echo ========================================
echo 开始安装 Whisper API Windows 服务
echo ========================================
echo.

REM 服务配置
set SERVICE_NAME_1=WhisperAPI-18000
set SERVICE_NAME_2=WhisperAPI-18001
set SERVICE_NAME_3=WhisperAPI-18002

set SERVICE_DISPLAY_NAME_1=Whisper API Service (Port 18000)
set SERVICE_DISPLAY_NAME_2=Whisper API Service (Port 18001)
set SERVICE_DISPLAY_NAME_3=Whisper API Service (Port 18002)

set SERVICE_DESCRIPTION=Whisper 音频转文字 API 服务

REM Python 路径（请根据实际情况修改）
REM 如果使用 conda：
set PYTHON_EXE=C:\ProgramData\anaconda3\envs\whisper\python.exe
REM 如果使用 venv：
REM set PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe

REM 检查 Python 是否存在
if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到 Python 可执行文件: %PYTHON_EXE%
    echo 请修改脚本中的 PYTHON_EXE 变量为正确的 Python 路径
    pause
    exit /b 1
)

REM 启动脚本路径
set START_SCRIPT_1=%PROJECT_ROOT%\scripts\start_api_18000.bat
set START_SCRIPT_2=%PROJECT_ROOT%\scripts\start_api_18001.bat
set START_SCRIPT_3=%PROJECT_ROOT%\scripts\start_api_18002.bat

REM 日志目录
set LOG_DIR=%PROJECT_ROOT%\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo 项目根目录: %PROJECT_ROOT%
echo Python 路径: %PYTHON_EXE%
echo 日志目录: %LOG_DIR%
echo.

REM 安装服务函数
call :install_service %SERVICE_NAME_1% "%SERVICE_DISPLAY_NAME_1%" "%START_SCRIPT_1%" "%LOG_DIR%\service_18000.log"
call :install_service %SERVICE_NAME_2% "%SERVICE_DISPLAY_NAME_2%" "%START_SCRIPT_2%" "%LOG_DIR%\service_18001.log"
call :install_service %SERVICE_NAME_3% "%SERVICE_DISPLAY_NAME_3%" "%START_SCRIPT_3%" "%LOG_DIR%\service_18002.log"

echo.
echo ========================================
echo 服务安装完成！
echo ========================================
echo.
echo 已安装的服务：
echo   - %SERVICE_NAME_1%
echo   - %SERVICE_NAME_2%
echo   - %SERVICE_NAME_3%
echo.
echo 服务管理命令：
echo   启动服务: net start %SERVICE_NAME_1%
echo   停止服务: net stop %SERVICE_NAME_1%
echo   查看状态: sc query %SERVICE_NAME_1%
echo.
echo 服务将在系统启动时自动运行。
echo.
pause
exit /b 0

:install_service
setlocal
set SERVICE_NAME=%~1
set SERVICE_DISPLAY_NAME=%~2
set START_SCRIPT=%~3
set LOG_FILE=%~4

echo [安装] %SERVICE_NAME%...

REM 如果服务已存在，先删除
%NSSM_CMD% remove %SERVICE_NAME% confirm >nul 2>&1

REM 安装服务
%NSSM_CMD% install %SERVICE_NAME% "%START_SCRIPT%"

REM 配置服务参数
%NSSM_CMD% set %SERVICE_NAME% DisplayName "%SERVICE_DISPLAY_NAME%"
%NSSM_CMD% set %SERVICE_NAME% Description "%SERVICE_DESCRIPTION%"
%NSSM_CMD% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM_CMD% set %SERVICE_NAME% AppDirectory "%PROJECT_ROOT%"
%NSSM_CMD% set %SERVICE_NAME% AppStdout "%LOG_FILE%"
%NSSM_CMD% set %SERVICE_NAME% AppStderr "%LOG_FILE%"
%NSSM_CMD% set %SERVICE_NAME% AppRotateFiles 1
%NSSM_CMD% set %SERVICE_NAME% AppRotateOnline 1
%NSSM_CMD% set %SERVICE_NAME% AppRotateSeconds 86400
%NSSM_CMD% set %SERVICE_NAME% AppRotateBytes 10485760

REM 设置服务失败时自动重启
%NSSM_CMD% set %SERVICE_NAME% AppRestartDelay 5000
%NSSM_CMD% set %SERVICE_NAME% AppExit Default Restart

echo [完成] %SERVICE_NAME% 安装成功
endlocal
goto :eof

