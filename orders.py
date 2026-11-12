"""Chuyển đổi giữa draft của bot <-> payload/response của API AlphaWash."""
from datetime import datetime

import config
from utils import parse_dt

BOT_TAG = "[Bot]"          # đánh dấu dòng ghi tên nhân viên lập phiếu trong note của đơn


def _n(x) -> int:
    return int(round(float(x or 0)))


# ------------------------------------------------------------------ thanh toán
def payment_options() -> list[dict]:
    return config.get_mapping()["payment_options"]


def payment_option(key: str) -> dict:
    return next(o for o in payment_options() if o["key"] == key)


def payment_display(payment_type: str | None, payment_status: str | None) -> str:
    m = config.get_mapping()
    if payment_status and payment_status != m.get("paid_status", "PAID"):
        return "Chưa thanh toán"
    for o in m["payment_options"]:
        if o.get("paymentType") and o["paymentType"] == payment_type:
            return o["display"]
    return payment_type or ""


# ------------------------------------------------------------------ draft -> payload
def line_price(line: dict) -> int:
    return line["adjusted"] if line["adjusted"] is not None else line["listed"]


def subtotal(lines: list[dict]) -> int:
    return sum(line_price(l) for l in lines)


def groups_for_size(groups: list[dict], size: str) -> list[dict]:
    """Từ /api/quick-invoice/services -> nhóm dịch vụ có giá cho size của xe."""
    out = []
    for g in groups:
        services = []
        for s in g.get("services") or []:
            cat = next((c for c in s.get("catalogs") or []
                        if str(c.get("size", "")).upper() == size and c.get("catalogCode")
                        and c.get("price") is not None), None)
            if cat:
                services.append({"code": cat["catalogCode"], "price": _n(cat["price"]),
                                 "name": s.get("serviceName") or s.get("serviceCode") or cat["catalogCode"]})
        if services:
            out.append({"name": g.get("serviceTypeName") or g.get("serviceTypeCode") or "Khác",
                        "services": services})
    return out


def build_order_payload(d: dict, staff_name: str) -> dict:
    m = config.get_mapping()
    v = d["vehicle"]
    opt = payment_option(d["payment_key"])
    sub, discount = subtotal(d["lines"]), d["discount"]
    total = sub if m.get("total_price_mode", "gross") == "gross" else sub - discount
    now = datetime.now(config.TZ).replace(microsecond=0, tzinfo=None).isoformat()

    note = [d["note"]] if d["note"] else []
    note.append(f"{BOT_TAG} NV lập: {staff_name}")

    services = [{
        "serviceCatalogCode": l["code"], "serviceItemId": None,
        "adjustedPrice": l["adjusted"], "adjustedPriceFlag": l["adjusted"] is not None,
        "adjustedPriceReason": l["reason"], "quantity": 1,
    } for l in d["lines"]]

    return {
        "customerId": v.get("customerId"),
        "licensePlate": v["plate"], "brandCode": v.get("brandCode"), "modelCode": v.get("modelCode"),
        "imageUrl": None, "vehicleNote": None,
        "date": now, "checkInTime": None, "checkOutTime": None,
        "paymentType": opt["paymentType"], "paymentStatus": opt["paymentStatus"],
        "tip": 0, "vat": 0, "discount": discount, "totalPrice": total,
        "note": "\n".join(note),
        "orderDetails": [{
            "employeeIds": [e["id"] for e in d["emps"] if e["id"] in d["emp_sel"]],
            "services": services, "products": [],
            "status": m.get("order_detail_status", "COMPLETED"), "note": None,
            "licensePlate": v["plate"], "brandCode": v.get("brandCode"), "modelCode": v.get("modelCode"),
            "imageUrl": None, "vehicleNote": None,
        }],
    }


# ------------------------------------------------------------------ OrderFullDto -> dữ liệu để vẽ ảnh
def order_to_invoice(order: dict) -> dict:
    m = config.get_mapping()
    details = order.get("orderDetails") or []
    vehicle = next((d["vehicle"] for d in details if d.get("vehicle")), {}) or {}

    items: list[dict] = []
    employees: list[str] = []
    for d in details:
        for e in d.get("employees") or []:
            if e.get("name") and e["name"] not in employees:
                employees.append(e["name"])
        for s in d.get("service") or []:
            flag = s.get("adjustedPriceFlag") and s.get("adjustedPrice") is not None
            unit = s["adjustedPrice"] if flag else (s.get("serviceCatalog") or {}).get("listedPrice")
            qty = s.get("quantity") or 1
            name = s.get("serviceName") or s.get("serviceCode") or "Dịch vụ"
            items.append({"name": name + (f" x{qty}" if qty > 1 else ""), "price": _n(unit) * qty})
        for p in d.get("products") or []:
            flag = p.get("adjustedPriceFlag") and p.get("adjustedPrice") is not None
            unit = p["adjustedPrice"] if flag else p.get("unitPrice")
            qty = p.get("quantity") or 1
            name = p.get("productName") or p.get("productCode") or "Sản phẩm"
            items.append({"name": name + (f" x{qty}" if qty > 1 else ""), "price": _n(unit) * qty})

    discount = _n(order.get("discount"))
    total_price = _n(order.get("totalPrice"))
    total = total_price - discount if m.get("total_price_mode", "gross") == "gross" else total_price

    note_lines, staff = [], ""
    for line in (order.get("note") or "").splitlines():
        if line.startswith(BOT_TAG):
            staff = line.split(":", 1)[-1].strip()
        elif line.strip():
            note_lines.append(line.strip())

    label = " ".join(x for x in (vehicle.get("brandName"), vehicle.get("modelName")) if x)
    size = str(vehicle.get("size") or "").upper()

    return {
        "number": order.get("code") or order.get("id") or "",
        "created_at": parse_dt(order.get("date")),
        "check_in": order.get("checkInTime"),
        "check_out": order.get("checkOutTime"),
        "plate": vehicle.get("licensePlate") or "",
        "vehicle": label,
        "size": size,
        "customer": (order.get("customer") or {}).get("name") or "",
        "employees": employees,
        "items": items,
        "subtotal": sum(i["price"] for i in items),
        "discount": discount,
        "total": total,
        "payment_type": order.get("paymentType") or "",
        "payment": payment_display(order.get("paymentType"), order.get("paymentStatus")),
        "note": "\n".join(note_lines),
        "staff_name": staff,
    }
