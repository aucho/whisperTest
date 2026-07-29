@echo off
chcp 65001 >nul
setlocal

set "PROJECT_ROOT=%~dp0.."
set "ENV_DIR=C:\Users\hh-ai\.conda\envs\fasterwhisper"
set "PYTHON_EXE=%ENV_DIR%\python.exe"
set "FIREWALL_RULE=Whisper API TCP 18000"

cd /d "%PROJECT_ROOT%"

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Run this script as Administrator.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] The required fasterwhisper Python executable was not found:
    echo   "%PYTHON_EXE%"
    pause
    exit /b 1
)

echo [1/4] Using the existing fasterwhisper environment:
echo   "%ENV_DIR%"

echo [2/4] Installing Python dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Verifying required modules...
"%PYTHON_EXE%" -c "import uvicorn, fastapi, faster_whisper; print('Python dependencies OK')"
if errorlevel 1 goto :failed

echo [4/4] Allowing inbound TCP port 18000...
netsh advfirewall firewall show rule name="%FIREWALL_RULE%" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="%FIREWALL_RULE%" dir=in action=allow protocol=TCP localport=18000 profile=any
    if errorlevel 1 goto :failed
) else (
    echo Firewall rule already exists: %FIREWALL_RULE%
)

echo.
echo Setup completed successfully.
echo Start the API with:
echo   scripts\start_api_18000.bat
echo.
echo The API will listen on:
echo   http://0.0.0.0:18000
echo Test it remotely with:
echo   http://SERVER_IP:18000/health
pause
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Review the command output above.
pause
exit /b 1
