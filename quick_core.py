"""Logic nhập nhanh hoá đơn dùng chung cho bot Telegram và bot Zalo (không phụ thuộc Telegram)."""
import re
import urllib.parse

import config
import orders
from api import AlphaWashClient, BackendError
from utils import canonical_plate, fold, money

SIZES = ("S", "M", "L", "XL")
_QUICK_PLATE_RE = re.compile(r"\d{2}[A-Z]{1,2}[\-.]?\d{4,5}", re.IGNORECASE)

QUICK_HELP = (
    "Dạng nhập nhanh:\n"
    "  Hãng/Dòng/Biển số      (VD: Mazda/CX-5/60K01968)\n"
    "  <tên dịch vụ 1>\n"
    "  <tên dịch vụ 2>\n"
    "  @Tên thợ"
)


class QuickError(Exception):
    """Lỗi có sẵn câu báo tiếng Việt cho người dùng."""


# ---------- Hàm thuần (chuyển từ bot.py sang) ----------
def _new_draft() -> dict:
    return {"vehicle": None, "groups": [], "lines": [], "emps": [], "emp_sel": [], "discount": 0,
            "payment_key": "", "note": "", "models": [], "recent": [], "adj_index": None}


def _head(d: dict) -> str:
    v = d["vehicle"]
    head = f"🚗 {v['plate']}" + (f" · {v['label']}" if v.get("label") else "")
    if v.get("size"):
        head += f" · size {v['size']}"
    if v.get("customerName"):
        head += f"\n👤 {v['customerName']}"
    return head


def _vehicle_from_check(res: dict, plate: str) -> dict:
    v = res.get("vehicle") or {}
    model = v.get("model") or {}
    brand = v.get("brand") or model.get("brand") or {}
    cust = v.get("customer") or res.get("customer") or {}
    return {"plate": v.get("licensePlate") or plate,
            "label": " ".join(x for x in (brand.get("brandName"), model.get("modelName")) if x),
            "size": str(model.get("size") or "").upper(),
            "brandCode": brand.get("code"), "modelCode": model.get("code"),
            "customerId": cust.get("id"), "customerName": cust.get("customerName")}


def _quick_norm(s: str) -> str:
    """Fold + chuẩn hoá viết tắt phổ biến (lv1 -> level 1)."""
    s = fold(s)
    s = re.sub(r"\blv\s*(\d)", r"level \1", s)
    return s


def _quick_tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _quick_norm(s))


def has_plate(text: str) -> bool:
    return bool(_QUICK_PLATE_RE.search((text or "").upper()))


