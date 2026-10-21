@echo off
setlocal
cd /d "%~dp0"
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw.exe "app.py"
) else (
    python "app.py"
)
