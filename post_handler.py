"""
Shine Autowerkz – module viết bài fanpage cho bot Telegram.

Dùng độc lập:   python bot.py
Gắn vào bot hoá đơn:
    import post_handler
    post_handler.register(app)   # app = Application của bot hoá đơn

Lệnh:
    /post                      -> bot hỏi từng bước
    /post Dịch vụ | Xe | Mô tả | Ưu đãi   -> nhập nhanh 1 dòng (Xe, Mô tả, Ưu đãi có thể bỏ trống)
    /huy                       -> huỷ giữa chừng
"""
import logging
import os
import re
import warnings

try:
    from google import genai
    from google.genai import errors as genai_errors
except ImportError:  # chưa cài google-genai -> /post báo lỗi, các chức năng khác vẫn chạy
    genai = genai_errors = None
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

warnings.filterwarnings("ignore", category=PTBUserWarning)
log = logging.getLogger(__name__)

# ---------- Cấu hình ----------
SHOP = {
    "name": "Shine Autowerkz",
    "addr": "297G đường Liên Phường, phường Long Trường, TP. Hồ Chí Minh",
    "phone": "0966 29 19 09",
    "hours": "8h – 17h30, Thứ 2 đến Chủ Nhật",
}
POST_LENGTH = os.getenv("POST_LENGTH", "vừa (120–180 chữ)")

TONES = {
    "pro": ("Chuyên nghiệp", "chuyên nghiệp, đáng tin, nói về kỹ thuật"),
    "young": ("Trẻ trung", "trẻ trung, vui, bắt trend, nhiều emoji"),
    "story": ("Kể chuyện trước–sau", "kể chuyện trước–sau, cảm xúc của chủ xe"),
    "sale": ("Chốt sale", "bán hàng mạnh, nhấn ưu đãi, kêu gọi đặt lịch ngay"),
}

SERVICE, CAR, DETAIL, PROMO, TONE = range(5)
SKIP_WORDS = {"-", "bỏ qua", "bo qua", "không", "khong", "k", "ko"}

_client = None
_allowed_override: set[int] | None = None  # bot hoá đơn truyền STAFF_USER_IDS vào đây
_model: str | None = None


class PostError(Exception):
    """Lỗi có sẵn câu báo tiếng Việt để gửi cho người dùng."""


def _gemini():
    global _client
    if genai is None:
        raise PostError("❌ Máy chạy bot chưa cài thư viện Gemini. Quản lý chạy: .venv\\Scripts\\pip install google-genai")
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


async def _pick_model() -> str:
    """Tự chọn model Flash mới nhất mà key này dùng được (Google hay đổi tên model)."""
    names = []
    async for m in await _gemini().aio.models.list():
        n = (m.name or "").removeprefix("models/")
        if "generateContent" not in (m.supported_actions or []) or "flash" not in n:
            continue
        if any(x in n for x in ("image", "tts", "live", "audio", "embed", "exp")):
            continue
        names.append(n)
    if not names:
        raise PostError("❌ Key Gemini này không dùng được model Flash nào.")
    if "gemini-flash-latest" in names:
        return "gemini-flash-latest"

    def score(n: str):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return ("preview" not in n, "lite" not in n, float(v.group(1)) if v else 0.0, -len(n))

    return max(names, key=score)


async def _get_model() -> str:
    global _model
    if _model is None:
        _model = os.getenv("GEMINI_MODEL", "").strip() or await _pick_model()
        log.info("Dùng model Gemini: %s", _model)
    return _model


def _allowed(update: Update) -> bool:
    """Giới hạn người dùng để không bị người lạ tiêu tiền API. Để trống = ai cũng dùng được."""
    if _allowed_override is not None:
        return update.effective_user is not None and update.effective_user.id in _allowed_override
    raw = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return True
    ids = {int(x) for x in raw.replace(" ", "").split(",") if x}
    return update.effective_user is not None and update.effective_user.id in ids


def _clean(text: str) -> str:
    t = (text or "").strip()
    return "" if t.lower() in SKIP_WORDS else t


