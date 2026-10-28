@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo BitTrace virtual environment not found.
  pause
  exit /b 1
)
"venv\Scripts\python.exe" -m streamlit run app\Home.py --server.address 0.0.0.0 --server.port 8501
