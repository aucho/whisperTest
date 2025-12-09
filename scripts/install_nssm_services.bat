@echo off
chcp 65001 >nul

setlocal enabledelayedexpansion

set PROJECT_ROOT=%~dp0\..

set NSSM_CMD=nssm

%NSSM_CMD% --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 or %ERRORLEVEL% NEQ 1 (
    nssm.exe --version >nul 2>&1
    if %ERRORLEVEL% NEQ 0 or %ERRORLEVEL% NEQ 1 (
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
echo start installing Whisper API Windows services
echo ========================================
echo.

set SERVICE_NAME_1=WhisperAPI-18000
set SERVICE_NAME_2=WhisperAPI-18001
set SERVICE_NAME_3=WhisperAPI-18002

set SERVICE_DISPLAY_NAME_1=Whisper API Service (Port 18000)
set SERVICE_DISPLAY_NAME_2=Whisper API Service (Port 18001)
set SERVICE_DISPLAY_NAME_3=Whisper API Service (Port 18002)

set SERVICE_DESCRIPTION=Whisper audio to text API service

set PYTHON_EXE=C:\ProgramData\anaconda3\envs\whisper\python.exe
REM set PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe

if not exist "%PYTHON_EXE%" (
    echo [error] Python executable file not found: %PYTHON_EXE%
    echo please modify the PYTHON_EXE variable in the script to the correct Python path
    pause
    exit /b 1
)

set START_SCRIPT_1=%PROJECT_ROOT%\scripts\start_api_18000.bat
set START_SCRIPT_2=%PROJECT_ROOT%\scripts\start_api_18001.bat
set START_SCRIPT_3=%PROJECT_ROOT%\scripts\start_api_18002.bat

set LOG_DIR=%PROJECT_ROOT%\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo project root directory: %PROJECT_ROOT%
echo Python path: %PYTHON_EXE%
echo log directory: %LOG_DIR%
echo.

call :install_service %SERVICE_NAME_1% "%SERVICE_DISPLAY_NAME_1%" "%START_SCRIPT_1%" "%LOG_DIR%\service_18000.log"
call :install_service %SERVICE_NAME_2% "%SERVICE_DISPLAY_NAME_2%" "%START_SCRIPT_2%" "%LOG_DIR%\service_18001.log"
call :install_service %SERVICE_NAME_3% "%SERVICE_DISPLAY_NAME_3%" "%START_SCRIPT_3%" "%LOG_DIR%\service_18002.log"

echo.
echo ========================================
echo services installed successfully!
echo ========================================
echo.
echo installed services:
echo   - %SERVICE_NAME_1%
echo   - %SERVICE_NAME_2%
echo   - %SERVICE_NAME_3%
echo.
echo service management commands:
echo   start service: net start %SERVICE_NAME_1%
echo   stop service: net stop %SERVICE_NAME_1%
echo   query status: sc query %SERVICE_NAME_1%
echo.
echo services will run automatically on system startup.
echo.
pause
exit /b 0

:install_service
setlocal
set SERVICE_NAME=%~1
set SERVICE_DISPLAY_NAME=%~2
set START_SCRIPT=%~3
set LOG_FILE=%~4

echo [install] %SERVICE_NAME%...

%NSSM_CMD% remove %SERVICE_NAME% confirm >nul 2>&1

%NSSM_CMD% install %SERVICE_NAME% "%START_SCRIPT%"

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

%NSSM_CMD% set %SERVICE_NAME% AppRestartDelay 5000
%NSSM_CMD% set %SERVICE_NAME% AppExit Default Restart

echo [success] %SERVICE_NAME% success
endlocal
goto :eof