# ---------- Prompt ----------
def build_prompt(d: dict, variant: bool = False) -> str:
    return f"""Bạn là người viết content cho fanpage Facebook của xưởng detailing ô tô {SHOP['name']} (TP.HCM).
Viết MỘT bài đăng fanpage bằng tiếng Việt cho hình ảnh/video dịch vụ vừa thực hiện.

Thông tin:
- Dịch vụ: {d['service']}
- Xe: {d.get('car') or '(không ghi)'}
- Nội dung đã làm: {d.get('detail') or '(không ghi)'}
- Giá/ưu đãi: {d.get('promo') or 'không đề cập giá, không bịa ưu đãi'}
- Giọng văn: {TONES[d.get('tone', 'pro')][1]}
- Độ dài: {POST_LENGTH}

Cấu trúc:
1. Dòng mở đầu gây chú ý (hook) — 1 câu.
2. Thân bài: tình trạng xe, quy trình làm, kết quả. Chỉ dùng chi tiết được cung cấp; không bịa số liệu, thời gian bảo hành hay cam kết.
3. Kêu gọi hành động: inbox/gọi Zalo đặt lịch.
4. Khối liên hệ đúng nguyên văn:
📍 {SHOP['addr']}
📞 Hotline/Zalo: {SHOP['phone']}
⏰ {SHOP['hours']}
5. 5–8 hashtag liên quan, có #ShineAutowerkz.

Dùng emoji vừa phải theo giọng văn. Không dùng markdown (không **, không #tiêu đề). Chỉ trả về nội dung bài đăng, không giải thích.""" + (
        "\nViết theo một góc nhìn và câu mở đầu KHÁC hẳn so với phiên bản thông thường." if variant else ""
    )


async def generate_post(d: dict, variant: bool = False) -> str:
    global _model
    prompt = build_prompt(d, variant)
    config = {"temperature": 1.1 if variant else 0.8}
    for attempt in range(2):
        try:
            model = await _get_model()
            resp = await _gemini().aio.models.generate_content(model=model, contents=prompt, config=config)
        except PostError:
            raise
        except Exception as e:
            if genai_errors is None or not isinstance(e, genai_errors.APIError):
                raise
            log.warning("Gemini lỗi %s: %s", e.code, e.message)
            if e.code == 404 and attempt == 0:  # model bị đổi tên/ngừng -> tự chọn lại
                _model = await _pick_model()
                continue
            if e.code == 429:
                raise PostError("⏳ Đã chạm giới hạn lượt miễn phí của Gemini. Đợi 1–2 phút rồi bấm lại (nếu hết lượt trong ngày thì khoảng 15h chiều mới reset).")
            if e.code in (400, 401, 403) and "key" in (e.message or "").lower():
                raise PostError("🔑 GEMINI_API_KEY sai hoặc chưa bật. Kiểm tra lại key trong file .env.")
            if e.code and e.code >= 500:
                raise PostError("❌ Máy chủ Gemini đang quá tải. Thử lại sau ít phút.")
            raise PostError(f"❌ Không viết được bài (Gemini lỗi {e.code}). Thử lại sau ít phút.")
        text = (resp.text or "").strip()
        if not text:
            raise PostError("❌ Gemini không trả về bài viết. Thử sửa lại mô tả rồi viết lại.")
        return text
    raise PostError("❌ Không tìm được model Gemini phù hợp.")


# ---------- Bàn phím ----------
def _tone_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, callback_data=f"tone:{k}")] for k, (label, _) in TONES.items()]
    return InlineKeyboardMarkup(rows)


def _after_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Viết kiểu khác", callback_data="post:again"),
        InlineKeyboardButton("🎨 Đổi giọng văn", callback_data="post:tone"),
    ]])


# ---------- Các bước hội thoại ----------
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _allowed(update):
        await update.message.reply_text("Bạn chưa được cấp quyền dùng tính năng này.")
        return ConversationHandler.END

    context.user_data["post"] = {}
    raw = " ".join(context.args or []).strip()
    if raw:  # nhập nhanh: Dịch vụ | Xe | Mô tả | Ưu đãi
        parts = [p.strip() for p in raw.split("|")] + ["", "", ""]
        context.user_data["post"] = {
            "service": parts[0], "car": _clean(parts[1]),
            "detail": _clean(parts[2]), "promo": _clean(parts[3]),
        }
        await update.message.reply_text("Chọn giọng văn:", reply_markup=_tone_kb())
        return TONE

    await update.message.reply_text(
        "📸 Dịch vụ vừa quay chụp là gì?\nVD: Phủ ceramic 9H, Dán PPF, Vệ sinh nội thất…\n(/huy để thoát)"
    )
    return SERVICE


