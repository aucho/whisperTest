@echo off
chcp 65001 >nul
REM NSSM 服务卸载脚本
REM 卸载三个 Whisper API Windows 服务

setlocal enabledelayedexpansion

REM 设置 NSSM 路径（请根据实际情况修改）
set NSSM_CMD=nssm

REM 检查 NSSM 是否可用
where %NSSM_CMD% >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未找到 NSSM，请先安装 NSSM
    echo.
    echo 下载地址: https://nssm.cc/download
    echo 安装后，请将 NSSM 添加到系统 PATH，或修改此脚本中的 NSSM_CMD 变量
    pause
    exit /b 1
)

echo ========================================
echo 开始卸载 Whisper API Windows 服务
echo ========================================
echo.

REM 服务名称
set SERVICE_NAME_1=WhisperAPI-18000
set SERVICE_NAME_2=WhisperAPI-18001
set SERVICE_NAME_3=WhisperAPI-18002

REM 卸载服务函数
call :uninstall_service %SERVICE_NAME_1%
call :uninstall_service %SERVICE_NAME_2%
call :uninstall_service %SERVICE_NAME_3%

echo.
echo ========================================
echo 服务卸载完成！
echo ========================================
echo.
pause
exit /b 0

:uninstall_service
setlocal
set SERVICE_NAME=%~1

echo [卸载] %SERVICE_NAME%...

REM 检查服务是否存在
sc query %SERVICE_NAME% >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [跳过] %SERVICE_NAME% 不存在，无需卸载
    endlocal
    goto :eof
)

REM 停止服务（如果正在运行）
echo [停止] 正在停止服务 %SERVICE_NAME%...
net stop %SERVICE_NAME% >nul 2>&1
timeout /t 2 /nobreak >nul

REM 删除服务
echo [删除] 正在删除服务 %SERVICE_NAME%...
%NSSM_CMD% remove %SERVICE_NAME% confirm
if %ERRORLEVEL% EQU 0 (
    echo [完成] %SERVICE_NAME% 卸载成功
) else (
    echo [警告] %SERVICE_NAME% 卸载失败，可能需要管理员权限
)

endlocal
goto :eof

