@echo off
REM =====================================================================
REM  Shine Autowerkz Invoice Bot - Khoi dong bot
REM  Chay 24/7 qua Task Scheduler. Log ghi vao logs\bot-YYYY-MM-DD.log.
REM =====================================================================

setlocal
cd /d "%~dp0"

REM Bat UTF-8 cho log tieng Viet
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM Tao thu muc log neu chua co
if not exist "logs" mkdir logs

REM Ten file log theo ngay
for /f "tokens=1-3 delims=/- " %%a in ("%date%") do set TODAY=%%c-%%b-%%a
set LOGFILE=logs\bot-%TODAY%.log

echo. >> "%LOGFILE%"
echo ==================== START %date% %time% ==================== >> "%LOGFILE%"

REM Chua co moi truong .venv (bi xoa hoac may moi) -> tu tao lai
if not exist ".venv\Scripts\python.exe" (
    echo Dang tao lai .venv, lan dau mat vai phut... >> "%LOGFILE%"
    py -3 -m venv .venv >> "%LOGFILE%" 2>&1 || python -m venv .venv >> "%LOGFILE%" 2>&1
)
if not exist ".venv\Scripts\python.exe" (
    echo KHONG TAO DUOC .venv - may chua cai Python hoac Python chua co trong PATH. >> "%LOGFILE%"
    echo KHONG TAO DUOC .venv - hay cai Python tu python.org, tick "Add python.exe to PATH".
    pause
    exit /b 3
)

REM Tu cai thu vien con thieu (theo requirements.txt). Loi mang thi bo qua, van chay bot.
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt >> "%LOGFILE%" 2>&1

REM Chay bot, redirect stdout + stderr vao log
".venv\Scripts\python.exe" bot.py >> "%LOGFILE%" 2>&1

echo ==================== EXIT  %date% %time% (code %errorlevel%) ==================== >> "%LOGFILE%"

endlocal
exit /b %errorlevel%