async def got_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["post"]["service"] = update.message.text.strip()
    await update.message.reply_text("🚗 Xe gì, màu gì? (gõ - để bỏ qua)")
    return CAR


async def got_car(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["post"]["car"] = _clean(update.message.text)
    await update.message.reply_text(
        "🛠 Đã làm những gì? Tình trạng trước – sau ra sao?\n"
        "Càng cụ thể bài càng hay. (gõ - để bỏ qua)"
    )
    return DETAIL


async def got_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["post"]["detail"] = _clean(update.message.text)
    await update.message.reply_text("🎁 Giá / ưu đãi muốn nhắc? (gõ - để bỏ qua)")
    return PROMO


async def got_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["post"]["promo"] = _clean(update.message.text)
    await update.message.reply_text("Chọn giọng văn:", reply_markup=_tone_kb())
    return TONE


async def _write_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, variant: bool) -> None:
    d = context.user_data.get("last_post")
    chat_id = update.effective_chat.id
    if not d:
        await context.bot.send_message(chat_id, "Chưa có thông tin bài. Gõ /post để bắt đầu.")
        return
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    wait = await context.bot.send_message(chat_id, "✍️ Đang viết bài…")
    try:
        text = await generate_post(d, variant)
    except PostError as e:
        await wait.edit_text(str(e))
        return
    except Exception:
        log.exception("Unexpected error")
        await wait.edit_text("❌ Có lỗi khi viết bài. Thử lại sau ít phút.")
        return
    await wait.delete()
    # Gửi dạng chữ thường để nhấn giữ -> Sao chép là dán thẳng lên Facebook
    await context.bot.send_message(chat_id, text[:4096], reply_markup=_after_kb())


async def got_tone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    d = dict(context.user_data.get("post") or context.user_data.get("last_post") or {})
    if not d.get("service"):
        await q.edit_message_text("Phiên đã hết. Gõ /post để bắt đầu lại.")
        return ConversationHandler.END
    d["tone"] = key if key in TONES else "pro"
    context.user_data["last_post"] = d
    await q.edit_message_text(f"Giọng văn: {TONES[d['tone']][0]}")
    await _write_and_send(update, context, variant=False)
    return ConversationHandler.END


async def on_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("Đang viết phiên bản khác…")
    await _write_and_send(update, context, variant=True)


async def on_change_tone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if not context.user_data.get("last_post"):
        await context.bot.send_message(update.effective_chat.id, "Gõ /post để bắt đầu.")
        return ConversationHandler.END
    context.user_data["post"] = dict(context.user_data["last_post"])
    await context.bot.send_message(update.effective_chat.id, "Chọn giọng văn:", reply_markup=_tone_kb())
    return TONE


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("post", None)
    await update.message.reply_text("Đã huỷ. Gõ /post khi cần viết bài.")
    return ConversationHandler.END


# ---------- Đăng ký vào bot ----------
def register(app: Application, allowed_ids: set[int] | None = None) -> None:
    """allowed_ids: danh sách ID được dùng (VD config.STAFF_USER_IDS). None = đọc ALLOWED_USER_IDS trong .env."""
    global _allowed_override
    _allowed_override = allowed_ids
    text = filters.TEXT & ~filters.COMMAND
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("post", cmd_post),
            CallbackQueryHandler(on_change_tone, pattern=r"^post:tone$"),
        ],
        states={
            SERVICE: [MessageHandler(text, got_service)],
            CAR: [MessageHandler(text, got_car)],
            DETAIL: [MessageHandler(text, got_detail)],
            PROMO: [MessageHandler(text, got_promo)],
            TONE: [CallbackQueryHandler(got_tone, pattern=r"^tone:")],
        },
        fallbacks=[CommandHandler("huy", cmd_cancel), CommandHandler("post", cmd_post)],
        conversation_timeout=15 * 60,
        name="shine_post",
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_again, pattern=r"^post:again$"))
