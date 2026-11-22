@echo off
setlocal
cd /d "%~dp0"
if not exist config.yaml copy config.example.yaml config.yaml >nul
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv
    if errorlevel 1 goto failure
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto failure
)
.venv\Scripts\python.exe main.py
if errorlevel 1 goto failure
exit /b 0
:failure
echo Launcher failed. Install Python 3.10+ with Tkinter and the Python launcher.
echo To repair dependencies: .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
