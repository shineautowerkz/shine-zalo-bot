"""
Tạo BẢNG BÁO GIÁ DỊCH VỤ trong bot Telegram.

Lệnh: /baogia -> chọn gói -> tên khách -> SĐT -> dòng xe -> kích cỡ -> (giá) -> xuất ảnh + PDF.
Gói, quà tặng, giá theo kích cỡ, ghi chú: sửa trong quote_templates.json (không cần sửa code).

Gắn vào bot: import quote; quote.register(app)   # đặt TRƯỚC các handler hoá đơn
"""
import asyncio
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)

import config
from quote_image import load_templates, render_quote, vnd
from utils import parse_money

log = logging.getLogger("quote")

Q_TPL, Q_NAME, Q_PHONE, Q_CAR, Q_SIZE, Q_PRICE, Q_CONFIRM = range(100, 107)
TEXT = filters.TEXT & ~filters.COMMAND
SKIP = {"-", "bỏ qua", "bo qua", "không", "khong", "k", "ko"}


def _b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


CANCEL = [_b("❌ Huỷ", "bg:cancel")]


async def _show(update: Update, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)


def _q(ctx) -> dict | None:
    return ctx.user_data.get("quote")


def _tpl(q: dict) -> dict:
    for t in load_templates()["templates"]:
        if t["id"] == q["tpl_id"]:
            return t
    raise KeyError(q["tpl_id"])


async def _expired(update: Update) -> int:
    await _show(update, "Phiên báo giá đã hết hạn. Gõ /baogia để làm lại.")
    return ConversationHandler.END


# ---------- Các bước ----------
async def start_quote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None or user.id not in config.STAFF_USER_IDS:
        await update.effective_message.reply_text(f"⛔ Bạn chưa được cấp quyền.\nID Telegram của bạn: {user.id if user else ''}")
        return ConversationHandler.END
    try:
        tpls = load_templates()["templates"]
    except Exception as e:
        log.exception("quote_templates.json lỗi")
        await update.effective_message.reply_text(f"❌ File quote_templates.json bị lỗi: {e}")
        return ConversationHandler.END
    ctx.user_data["quote"] = {}
    if len(tpls) == 1:
        ctx.user_data["quote"]["tpl_id"] = tpls[0]["id"]
        return await _ask_name(update, tpls[0])
    kb = [[_b(t["name"], f"bg:tpl:{t['id']}")] for t in tpls] + [CANCEL]
    await _show(update, "📄 Báo giá dịch vụ nào?", InlineKeyboardMarkup(kb))
    return Q_TPL


async def _ask_name(update: Update, tpl: dict) -> int:
    await _show(update, f"📄 Báo giá: {tpl['name']}\n\n👤 Tên khách hàng? (VD: Anh Nguyên)\n(/huy để thoát)")
    return Q_NAME


async def pick_tpl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    q["tpl_id"] = update.callback_query.data.split(":", 2)[2]
    return await _ask_name(update, _tpl(q))


async def got_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    q["customer"] = update.message.text.strip()
    await update.message.reply_text("📞 Số điện thoại? (gõ - để bỏ qua)")
    return Q_PHONE


async def got_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    t = update.message.text.strip()
    q["phone"] = "" if t.lower() in SKIP else t
    await update.message.reply_text("🚗 Dòng xe? (VD: Lynk & Co 02)")
    return Q_CAR


