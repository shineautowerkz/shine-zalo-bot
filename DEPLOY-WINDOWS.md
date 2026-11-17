# Deploy bot lên máy xưởng (Windows)

Bot chạy nền 24/7 qua **Task Scheduler**, tự khởi động khi máy bật, tự restart nếu crash.
Không cần domain, không cần mở cổng.

## Yêu cầu máy

- Windows 10 / 11
- Python 3.10+ (dùng 3.13 đang có sẵn cũng OK)
- Internet 24/7
- Máy **không tự tắt / sleep** (Settings → System → Power → Screen and sleep → Never)
- Khuyến nghị **UPS** phòng mất điện đột ngột

## Bước 1 — Chuẩn bị code + `.env`

Mở PowerShell trong thư mục bot (chuột phải trong Explorer → *Open in Terminal*):

```powershell
# Tao venv (chi lam 1 lan)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Tao .env
copy .env.example .env
notepad .env
```

Trong `.env` điền:
- `BOT_TOKEN` — lấy từ [@BotFather](https://t.me/BotFather) → `/newbot`
- `API_BASE_URL` — URL AlphaWash production (không phải staging)
- `API_USERNAME` / `API_PASSWORD` — tài khoản **riêng cho bot** trên AlphaWash (đừng dùng tài khoản admin)
- `ADMIN_USER_IDS` / `STAFF_USER_IDS` — Telegram ID của bạn + nhân viên
  - Cách lấy ID: chạy bot lần đầu (`.venv\Scripts\python bot.py`), nhắn `/myid` cho bot, copy số vào `.env`

## Bước 2 — Chạy thử 1 lần

```powershell
.venv\Scripts\python bot.py
```

Vào Telegram nhắn `/start` cho bot → xem có phản hồi không. Nếu OK, `Ctrl+C` để dừng.

## Bước 3 — Cài Task Scheduler (chạy 1 lần)

Chuột phải file `install-task.ps1` → **Run with PowerShell** (chọn *Yes* khi UAC hỏi quyền Admin).

Script sẽ:
- Tạo task tên `ShineInvoiceBot`
- Chạy `run-bot.bat` khi máy boot (không cần user login)
- Tự restart mỗi phút nếu bot crash
- Chạy dưới quyền `SYSTEM` (không lệ thuộc user cụ thể)
- Hỏi có khởi động ngay không (chọn `y`)

**Kiểm tra bot đã chạy:** vào Telegram nhắn `/start` — có phản hồi = OK.

## Vận hành hằng ngày

### Xem log
```powershell
# Log hom nay
Get-Content logs\bot-$(Get-Date -Format 'yyyy-MM-dd').log -Tail 50

# Theo doi log real-time
Get-Content logs\bot-$(Get-Date -Format 'yyyy-MM-dd').log -Wait -Tail 20
```

### Restart bot (sau khi update code)
```powershell
# Cach 1: chay stop-bot.bat -> Task Scheduler tu bat lai sau ~1 phut
.\stop-bot.bat

# Cach 2 (nhanh hon, chay PowerShell Admin):
Stop-ScheduledTask  -TaskName ShineInvoiceBot
Start-ScheduledTask -TaskName ShineInvoiceBot
```

### Kiểm tra trạng thái task
```powershell
Get-ScheduledTaskInfo -TaskName ShineInvoiceBot
```
Xem cột `LastTaskResult` — `0` = OK, khác 0 = có lỗi.

### Update code (fix bug, đổi business.json, ...)

```powershell
# 1. Dung bot
.\stop-bot.bat

# 2. Update file (git pull hoac copy file moi)
git pull   # hoac chi don gian la copy file moi vao

# 3. Neu doi requirements.txt thi cai lai deps
.venv\Scripts\pip install -r requirements.txt

# 4. Bot tu khoi dong lai trong 1 phut, hoac force ngay:
Start-ScheduledTask -TaskName ShineInvoiceBot
```

### Đổi Telegram ID nhân viên (thêm/bớt)

Sửa `.env`, dòng `STAFF_USER_IDS` / `ADMIN_USER_IDS`, rồi restart bot.

### Xem doanh thu hôm nay
Từ Telegram (tài khoản admin): `/homnay`

## Troubleshooting

### Bot không phản hồi trong Telegram
1. Kiểm tra task còn chạy: `Get-ScheduledTaskInfo -TaskName ShineInvoiceBot`
   - `State` phải là `Running`
2. Xem log: `Get-Content logs\bot-*.log -Tail 30`
   - Thường gặp: sai `BOT_TOKEN`, không kết nối được AlphaWash, sai username/password bot

### Log báo "AlphaWash không trả token đăng nhập"
- Kiểm tra `API_USERNAME` / `API_PASSWORD` trong `.env`
- Test thủ công:
  ```powershell
  curl.exe -X POST "$env:API_BASE_URL/api/auth/login" -H "Content-Type: application/json" -d '{"username":"...","password":"..."}'
  ```

### Bot chạy trùng (2 instance) → Telegram báo `Conflict: terminated by other getUpdates request`
- Có thể có 1 instance cũ còn chạy. Chạy `stop-bot.bat` rồi start lại từ Task Scheduler.
- Không bao giờ chạy `python bot.py` thủ công khi task đang chạy.

### Máy đang online nhưng task chưa khởi động
- Mở **Task Scheduler** (gõ `taskschd.msc`) → tab *Task Scheduler Library* → tìm `ShineInvoiceBot`
- Chuột phải → **Run** (chạy thủ công 1 lần để test)
- Nếu vẫn không được, xem *History* tab để đọc lỗi.

### Máy sleep khiến bot chết
Vào **Settings → System → Power → Screen and sleep**:
- *Screen off*: tuỳ ý
- *Sleep*: **Never** (khi cắm điện)

Hoặc chạy PowerShell (Admin):
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

### Log tiếng Việt bị "?" hoặc ký tự lạ
`run-bot.bat` đã set `PYTHONIOENCODING=utf-8` — mở log bằng **VS Code** hoặc **Notepad++** (Notepad thường của Windows có thể hiển thị sai).

### Cần xoá log cũ định kỳ
File log trong `logs\` tăng dần theo ngày. Xoá bằng:
```powershell
# Xoa log qua 30 ngay
Get-ChildItem logs\bot-*.log | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item
```

## Gỡ bot hoàn toàn

```powershell
# Chay PowerShell Admin
Unregister-ScheduledTask -TaskName ShineInvoiceBot -Confirm:$false
```

Xoá thư mục `E:\ShineAutowerkz\Software\shine-invoice-bot` nếu muốn.

## Backup / khôi phục

Bot **không có DB nội bộ** — mọi dữ liệu nghiệp vụ nằm ở AlphaWash. Backup chỉ cần:
- `.env` (chứa token + credentials — cất riêng, cẩn thận)
- `business.json` (thông tin xưởng)
- `api_mapping.json` (mapping enum BE)
- `assets/logo.png` (nếu có logo)
- `fonts/` (font Be Vietnam Pro)

Không cần backup `data/invoices/` (PDF tự sinh lại được bằng `/in <mã>`) hay `logs/`.
