@echo off
REM Chay bot hoa don + viet bai + bao gia. Bo shortcut file nay vao shell:startup de tu chay khi bat may.
cd /d "%~dp0"
if not exist .env (
  echo Chua co file .env - doi ten .env.example thanh .env roi dien thong tin.
  pause
  exit /b
)
if not exist .venv python -m venv .venv
.venv\Scripts\pip install -q -r requirements.txt
:loop
.venv\Scripts\python bot.py
echo Bot dung, khoi dong lai sau 10 giay...
timeout /t 10 >nul
goto loop
