"""Vẽ BẢNG BÁO GIÁ DỊCH VỤ (PNG + PDF) theo mẫu Shine Autowerkz."""
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

W, H = 1240, 1754            # A4 @ 150 DPI
ML, MR = 128, 1112           # lề trái / phải của bảng
INK = (0, 0, 0)
WHITE = (255, 255, 255)
LABEL_BG = (230, 230, 230)
TOTAL_BG = (170, 167, 167)
GOLD = (176, 141, 66)

QUOTE_DIR = config.DATA_DIR / "quotes"
TEMPLATES_PATH = config.BASE_DIR / "quote_templates.json"

# Font có chân giống mẫu (Times New Roman trên Windows); thiếu thì lùi về font của hoá đơn
_FONTS = {
    "r": ["C:/Windows/Fonts/times.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"],
    "b": ["C:/Windows/Fonts/timesbd.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"],
    "i": ["C:/Windows/Fonts/timesi.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"],
    "bi": ["C:/Windows/Fonts/timesbi.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf"],
}
_FALLBACK = {"r": "BeVietnamPro-Regular.ttf", "b": "BeVietnamPro-Bold.ttf",
             "i": "BeVietnamPro-Regular.ttf", "bi": "BeVietnamPro-Bold.ttf"}


@lru_cache(maxsize=None)
def font(style: str, size: int) -> ImageFont.FreeTypeFont:
    for p in _FONTS[style] + [str(config.FONT_DIR / _FALLBACK[style])]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise FileNotFoundError("Không tìm thấy font Times New Roman hoặc font trong thư mục fonts/")


def load_templates() -> dict:
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))


def vnd(n: int) -> str:
    return f"{int(n):,}".replace(",", ".") + " VND"


# ---------- Chữ xuống dòng ----------
def wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in str(text).split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines or [""]


def rich_lines(d, segments: list[tuple[str, object]], max_w: int) -> list[list[tuple[str, object]]]:
    """segments: [(text, font)] -> các dòng, mỗi dòng là [(text, font)] (giữ đậm/nghiêng giữa câu)."""
    words = []
    for text, f in segments:
        for w in re.findall(r"\S+\s*", text):
            words.append((w, f))
    lines, cur, cur_w = [], [], 0.0
    for w, f in words:
        ww = d.textlength(w, font=f)
        if cur and cur_w + d.textlength(w.rstrip(), font=f) > max_w:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((w, f))
        cur_w += ww
    if cur:
        lines.append(cur)
    return lines


def draw_rich(d, x: float, y: float, line) -> None:
    for text, f in line:
        d.text((x, y), text, font=f, fill=INK)
        x += d.textlength(text, font=f)


def _parse_bold(text: str, f_norm, f_bold):
    parts = text.split("**")
    return [(p, f_bold if i % 2 else f_norm) for i, p in enumerate(parts) if p]


