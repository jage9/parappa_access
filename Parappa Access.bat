@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" "scripts\accessible-menu.py" %*
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\accessible-menu.py" %*
) else (
    python "scripts\accessible-menu.py" %*
)
if errorlevel 1 (
    echo.
    echo Parappa Access could not start. See the message above.
    pause
    exit /b 1
)
