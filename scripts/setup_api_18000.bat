@echo off
chcp 65001 >nul
setlocal

set "PROJECT_ROOT=%~dp0.."
set "CONDA_EXE=C:\ProgramData\anaconda3\Scripts\conda.exe"
set "ENV_NAME=fasterwhisper"
set "FIREWALL_RULE=Whisper API TCP 18000"

cd /d "%PROJECT_ROOT%"

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Run this script as Administrator.
    pause
    exit /b 1
)

if not exist "%CONDA_EXE%" (
    echo [ERROR] Conda was not found: "%CONDA_EXE%"
    echo Update CONDA_EXE in this file if Conda is installed elsewhere.
    pause
    exit /b 1
)

echo [1/4] Checking Conda environment "%ENV_NAME%"...
"%CONDA_EXE%" run -n "%ENV_NAME%" python -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Environment not found. Creating it with Python 3.11...
    "%CONDA_EXE%" create -n "%ENV_NAME%" python=3.11 -y
    if errorlevel 1 goto :failed
)

echo [2/4] Installing Python dependencies...
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Verifying required modules...
"%CONDA_EXE%" run -n "%ENV_NAME%" python -c "import uvicorn, fastapi, faster_whisper; print('Python dependencies OK')"
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
