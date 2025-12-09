@echo off
chcp 65001 >nul

setlocal enabledelayedexpansion

set NSSM_CMD=nssm

%NSSM_CMD% --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    nssm.exe --version >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [error] NSSM not found, please install NSSM first
        echo.
        echo download address: https://nssm.cc/download
        echo after installation, please add NSSM to the system PATH, or modify the NSSM_CMD variable in this script
        pause
        exit /b 1
    ) else (
        set NSSM_CMD=nssm.exe
    )
)

echo ========================================
echo start uninstalling Whisper API Windows services
echo ========================================
echo.

set SERVICE_NAME_1=WhisperAPI-18000
set SERVICE_NAME_2=WhisperAPI-18001
set SERVICE_NAME_3=WhisperAPI-18002

call :uninstall_service %SERVICE_NAME_1%
call :uninstall_service %SERVICE_NAME_2%
call :uninstall_service %SERVICE_NAME_3%

echo.
echo ========================================
echo services uninstalled successfully!
echo ========================================
echo.
pause
exit /b 0

:uninstall_service
setlocal
set SERVICE_NAME=%~1

echo [uninstall] %SERVICE_NAME%...

sc query %SERVICE_NAME% >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [skip] %SERVICE_NAME% does not exist, no need to uninstall
    endlocal
    goto :eof
)

echo [stop] stopping service %SERVICE_NAME%...
net stop %SERVICE_NAME% >nul 2>&1
timeout /t 2 /nobreak >nul

echo [delete] deleting service %SERVICE_NAME%...
%NSSM_CMD% remove %SERVICE_NAME% confirm
if %ERRORLEVEL% EQU 0 (
    echo [success] %SERVICE_NAME% uninstalled successfully
) else (
    echo [warning] %SERVICE_NAME% uninstall failed, maybe need admin permissions
)

endlocal
goto :eof