# ---------- Vẽ ----------
def render_quote(q: dict) -> tuple[Path, Path]:
    """q = {customer, phone, date (dd/mm/yyyy), car, size, template (dict), prices [int]} -> (png, pdf)."""
    data = load_templates()
    tpl = q["template"]
    opts = tpl["options"]
    n = len(opts)

    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # --- Tiêu đề + logo + công ty ---
    d.text((490, 92), "BẢNG BÁO GIÁ DỊCH VỤ", font=font("b", 44), fill=INK, anchor="mm")

    cx = 925
    logo_bottom = 40
    if config.LOGO_PATH.exists():
        logo = Image.open(config.LOGO_PATH).convert("RGBA")
        logo.thumbnail((170, 115))
        img.paste(logo, (int(cx - logo.width / 2), 40), logo)
        logo_bottom = 40 + logo.height
    else:
        d.text((cx, 100), "SHINE.AUTOWERKZ", font=font("bi", 20), fill=GOLD, anchor="mm")
        logo_bottom = 120
    comp = data["company"]
    y = logo_bottom + 22
    d.text((cx, y), comp["name"], font=font("b", 18), fill=INK, anchor="mm")
    for line in comp["lines"]:
        y += 19
        d.text((cx, y), line, font=font("r", 13), fill=INK, anchor="mm")

    # --- Thông tin khách ---
    f_info = font("b", 22)
    info = [("KHÁCH HÀNG", q.get("customer") or ""), ("SỐ ĐIỆN THOẠI", q.get("phone") or ""),
            ("NGÀY:", q["date"]), ("DÒNG XE:", q.get("car") or ""), ("KÍCH CỠ:", q.get("size") or "")]
    y = 160
    for label, value in info:
        d.text((131, y), label, font=f_info, fill=INK, anchor="lm")
        d.text((346, y), f": {value}", font=f_info, fill=INK, anchor="lm")
        y += 34.5

    # --- Tiêu đề mục ---
    sec = f"I. DỊCH VỤ: {tpl['title'].upper()}"
    if n > 1:
        sec += f" (QUÝ KHÁCH CHỌN 1 TRONG {n} OPTION)"
    f_sec = font("b", 23)
    sec_lines = wrap(d, sec, f_sec, MR - ML)
    y = 340
    for ln in sec_lines:
        d.text((ML, y), ln, font=f_sec, fill=INK, anchor="lm")
        y += 30
    y += 4

    # --- Bảng ---
    label_w = 254
    col_w = (MR - ML - label_w) / n
    cols = [ML + label_w + i * col_w for i in range(n + 1)]
    f_cell = font("b", 19)
    pad = 12

    def cell_text_center(x0, x1, y0, h, text, f, fill=INK):
        lines = wrap(d, text, f, x1 - x0 - 2 * pad)
        lh = f.size + 6
        ty = y0 + (h - lh * len(lines)) / 2 + lh / 2
        for ln in lines:
            d.text(((x0 + x1) / 2, ty), ln, font=f, fill=fill, anchor="mm")
            ty += lh

    def row_height(texts, f, base=46):
        lh = f.size + 6
        need = max(len(wrap(d, t, f, col_w - 2 * pad)) for t in texts)
        return max(base, need * lh + 18)

    # Header
    hh = 54
    d.rectangle([ML, y, MR, y + hh], fill=INK)
    cell_text_center(ML, cols[0], y, hh, "HẠNG MỤC", font("b", 20), WHITE)
    for i, o in enumerate(opts):
        cell_text_center(cols[i], cols[i + 1], y, hh, o["name"], font("b", 20), WHITE)
    y += hh
    table_top = y

    for label in tpl["rows"]:
        vals = [o["values"].get(label, "–") for o in opts]
        if any(isinstance(v, list) for v in vals):
            # Hàng danh sách đánh số (VD quà tặng): mỗi mục 1 dòng con
            lists = [v if isinstance(v, list) else [v] for v in vals]
            k = max(len(v) for v in lists)
            sub_h = []
            for j in range(k):
                texts = [f"{j + 1}.   {v[j]}" if j < len(v) else "" for v in lists]
                sub_h.append(row_height(texts, f_cell))
            total_h = sum(sub_h)
            d.rectangle([ML, y, cols[0], y + total_h], fill=LABEL_BG, outline=INK, width=1)
            cell_text_center(ML, cols[0], y, total_h, label, f_cell)
            sy = y
            for j, hgt in enumerate(sub_h):
                for i, v in enumerate(lists):
                    d.rectangle([cols[i], sy, cols[i + 1], sy + hgt], outline=INK, width=1)
                    if j < len(v):
                        lines = wrap(d, v[j], f_cell, col_w - 70 - pad)
                        lh = f_cell.size + 6
                        ty = sy + (hgt - lh * len(lines)) / 2 + lh / 2
                        d.text((cols[i] + 52, ty), f"{j + 1}.", font=f_cell, fill=INK, anchor="rm")
                        for ln in lines:
                            d.text((cols[i] + 68, ty), ln, font=f_cell, fill=INK, anchor="lm")
                            ty += lh
                sy += hgt
            y += total_h
        else:
            h = row_height([str(v) for v in vals], f_cell)
            d.rectangle([ML, y, cols[0], y + h], fill=LABEL_BG, outline=INK, width=1)
            cell_text_center(ML, cols[0], y, h, label, f_cell)
            for i, v in enumerate(vals):
                d.rectangle([cols[i], y, cols[i + 1], y + h], outline=INK, width=1)
                cell_text_center(cols[i], cols[i + 1], y, h, str(v), f_cell)
            y += h

    # Tổng cộng
    th = 58
    d.rectangle([ML, y, MR, y + th], fill=TOTAL_BG)
    for x0, x1 in [(ML, cols[0])] + [(cols[i], cols[i + 1]) for i in range(n)]:
        d.rectangle([x0, y, x1, y + th], outline=INK, width=1)
    f_total = font("b", 21)
    cell_text_center(ML, cols[0], y, th, "TỔNG CỘNG", f_total)
    for i, p in enumerate(q["prices"]):
        cell_text_center(cols[i], cols[i + 1], y, th, vnd(p), f_total)
    y += th
    d.rectangle([ML, table_top - hh, MR, y], outline=INK, width=2)

    # --- Ghi chú ---
    y += 54
    f_i, f_bi = font("i", 18), font("bi", 18)
    for note in data["notes"]:
        text = note["text"].replace("{n}", str(n))
        if "{n}" in note["text"] and n < 2:
            continue
        segs = [(note["label"] + " ", f_bi)] + _parse_bold(text, f_i, f_bi)
        for line in rich_lines(d, segs, MR - ML):
            draw_rich(d, ML, y, line)
            y += 29

    # --- Người phụ trách ---
    y = max(y + 60, 1165)
    sx = 916
    d.text((sx, y), data.get("signer_title", "NGƯỜI PHỤ TRÁCH"), font=font("b", 21), fill=INK, anchor="mm")
    d.text((sx, y + 25), data.get("signer_note", ""), font=font("i", 17), fill=INK, anchor="mm")

    # --- Slogan ---
    slogan = data.get("slogan")
    if slogan:
        sy = max(y + 170, 1365)
        f_s = font("bi", 30)
        d.text((418, sy), slogan, font=f_s, fill=INK, anchor="mm")
        tw = d.textlength(slogan, font=f_s)
        d.line([418 - tw / 2, sy + 18, 418 + tw / 2, sy + 18], fill=INK, width=2)

    # --- Lưu file ---
    QUOTE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w]+", "_", f"{q.get('customer', '')}_{q.get('car', '')}", flags=re.U).strip("_")[:40]
    stamp = datetime.now(config.TZ).strftime("%Y%m%d_%H%M%S")
    base = QUOTE_DIR / f"BaoGia_{stamp}_{safe or 'khach'}"
    png, pdf = base.with_suffix(".png"), base.with_suffix(".pdf")
    img.save(png, "PNG", optimize=True)
    img.save(pdf, "PDF", resolution=150.0)
    return png, pdf
