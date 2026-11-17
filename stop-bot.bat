@echo off
REM =====================================================================
REM  Dung bot (tim tien trinh python.exe dang chay bot.py roi kill).
REM  Dung khi can update code hoac restart.
REM =====================================================================

setlocal
echo Tim tien trinh bot dang chay...

REM WMIC tim python.exe co command line chua "bot.py"
for /f "tokens=2" %%p in ('wmic process where "name='python.exe' and CommandLine like '%%bot.py%%'" get ProcessId /value ^| find "="') do (
    echo Dung PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo Da dung bot. Task Scheduler se tu khoi dong lai neu duoc cau hinh.
endlocal
