# =====================================================================
#  Cai dat Task Scheduler chay bot 24/7 tren Windows.
#  Chay: nhap chuot phai file nay -> "Run with PowerShell" (as Admin).
#  Hoac terminal:  powershell -ExecutionPolicy Bypass -File install-task.ps1
# =====================================================================

$ErrorActionPreference = "Stop"

# Xac nhan chay voi quyen Admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Can chay PowerShell voi quyen Administrator." -ForegroundColor Red
    Write-Host "Nhap chuot phai file .ps1 -> Run with PowerShell (as Admin)."
    Read-Host "Bam Enter de thoat"
    exit 1
}

$TaskName = "ShineInvoiceBot"
$BotDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath  = Join-Path $BotDir "run-bot.bat"

if (-not (Test-Path $BatPath)) {
    Write-Host "Khong tim thay $BatPath" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $BotDir ".venv\Scripts\python.exe"))) {
    Write-Host "Khong tim thay .venv. Chay truoc:" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $BotDir ".env"))) {
    Write-Host "Chua co file .env. Copy .env.example -> .env va dien BOT_TOKEN, API_*." -ForegroundColor Yellow
    Write-Host "(Van tiep tuc cai task, nhung bot se loi luc chay neu chua co .env)"
}

# Xoa task cu neu co
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Xoa task cu '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Task: chay run-bot.bat khi may boot, khong can login, an cua so console
$action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $BotDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)  # 0 = khong gioi han

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Shine Autowerkz Invoice Bot - Telegram bot chay 24/7" | Out-Null

Write-Host ""
Write-Host "Da cai xong task '$TaskName'." -ForegroundColor Green
Write-Host "Bot se tu chay moi khi may boot, va tu restart moi 1 phut neu crash."
Write-Host ""

$answer = Read-Host "Khoi dong bot ngay bay gio? (y/n)"
if ($answer -eq "y" -or $answer -eq "Y") {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Da khoi dong bot. Xem log tai:" -ForegroundColor Green
    Write-Host "  $BotDir\logs\"
}
Write-Host ""
Write-Host "Cac lenh huu ich (chay tu PowerShell Admin):"
Write-Host "  Start-ScheduledTask   -TaskName $TaskName   # bat"
Write-Host "  Stop-ScheduledTask    -TaskName $TaskName   # tat"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName   # trang thai"
Write-Host "  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false   # go bo"