async def got_car(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    q["car"] = update.message.text.strip()
    sizes = _tpl(q).get("sizes") or []
    kb = [[_b(s, f"bg:sz:{i}")] for i, s in enumerate(sizes)] + [CANCEL]
    await update.message.reply_text("📏 Kích cỡ xe? (bấm chọn hoặc gõ kích cỡ khác)", reply_markup=InlineKeyboardMarkup(kb))
    return Q_SIZE


async def _after_size(update: Update, ctx, size: str) -> int:
    q = _q(ctx)
    q["size"] = size
    opts = _tpl(q)["options"]
    prices = [o.get("prices", {}).get(size) for o in opts]
    if all(isinstance(p, int) and p > 0 for p in prices):
        q["prices"] = prices
        return await _confirm(update, ctx)
    return await _ask_price(update, ctx)


async def pick_size(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    sizes = _tpl(q).get("sizes") or []
    i = int(update.callback_query.data.split(":")[2])
    return await _after_size(update, ctx, sizes[i] if i < len(sizes) else "")


async def got_size(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if _q(ctx) is None:
        return await _expired(update)
    return await _after_size(update, ctx, update.message.text.strip())


async def _ask_price(update: Update, ctx) -> int:
    q = _q(ctx)
    opts = _tpl(q)["options"]
    names = "\n".join(f"• {o['name']}" for o in opts)
    eg = " / ".join(["33tr", "55tr", "70tr"][: len(opts)])
    await _show(update,
                f"💰 Nhập giá cho {len(opts)} option (theo thứ tự), cách nhau bằng dấu /\n{names}\n\nVD: {eg}",
                InlineKeyboardMarkup([CANCEL]))
    return Q_PRICE


async def ask_price_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    if _q(ctx) is None:
        return await _expired(update)
    return await _ask_price(update, ctx)


async def got_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    n = len(_tpl(q)["options"])
    parts = [p for p in re.split(r"[/;|\n]+", update.message.text) if p.strip()]
    prices = [parse_money(p) for p in parts]
    if len(prices) != n or any(p is None for p in prices):
        await update.message.reply_text(f"Chưa đúng. Cần {n} giá, cách nhau bằng dấu /. VD: " + " / ".join(["33tr", "55tr", "70tr"][:n]))
        return Q_PRICE
    q["prices"] = prices
    return await _confirm(update, ctx)


async def _confirm(update: Update, ctx) -> int:
    q = _q(ctx)
    tpl = _tpl(q)
    lines = [f"📄 {tpl['name']}", f"👤 {q['customer']}" + (f" · {q['phone']}" if q.get("phone") else ""),
             f"🚗 {q['car']} · {q['size']}", ""]
    lines += [f"{o['name']}: {vnd(p)}" for o, p in zip(tpl["options"], q["prices"])]
    kb = InlineKeyboardMarkup([[_b("✅ Xuất báo giá", "bg:ok")], [_b("✏️ Sửa giá", "bg:price")], CANCEL])
    await _show(update, "\n".join(lines), kb)
    return Q_CONFIRM


async def do_render(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    q = _q(ctx)
    if q is None:
        return await _expired(update)
    await update.callback_query.edit_message_text("🖨 Đang tạo báo giá…")
    payload = dict(q, template=_tpl(q), date=datetime.now(config.TZ).strftime("%d/%m/%Y"))
    try:
        png, pdf = await asyncio.to_thread(render_quote, payload)
    except Exception as e:
        log.exception("Lỗi vẽ báo giá")
        await update.callback_query.edit_message_text(f"❌ Không tạo được báo giá: {e}")
        return ConversationHandler.END
    chat = update.effective_chat.id
    with open(png, "rb") as f:
        await ctx.bot.send_photo(chat, f, caption=f"Báo giá {q['customer']} – {q['car']}")
    with open(pdf, "rb") as f:
        await ctx.bot.send_document(chat, f, filename=pdf.name)
    await update.callback_query.edit_message_text("✅ Đã tạo báo giá. Gõ /baogia để làm báo giá khác.")
    ctx.user_data.pop("quote", None)
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    ctx.user_data.pop("quote", None)
    await _show(update, "Đã huỷ báo giá.")
    return ConversationHandler.END


def register(app: Application) -> None:
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("baogia", start_quote)],
        states={
            Q_TPL: [CallbackQueryHandler(pick_tpl, pattern=r"^bg:tpl:")],
            Q_NAME: [MessageHandler(TEXT, got_name)],
            Q_PHONE: [MessageHandler(TEXT, got_phone)],
            Q_CAR: [MessageHandler(TEXT, got_car)],
            Q_SIZE: [CallbackQueryHandler(pick_size, pattern=r"^bg:sz:\d+$"), MessageHandler(TEXT, got_size)],
            Q_PRICE: [MessageHandler(TEXT, got_price)],
            Q_CONFIRM: [CallbackQueryHandler(do_render, pattern=r"^bg:ok$"),
                        CallbackQueryHandler(ask_price_btn, pattern=r"^bg:price$")],
        },
        fallbacks=[CommandHandler("huy", cancel), CallbackQueryHandler(cancel, pattern=r"^bg:cancel$"),
                   CommandHandler("baogia", start_quote)],
        conversation_timeout=1800,
        name="quote",
    ))
