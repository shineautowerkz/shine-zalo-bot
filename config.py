"""Cấu hình chung: đọc .env, thông tin xưởng, mapping với API AlphaWash."""
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

API_BASE_URL = os.getenv("API_BASE_URL", "").strip().rstrip("/")
API_USERNAME = os.getenv("API_USERNAME", "").strip()
API_PASSWORD = os.getenv("API_PASSWORD", "")
API_TIMEOUT = float(os.getenv("API_TIMEOUT", "20"))


def _ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}


# ADMIN: chủ xưởng/quản lý - xem doanh thu (/homnay). STAFF: nhân viên tạo phiếu.
ADMIN_USER_IDS = _ids("ADMIN_USER_IDS")
STAFF_USER_IDS = _ids("STAFF_USER_IDS") | ADMIN_USER_IDS

DATA_DIR = BASE_DIR / "data"
INVOICE_DIR = DATA_DIR / "invoices"      # ảnh phiếu đã vẽ (bản lưu tạm, có thể xoá)
FONT_DIR = BASE_DIR / "fonts"
LOGO_PATH = BASE_DIR / "assets" / "logo.png"


def _load_json(name: str) -> dict:
    return json.loads((BASE_DIR / name).read_text(encoding="utf-8"))


def get_business() -> dict:
    return _load_json("business.json")


def get_mapping() -> dict:
    """api_mapping.json: giá trị paymentType/status, cách tính totalPrice... (đọc lại mỗi lần)."""
    return _load_json("api_mapping.json")
