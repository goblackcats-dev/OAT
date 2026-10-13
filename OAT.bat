@echo off
REM One-click launcher (no .exe needed). Double-click to run.
cd /d "%~dp0"
if not exist .venv (
  echo First-time setup, this takes a minute...
  python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  call .venv\Scripts\activate
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
python -m oat.run %*
echo.
pause
