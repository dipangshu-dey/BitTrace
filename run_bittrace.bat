@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo BitTrace virtual environment not found.
  echo Expected: %CD%\venv\Scripts\python.exe
  pause
  exit /b 1
)
"venv\Scripts\python.exe" -m streamlit run app\Home.py
