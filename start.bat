@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\.ready" (
    echo [DFYZB] First run: preparing Python environment and dependencies...
    set "PY_CMD="
    py -3.13 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.13"
    if not defined PY_CMD py -3.12 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.12"
    if not defined PY_CMD py -3.11 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.11"
    if not defined PY_CMD py -3.10 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.10"
    if not defined PY_CMD python -c "import sys" >nul 2>&1 && set "PY_CMD=python"
    if not defined PY_CMD (
        echo [ERROR] Python not found. Please install Python 3.10-3.13 and check "Add to PATH".
        pause
        exit /b 1
    )
    if not exist ".venv\Scripts\python.exe" (
        echo [DFYZB] Creating virtual environment with %PY_CMD% ...
        %PY_CMD% -m venv .venv
        if errorlevel 1 (
            echo [ERROR] Failed to create .venv.
            pause
            exit /b 1
        )
    )
    echo [DFYZB] Installing packages from requirements.txt (Tsinghua mirror)...
    ".venv\Scripts\pip.exe" install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [DFYZB] Mirror failed, retrying default PyPI...
        ".venv\Scripts\pip.exe" install -r requirements.txt
        if errorlevel 1 (
            echo [ERROR] Dependency installation failed. Please check network or Python version (3.10-3.13).
            pause
            exit /b 1
        )
    )
    echo ok>".venv\.ready"
)

echo [DFYZB] Launching desktop console...
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0
