@echo off
cd /d "%~dp0"

if exist ".venv\.ready" (
    if exist ".venv\Scripts\pythonw.exe" (
        start "" ".venv\Scripts\pythonw.exe" app.py
        exit /b 0
    )
)

call "%~dp0start.bat"
