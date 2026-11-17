# Bot Telegram tạo phiếu thanh toán — Shine Autowerkz (nối API AlphaWash)

Nhân viên bấm nút trong Telegram → bot tạo đơn trong AlphaWash qua API → vẽ **ảnh phiếu** (PNG) từ chính
dữ liệu BE trả về. Khi bật endpoint PDF của AlphaWash, bot gửi **file PDF hoá đơn (có mã QR)** do chính BE tạo;
chưa bật thì gửi ảnh tự vẽ (không có QR). Bot **không lưu dữ liệu nghiệp vụ**; mã phiếu là `code` do BE cấp.

## 1. Chuẩn bị

1. **Bot Telegram:** chat với **@BotFather** → `/newbot` → lấy token.
2. **Tài khoản riêng cho bot trên AlphaWash** (quyền tối thiểu, không dùng tài khoản admin). Bot cần: tạo đơn
   (`POST /api/orders/create-order`), đọc đơn, xe, dịch vụ (quick-invoice), hãng/dòng xe, nhân viên, khách.
   Lưu ý `GET /api/employee/` trả cả CCCD/STK ngân hàng: bot chỉ giữ `id` + `name`, không ghi log.
3. Nhân viên chat **riêng** với bot (trong group bot chỉ thấy lệnh, không thấy biển số/ghi chú gõ vào).

## 2. Cài đặt (Python 3.10+)

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # Linux/Mac: cp .env.example .env
```

Điền `.env`: `BOT_TOKEN`, `API_BASE_URL` (dùng **https**), `API_USERNAME`, `API_PASSWORD`.
Chạy `python bot.py`, nhắn `/myid` cho bot để lấy Telegram ID rồi điền `ADMIN_USER_IDS` / `STAFF_USER_IDS`, chạy lại.

## 3. Cách dùng

| Lệnh | Ai | Việc |
|---|---|---|
| `/hoadon` | nhân viên | Chọn xe gần đây hoặc gõ biển số → (xe mới: gõ tên dòng xe) → chọn dịch vụ theo size xe → sửa giá nếu cần → chọn thợ → giảm giá → thanh toán → ghi chú → xác nhận |
| `/lichsu 51A-12345` | nhân viên | 5 phiếu gần nhất của biển số (xe phải đã gắn khách) |
| `/in ORD-2026-000123` | nhân viên | Gửi lại PDF (hoặc ảnh nếu chưa bật PDF) của phiếu theo mã |
| `/homnay` | quản lý | Số phiếu + doanh thu hôm nay (từ `/api/dashboard`) |
| `/huy` | nhân viên | Huỷ phiếu đang tạo |

- Giá dịch vụ lấy từ AlphaWash theo **size** của xe (S/M/L/XL) qua `serviceCatalogCode`. Sửa giá trong bot
  = `adjustedPrice` + lý do (giá 0 = tặng kèm). Không còn mục dịch vụ gõ tay vì BE chỉ nhận dịch vụ có trong catalog.
- Xe mới: chỉ cần hãng/dòng (BE tự tạo xe từ biển số + brand + model). Khách sẽ được gắn sau (AutoLink).
- Biển số được chuẩn hoá về dạng `51A-12345` (bỏ dấu chấm) như ví dụ của BE.
- Tên nhân viên lập phiếu được ghi vào `note` của đơn (dòng bắt đầu `[Bot]`), phiếu in ra hiển thị ở "Người lập phiếu".

## 4. `api_mapping.json` — kiểm tra trước khi dùng thật

| Khoá | Trạng thái | Cần làm |
|---|---|---|
| `CASH` / `PAID` / `COMPLETED` | Lấy từ ví dụ của BE | — |
| `TRANSFER`, `CARD`, `UNPAID` | **ĐOÁN** | Đối chiếu với `OrderServiceImpl`, sửa trong file |
| `total_price_mode` | **ĐOÁN**: `gross` | Ví dụ BE: `totalPrice` = tổng dịch vụ + sản phẩm (chưa trừ `discount`). Nếu BE lưu sau giảm giá thì đổi thành `net` |
| `invoice_pdf.path` | **CHƯA BẬT** (rỗng) | Điền path endpoint PDF của BE, dùng `{id}` (UUID) hoặc `{code}`, VD `/api/orders/{id}/pdf`. Bot tự nhận PDF trực tiếp, base64 trong JSON, hoặc link tải. Có PDF thì bot chỉ gửi PDF |
| `dashboard_date_format` | ĐOÁN `%Y-%m-%d` | Đối chiếu kiểu `startDate` của `/api/dashboard` |

Bot gửi `tip = 0`, `vat = 0`, `checkInTime/checkOutTime = null`. Nếu BE bắt buộc các trường này, bạn sẽ thấy lỗi
"AlphaWash từ chối: ..." ngay lúc xuất phiếu (bot giữ nguyên phiếu để bạn thử lại).

**Thử trên staging trước:** tạo 1 phiếu bằng bot, mở đơn đó trong AlphaWash và đối chiếu tổng tiền, hình thức thanh
toán, thợ, giảm giá với ảnh bot xuất ra. Phiếu in lại (`/in`) của đơn có VAT hoặc tip sẽ chưa hiển thị hai khoản này.

## 5. Khi lỗi

- BE từ chối (4xx): bot báo lý do và giữ nguyên phiếu để sửa/thử lại.
- Timeout hoặc 5xx lúc tạo đơn: bot **không tự tạo lại** (tránh trùng phiếu), báo nhân viên kiểm tra trong AlphaWash trước.
- Token hết hạn: bot tự đăng nhập lại một lần.
- Lấy PDF lỗi (hoặc chưa bật): phiếu vẫn được tạo, bot gửi ảnh tự vẽ kèm cảnh báo **"KHÔNG có mã QR"** — đừng gửi ảnh này cho khách nếu cần QR; dùng `/in <mã>` để lấy lại PDF sau.
- Bot chỉ gửi token đăng nhập tới đúng máy chủ AlphaWash; link tải PDF ở máy chủ khác được tải không kèm token.

## 6. Chạy 24/7

- **Máy xưởng (Windows):** Task Scheduler chạy `.venv\Scripts\python.exe bot.py` khi khởi động.
- **VPS (Linux):** systemd, `Restart=always`. Bot dùng polling, không cần domain hay mở cổng.
- Đổi từ staging sang production: chỉ đổi `API_BASE_URL` (và tài khoản bot) trong `.env`.

## 7. Tuỳ chỉnh

`business.json` (thông tin xưởng, tiêu đề, màu, STK hiển thị khi chuyển khoản), `assets/logo.png` (logo, tuỳ chọn),
font Be Vietnam Pro (OFL) trong `fonts/`. Đây là **phiếu thanh toán nội bộ**, không thay thế hoá đơn điện tử VAT.
