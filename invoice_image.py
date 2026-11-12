"""Vẽ hoá đơn PDF theo layout AlphaWash FE + QR VietQR (Napas)."""
import io
import logging
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config
from utils import money

log = logging.getLogger("invoice-image")

W = 1240              # A4 width @ 150 DPI
M = 90                # lề trái/phải
INK = (17, 24, 39)
MUTED = (107, 114, 128)
LINE = (209, 213, 219)
BAND = (243, 244, 246)
WHITE = (255, 255, 255)
BOX_BG = (243, 244, 246)


@lru_cache(maxsize=None)
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "BeVietnamPro-Bold.ttf" if bold else "BeVietnamPro-Regular.ttf"
    candidates = [
        config.FONT_DIR / name,
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise FileNotFoundError(f"Không tìm thấy font. Hãy đặt {name} vào thư mục fonts/")


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
        cur = ""
        for word in paragraph.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _dashed(d: ImageDraw.ImageDraw, x0: int, x1: int, y: int, color=LINE, dash: int = 8) -> None:
    x = x0
    while x < x1:
        d.line([x, y, min(x + dash, x1), y], fill=color, width=2)
        x += dash * 2


def _fetch_vietqr(amount: int, add_info: str) -> Image.Image | None:
    """Tải ảnh VietQR (có sẵn logo VIETQR + napas 247 + tên NH + STK + tên chủ TK + số tiền)."""
    bank = (config.get_business().get("bank") or {})
    short = bank.get("short_name") or bank.get("bin")
    account = bank.get("account")
    if not short or not account:
        return None
    params = urllib.parse.urlencode({
        "amount": str(int(amount)),
        "addInfo": add_info,
        "accountName": bank.get("account_name") or "",
    })
    template = bank.get("template") or "compact2"
    url = f"https://img.vietqr.io/image/{short}-{account}-{template}.png?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shine-invoice-bot"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGBA")
    except Exception as e:  # noqa: BLE001
        log.warning("Không tải được QR VietQR: %s", e)
        return None


def render_invoice(inv: dict) -> Path:
    """inv: dict từ orders.order_to_invoice(). Trả về đường dẫn file PDF."""
    biz = config.get_business()
    accent = _hex(biz.get("accent_color", "#B91C1C"))

    f_meta = _font(False, 22)                # dòng "Mã HĐ" / "In lúc"
    f_biz_name = _font(True, 34)             # tên xưởng
    f_biz = _font(False, 22)                 # địa chỉ, SĐT
    f_title = _font(True, 48)                # HÓA ĐƠN DỊCH VỤ
    f_lbl = _font(True, 24)                  # label bold: "Khách hàng:", ...
    f_val = _font(False, 24)                 # value regular
    f_car_hdr = _font(True, 26)              # header xe
    f_thead = _font(True, 22)                # header bảng dịch vụ
    f_row = _font(False, 22)                 # row dịch vụ
    f_sum = _font(False, 24)                 # tạm tính
    f_total = _font(True, 34)                # TỔNG THANH TOÁN
    f_pay_lbl = _font(True, 24)
    f_pay_val = _font(True, 24)
    f_qr_hdr = _font(True, 26)               # "Quét mã QR để thanh toán"
    f_footer = _font(True, 24)

    # Tạo canvas cao dư, crop sau
    est_h = 2600 + 60 * len(inv["items"])
    img = Image.new("RGB", (W, est_h), WHITE)
    d = ImageDraw.Draw(img)

    # ---- Header meta: Mã HĐ | In lúc ----
    y = 60
    d.text((M, y), f"Mã HĐ: {inv['number']}", font=f_meta, fill=INK)
    ca = inv["created_at"]
    printed = f"In lúc: {ca.strftime('%H:%M:%S')} {ca.day}/{ca.month}/{ca.year}"
    d.text((W - M, y), printed, font=f_meta, fill=MUTED, anchor="ra")
    y += 60

    # ---- Logo + business info ----
    logo_h = 0
    text_x = M
    if config.LOGO_PATH.exists():
        logo = Image.open(config.LOGO_PATH).convert("RGBA")
        logo_h = 130
        lw = int(logo.width * logo_h / logo.height)
        logo = logo.resize((lw, logo_h))
        img.paste(logo, (M, y), logo)
        text_x = M + lw + 32
    d.text((text_x, y), biz["name"], font=f_biz_name, fill=INK)
    ty = y + 50
    for line in _wrap(d, biz.get("address", ""), f_biz, W - text_x - M):
        d.text((text_x, ty), line, font=f_biz, fill=INK)
        ty += 30
    if biz.get("hotline"):
        d.text((text_x, ty), f"SĐT: {biz['hotline']}", font=f_biz, fill=INK)
        ty += 30
    y = max(ty, y + logo_h) + 26

    # ---- Đường kẻ ngang ----
    d.line([M, y, W - M, y], fill=LINE, width=2)
    y += 40

    # ---- Tiêu đề ----
    d.text((W / 2, y), biz.get("invoice_title", "HÓA ĐƠN DỊCH VỤ"), font=f_title, fill=INK, anchor="ma")
    y += 80

    # ---- Info grid 2 cột ----
    col1_x = M
    col2_x = M + (W - 2 * M) // 2 + 20
    row_h = 42

    def info_pair(label: str, value: str, x: int, cy: int) -> None:
        d.text((x, cy), label, font=f_lbl, fill=INK)
        lbl_w = d.textlength(label + " ", font=f_lbl)
        d.text((x + lbl_w, cy), value, font=f_val, fill=INK)

    ci = inv.get("check_in") or ""
    co = inv.get("check_out") or ""
    kt = ", ".join(inv.get("employees") or []) or "Chưa có"
    info_pair("Khách hàng:", inv.get("customer") or "Khách lẻ", col1_x, y)
    info_pair("Ngày:", f"{inv['created_at'].day}/{inv['created_at'].month}/{inv['created_at'].year}", col2_x, y)
    y += row_h
    info_pair("Kỹ thuật:", kt, col1_x, y)
    info_pair("Giờ vào:", str(ci), col2_x, y)
    y += row_h
    info_pair("Số xe:", "1 xe", col1_x, y)
    info_pair("Giờ ra:", str(co), col2_x, y)
    y += row_h + 30

    # ---- Bảng dịch vụ (khung + hàng) ----
    veh_head = f"🚗 Xe #1: {inv.get('vehicle') or 'Xe'} - {inv['plate']}"
    if inv.get("size"):
        veh_head += f"  (Size: {inv['size']})"
    # box header xe
    box_x0, box_x1 = M, W - M
    hdr_h = 60
    d.rounded_rectangle([box_x0, y, box_x1, y + hdr_h], radius=8, fill=BOX_BG, outline=LINE, width=1)
    d.text((box_x0 + 20, y + hdr_h // 2), veh_head, font=f_car_hdr, fill=INK, anchor="lm")
    y += hdr_h

    # bảng dịch vụ: cột "Dịch vụ" | "Loại xe" | "Giá"
    col_price_x = box_x1 - 20                       # right edge cho Giá
    col_size_x = box_x1 - 240                       # right edge cho Loại xe
    col_svc_x = box_x0 + 20                         # left edge cho Dịch vụ
    col_svc_w = col_size_x - 40 - col_svc_x

    thead_h = 48
    d.rectangle([box_x0, y, box_x1, y + thead_h], fill=WHITE, outline=LINE, width=1)
    d.text((col_svc_x, y + thead_h // 2), "Dịch vụ", font=f_thead, fill=INK, anchor="lm")
    d.text((col_size_x - 20, y + thead_h // 2), "Loại xe", font=f_thead, fill=INK, anchor="lm")
    d.text((col_price_x, y + thead_h // 2), "Giá", font=f_thead, fill=INK, anchor="rm")
    y += thead_h

    size_txt = inv.get("size") or ""
    for item in inv["items"]:
        lines = _wrap(d, item["name"], f_row, col_svc_w)
        rh = max(52, len(lines) * 30 + 22)
        d.rectangle([box_x0, y, box_x1, y + rh], fill=WHITE, outline=LINE, width=1)
        for i, ln in enumerate(lines):
            d.text((col_svc_x, y + 14 + i * 30), ln, font=f_row, fill=INK)
        d.text((col_size_x - 20, y + rh // 2), size_txt, font=f_row, fill=INK, anchor="lm")
        d.text((col_price_x, y + rh // 2), money(item["price"]), font=f_row, fill=INK, anchor="rm")
        y += rh
    y += 24

    # ---- Tổng cộng ----
    d.text((M, y), "Tạm tính:", font=f_sum, fill=INK)
    d.text((W - M, y), money(inv["subtotal"]), font=f_sum, fill=INK, anchor="ra")
    y += 40
    if inv.get("discount"):
        d.text((M, y), "Giảm giá:", font=f_sum, fill=INK)
        d.text((W - M, y), "-" + money(inv["discount"]), font=f_sum, fill=accent, anchor="ra")
        y += 40
    _dashed(d, M, W - M, y + 6)
    y += 28

    d.text((M, y), "TỔNG THANH TOÁN:", font=f_total, fill=INK)
    d.text((W - M, y), money(inv["total"]), font=f_total, fill=INK, anchor="ra")
    y += 60

    d.text((M, y), "Thanh toán:", font=f_pay_lbl, fill=INK)
    d.text((W - M, y), inv.get("payment_type") or inv.get("payment", ""), font=f_pay_val, fill=INK, anchor="ra")
    y += 40
    _dashed(d, M, W - M, y + 6)
    y += 40

    # ---- QR VietQR (luôn hiển thị khi có số tiền > 0) ----
    if inv["total"] > 0:
        d.text((W / 2, y), "Quét mã QR để thanh toán", font=f_qr_hdr, fill=INK, anchor="ma")
        y += 50
        add_info = f"Thanh toan {inv['number']}"
        qr = _fetch_vietqr(inv["total"], add_info)
        if qr is not None:
            # Resize QR image giữ nguyên tỉ lệ, rộng 520px
            qw = 520
            qh = int(qr.height * qw / qr.width)
            qr_r = qr.resize((qw, qh))
            qx = (W - qw) // 2
            img.paste(qr_r, (qx, y), qr_r)
            y += qh + 20
        else:
            # fallback: chỉ in STK
            bank = biz.get("bank") or {}
            d.text((W / 2, y), f"Techcombank · {bank.get('account', '')}", font=f_lbl, fill=INK, anchor="ma")
            y += 34
            d.text((W / 2, y), bank.get("account_name", ""), font=f_val, fill=INK, anchor="ma")
            y += 40
            d.text((W / 2, y), f"Số tiền: {money(inv['total'])}", font=f_val, fill=INK, anchor="ma")
            y += 40

    # ---- Footer ----
    y += 30
    for line in (biz.get("footer_text") or "").splitlines():
        d.text((W / 2, y), line.strip(), font=f_footer, fill=INK, anchor="ma")
        y += 40
    y += 40

    # ---- Xuất PDF ----
    out = img.crop((0, 0, W, min(y, est_h)))
    config.INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", str(inv["number"]) or "invoice")
    path = config.INVOICE_DIR / f"{safe}.pdf"
    out.save(path, "PDF", resolution=150.0)
    return path
