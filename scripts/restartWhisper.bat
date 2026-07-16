@echo off
SETLOCAL

set SERVICES=WhisperAPI-18000
for %%S in (%SERVICES%) do (
    echo ==============================
    echo restart service %%S ...
    net stop "%%S" /y
    timeout /t 5 /nobreak >nul
    net start "%%S"
    echo service %%S restarted
    echo ==============================
)

echo all services restarted
ENDLOCAL
pause
