"""Hàm tiện ích: định dạng/parse tiền, biển số, ngày giờ."""
import re
import unicodedata
from datetime import datetime

import config


def money(n: int) -> str:
    """1500000 -> '1.500.000đ'"""
    return f"{int(n):,}".replace(",", ".") + "đ"


_UNIT = {"k": 1_000, "nghìn": 1_000, "nghin": 1_000, "ngàn": 1_000,
         "tr": 1_000_000, "triệu": 1_000_000, "trieu": 1_000_000}


def parse_money(text: str, allow_zero: bool = False) -> int | None:
    """Hiểu: 300k, 1.5tr, 1,5 triệu, 1500000, 1.500.000, 300.000đ. Sai -> None."""
    s = text.strip().lower()
    for junk in ("vnđ", "vnd", "đ", "₫"):
        s = s.replace(junk, "")
    s = s.replace(" ", "")
    if not s:
        return None

    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(nghìn|nghin|ngàn|triệu|trieu|tr|k)", s)
    if m:
        value = int(round(float(m.group(1).replace(",", ".")) * _UNIT[m.group(2)]))
        return value if value > 0 or allow_zero else None

    digits = s.replace(".", "").replace(",", "")
    if digits.isdigit():
        value = int(digits)
        return value if value > 0 or allow_zero else None
    return None


def parse_discount(text: str, subtotal: int) -> int | None:
    """'10%' -> 10% của tạm tính; '200k' -> 200000. Không vượt quá tạm tính. Sai -> None."""
    s = text.strip().replace(" ", "")
    if s.endswith("%"):
        try:
            pct = float(s[:-1].replace(",", "."))
        except ValueError:
            return None
        if not 0 < pct <= 100:
            return None
        return int(subtotal * pct / 100)
    amount = parse_money(s)
    if amount is None:
        return None
    return min(amount, subtotal)


def canonical_plate(text: str) -> str | None:
    """'51k-123.45' / '51A12345' -> '51K-12345' (dạng như ví dụ của BE). Không hợp lệ -> None."""
    s = re.sub(r"[\s.]", "", text.upper())
    if not re.fullmatch(r"[0-9A-Z][0-9A-Z\-]{3,14}", s):
        return None
    m = re.fullmatch(r"(\d{2}[A-Z]{1,2}\d??)-?(\d{4,5})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else s


def plate_key(text: str) -> str:
    """Dạng so khớp: bỏ dấu . - và khoảng trắng."""
    return re.sub(r"[.\-\s]", "", text.upper())


def fold(text: str) -> str:
    """Bỏ dấu tiếng Việt + lowercase, để tìm kiếm."""
    s = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def parse_dt(value: str | None) -> datetime:
    """ISO từ BE ('2026-09-18T09:30:00.000+07:00' hoặc không có offset) -> datetime giờ VN."""
    if not value:
        return datetime.now(config.TZ)
    s = value.strip().replace("Z", "+00:00")
    s = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(config.TZ)
    return dt.replace(tzinfo=config.TZ) if dt.tzinfo is None else dt.astimezone(config.TZ)