def _parse_quick(text: str) -> dict | None:
    """Tách text người dùng gõ: dòng có biển số -> xe (kèm brand/model nếu có),
    dòng bắt đầu @ -> thợ, còn lại -> dịch vụ. Không tìm thấy biển số -> None."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    result = {"plate": None, "brand": None, "model": None, "services": [], "employees": []}
    for ln in lines:
        if ln.startswith("@"):
            name = ln[1:].strip()
            if name:
                result["employees"].append(name)
            continue
        if not result["plate"] and _QUICK_PLATE_RE.search(ln.upper()):
            parts = [p.strip() for p in re.split(r"[\/|]", ln) if p.strip()]
            if len(parts) >= 3:
                result["brand"], result["model"], plate_txt = parts[0], parts[1], parts[2]
            else:
                plate_txt = _QUICK_PLATE_RE.search(ln.upper()).group(0)
            result["plate"] = plate_txt
            continue
        result["services"].append(ln)
    return result if result["plate"] else None


def _find_service(groups: list[dict], query: str) -> dict | None:
    q = _quick_tokens(query)
    if not q:
        return None
    for g in groups:
        for s in g["services"]:
            hay = _quick_tokens(s["name"])
            if all(t in hay for t in q):
                return s
    return None


def _find_employee(emps: list[dict], query: str) -> dict | None:
    q = _quick_tokens(query)
    if not q:
        return None
    for e in emps:
        if not e.get("name") or (e.get("workStatus") or "Working") != "Working":
            continue
        if all(t in _quick_tokens(e["name"]) for t in q):
            return e
    return None


def _find_brand_model(brands: list[dict], brand_q: str, model_q: str) -> dict | None:
    b_toks = _quick_tokens(brand_q or "")
    m_toks = _quick_tokens(model_q or "")
    for b in brands:
        if b_toks and not all(t in _quick_tokens(b.get("brandName", "")) for t in b_toks):
            continue
        for m in b.get("models") or []:
            if m_toks and not all(t in _quick_tokens(m.get("modelName", "")) for t in m_toks):
                continue
            return {"brandCode": b.get("code"), "brandName": b.get("brandName"),
                    "modelCode": m.get("code"), "modelName": m.get("modelName"),
                    "size": str(m.get("size") or "").upper()}
    return None


# ---------- Dùng cho bot Zalo ----------
async def build_quick_draft(api: AlphaWashClient, text: str) -> tuple[dict, list[str]]:
    """Tin nhắn nhập nhanh -> (draft, danh sách tên thợ không tìm thấy). Lỗi -> QuickError."""
    parsed = _parse_quick(text)
    if not parsed:
        raise QuickError("Mình chưa nhận ra biển số trong tin nhắn.\n\n" + QUICK_HELP)
    plate = canonical_plate(parsed["plate"])
    if not plate:
        raise QuickError(f"Biển số '{parsed['plate']}' chưa đúng dạng.")
    try:
        res = await api.check_plate(plate)
        if res.get("exists") and res.get("vehicle"):
            vehicle = _vehicle_from_check(res, plate)
        else:
            if not parsed.get("brand") or not parsed.get("model"):
                raise QuickError(f"Xe {plate} chưa có trong AlphaWash. Ghi thêm hãng/dòng ở dòng đầu:\n"
                                 f"VD:  Mazda/CX-5/{plate}")
            found = _find_brand_model(await api.brands_with_models(), parsed["brand"], parsed["model"])
            if not found:
                raise QuickError(f"Không tìm thấy dòng xe '{parsed['brand']} {parsed['model']}' trong AlphaWash.")
            vehicle = {"plate": plate, "label": f"{found['brandName']} {found['modelName']}",
                       "size": found["size"], "brandCode": found["brandCode"],
                       "modelCode": found["modelCode"], "customerId": None, "customerName": None}
        if vehicle["size"] not in SIZES:
            raise QuickError(f"Xe {plate} chưa có size trong AlphaWash. Tạo phiếu bằng /hoadon trên Telegram để chọn size.")
        if not parsed["services"]:
            raise QuickError("Chưa có dịch vụ nào trong tin nhắn.\n\n" + QUICK_HELP)

        groups = orders.groups_for_size(await api.quick_services(), vehicle["size"])
        matched, missing = [], []
        for name in parsed["services"]:
            s = _find_service(groups, name)
            (matched if s else missing).append(s or name)
        if missing:
            raise QuickError(f"Không nhận ra dịch vụ: {', '.join(missing)}.\nKiểm tra tên trong AlphaWash rồi thử lại.")

        matched_emps, missing_emps = [], []
        if parsed["employees"]:
            emps = await api.employees()
            for name in parsed["employees"]:
                e = _find_employee(emps, name)
                if e:
                    matched_emps.append({"id": e["id"], "name": e["name"]})
                else:
                    missing_emps.append(name)
    except BackendError as e:
        raise QuickError(f"⚠️ {e.message}")

    d = _new_draft()
    d["vehicle"] = vehicle
    d["lines"] = [{"code": s["code"], "name": s["name"], "listed": s["price"],
                   "adjusted": None, "reason": None} for s in matched]
    d["emps"] = matched_emps
    d["emp_sel"] = [e["id"] for e in matched_emps]
    d["payment_key"] = "bank"
    return d, missing_emps


def payment_menu() -> tuple[str, list[str]]:
    """Menu chọn thanh toán dạng gõ số (Zalo không có nút)."""
    opts = orders.payment_options()
    text = "Chọn thanh toán (gõ số):\n" + "\n".join(
        f"{i}. {o['label']}" for i, o in enumerate(opts, 1)) + "\n0. ❌ Huỷ"
    return text, [o["key"] for o in opts]


def quick_summary(d: dict) -> str:
    lines = ["🚀 Phiếu nhập nhanh", _head(d), ""]
    for n, ln in enumerate(d["lines"], 1):
        lines.append(f"{n}. {ln['name']} — {money(ln['listed'])}")
    lines.append(f"\n💰 TỔNG: {money(orders.subtotal(d['lines']))}")
    if d["emps"]:
        lines.append(f"Thực hiện: {', '.join(e['name'] for e in d['emps'])}")
    return "\n".join(lines)


def vietqr_url(amount: int, add_info: str) -> str | None:
    """Link ảnh VietQR công khai (img.vietqr.io) — Zalo gửi ảnh được bằng link này."""
    bank = (config.get_business().get("bank") or {})
    short = bank.get("short_name") or bank.get("bin")
    account = bank.get("account")
    if not short or not account:
        return None
    params = urllib.parse.urlencode({"amount": str(int(amount)), "addInfo": add_info,
                                     "accountName": bank.get("account_name") or ""})
    return f"https://img.vietqr.io/image/{short}-{account}-{bank.get('template') or 'compact2'}.png?{params}"
