"""
Bot Zalo viết bài fanpage – dùng chung câu lệnh và Gemini với bot Telegram (post_handler.py).

Zalo Bot không có nút bấm, nên mọi thao tác là gõ chữ:
    /post                                  -> bot hỏi từng bước
    /post Dịch vụ | Xe | Mô tả | Ưu đãi    -> nhập nhanh 1 dòng
    lại      -> viết kiểu khác
    giọng    -> đổi giọng văn
    /huy     -> huỷ
    /id      -> xem ID Zalo
"""
import asyncio
import logging
import os
import re

import httpx

from post_handler import TONES, PostError, _clean, generate_post

API = "https://bot-api.zaloplatforms.com/bot{token}/{method}"
MAX_LEN = 2000  # giới hạn 1 tin nhắn của Zalo Bot
log = logging.getLogger("zalo_bot")

TONE_KEYS = list(TONES)
TONE_MENU = "Chọn giọng văn (gõ số):\n" + "\n".join(
    f"{i}. {TONES[k][0]}" for i, k in enumerate(TONE_KEYS, 1)
)
HELP = (
    "Chào bạn 👋 Mình là bot viết bài fanpage của Shine Autowerkz.\n\n"
    "• /post – viết bài, mình hỏi từng bước\n"
    "• /post Dịch vụ | Xe | Mô tả | Ưu đãi – nhập nhanh 1 dòng\n"
    "• lại – viết kiểu khác\n"
    "• giọng – đổi giọng văn\n"
    "• /huy – huỷ\n"
    "• /id – xem ID Zalo của bạn"
)
FOOTER = "👉 Gõ: lại (viết kiểu khác) · giọng (đổi giọng văn) · /post (bài mới)"
AGAIN_WORDS = {"lại", "lai", "/lai", "viết lại", "viet lai"}
TONE_WORDS = {"giọng", "giong", "/giong", "đổi giọng", "doi giong"}


def _split(text: str, limit: int = MAX_LEN) -> list[str]:
    """Cắt bài dài thành nhiều tin, ưu tiên cắt ở chỗ xuống dòng."""
    parts, buf = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) > limit:
            parts.append(buf)
            buf = line
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts or [text[:limit]]


class ZaloBot:
    def __init__(self, token: str):
        self.token = token
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))
        self.state: dict[str, dict] = {}
        self.bot_name = ""
        raw = os.getenv("ZALO_ALLOWED_USER_IDS", "").strip()
        self.allowed = {x.strip() for x in raw.split(",") if x.strip()}

    # ---------- Gọi API ----------
    async def call(self, method: str, **params):
        r = await self.http.post(API.format(token=self.token, method=method), json=params)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"{method}: HTTP {r.status_code}")
        if not data.get("ok"):
            if data.get("error_code") == 408:  # long polling hết giờ, không có tin mới
                return None
            raise RuntimeError(f"{method}: {data.get('error_code')} {data.get('description')}")
        return data.get("result")

    async def send(self, chat_id: str, text: str) -> None:
        for part in _split(text):
            await self.call("sendMessage", chat_id=chat_id, text=part)

    async def typing(self, chat_id: str) -> None:
        try:
            await self.call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass

    # ---------- Vòng lặp nhận tin ----------
    async def run(self) -> None:
        me = await self.call("getMe")
        self.bot_name = str((me or {}).get("account_name") or (me or {}).get("name") or "")
        log.info("Zalo bot đang chạy: %s", (me or {}).get("account_name") or (me or {}).get("id"))
        try:
            await self.call("deleteWebhook")  # getUpdates không chạy nếu còn webhook
        except Exception:
            pass
        try:
            while True:
                try:
                    res = await self.call("getUpdates", timeout=30)
                except (httpx.TimeoutException, httpx.TransportError):
                    await asyncio.sleep(2)
                    continue
                except Exception as e:
                    log.warning("getUpdates lỗi: %s", e)
                    await asyncio.sleep(5)
                    continue
                if not res:
                    continue
                for u in res if isinstance(res, list) else [res]:
                    asyncio.create_task(self._safe_handle(u))  # không chặn vòng lặp khi Gemini đang viết
        finally:
            await self.http.aclose()

    async def _safe_handle(self, update: dict) -> None:
        try:
            await self.handle(update)
        except Exception:
            log.exception("Lỗi xử lý tin Zalo: %s", update)

    # ---------- Xử lý tin nhắn ----------
    async def handle(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        user_id = str((msg.get("from") or {}).get("id") or "")
        if not chat_id or (msg.get("from") or {}).get("is_bot"):
            return
        if update.get("event_name") != "message.text.received":
            await self.send(chat_id, "Bot chỉ đọc tin nhắn chữ. Gõ /post để viết bài.")
            return

        text = (msg.get("text") or "").strip()
        if (msg.get("chat") or {}).get("chat_type") == "GROUP" or str((msg.get("chat") or {}).get("chat_type", "")).lower() == "group":
            if self.bot_name:  # trong nhóm phải @tag bot -> bỏ phần @tên bot ra khỏi tin
                text = re.sub(re.escape("@" + self.bot_name), "", text, flags=re.I).strip()
            text = re.sub(r"^@\S+\s*", "", text).strip()
        low = text.lower()
        # mỗi người trong mỗi cuộc trò chuyện có phiên riêng
        st = self.state.setdefault(f"{chat_id}:{user_id}", {"step": None, "post": {}, "last": None})

        if low in ("/id", "id"):
            await self.send(chat_id, f"ID Zalo của bạn: {user_id}")
            return
        if low in ("/start", "/help", "help", "hi", "hello", "chào", "chao"):
            await self.send(chat_id, HELP)
            return
        if self.allowed and user_id not in self.allowed:
            await self.send(chat_id, "Bạn chưa được cấp quyền dùng bot này. Gửi /id cho quản lý để được thêm.")
            return
        if low in ("/huy", "huỷ", "hủy", "huy"):
            st.update(step=None, post={})
            await self.send(chat_id, "Đã huỷ. Gõ /post khi cần viết bài.")
            return

        if low.startswith("/post"):
            raw = text[5:].strip()
            if raw:
                parts = [p.strip() for p in raw.split("|")] + ["", "", ""]
                st["post"] = {"service": parts[0], "car": _clean(parts[1]),
                              "detail": _clean(parts[2]), "promo": _clean(parts[3])}
                st["step"] = "tone"
                await self.send(chat_id, TONE_MENU)
            else:
                st.update(step="service", post={})
                await self.send(chat_id, "📸 Dịch vụ vừa quay chụp là gì?\nVD: Phủ ceramic 9H, Dán PPF, Vệ sinh nội thất…\n(/huy để thoát)")
            return

        if st["step"] is None and low in AGAIN_WORDS:
            if st["last"]:
                await self.write(chat_id, st, variant=True)
            else:
                await self.send(chat_id, "Chưa có bài nào. Gõ /post để bắt đầu.")
            return
        if st["step"] is None and low in TONE_WORDS:
            if st["last"]:
                st.update(step="tone", post=dict(st["last"]))
                await self.send(chat_id, TONE_MENU)
            else:
                await self.send(chat_id, "Chưa có bài nào. Gõ /post để bắt đầu.")
            return

        step = st["step"]
        if step == "service":
            st["post"]["service"] = text
            st["step"] = "car"
            await self.send(chat_id, "🚗 Xe gì, màu gì? (gõ - để bỏ qua)")
        elif step == "car":
            st["post"]["car"] = _clean(text)
            st["step"] = "detail"
            await self.send(chat_id, "🛠 Đã làm những gì? Tình trạng trước – sau ra sao?\nCàng cụ thể bài càng hay. (gõ - để bỏ qua)")
        elif step == "detail":
            st["post"]["detail"] = _clean(text)
            st["step"] = "promo"
            await self.send(chat_id, "🎁 Giá / ưu đãi muốn nhắc? (gõ - để bỏ qua)")
        elif step == "promo":
            st["post"]["promo"] = _clean(text)
            st["step"] = "tone"
            await self.send(chat_id, TONE_MENU)
        elif step == "tone":
            if not (text.isdigit() and 1 <= int(text) <= len(TONE_KEYS)):
                await self.send(chat_id, f"Gõ một số từ 1 đến {len(TONE_KEYS)}.\n\n{TONE_MENU}")
                return
            d = dict(st["post"], tone=TONE_KEYS[int(text) - 1])
            st.update(step=None, post={}, last=d)
            await self.write(chat_id, st, variant=False)
        else:
            await self.send(chat_id, "Gõ /post để viết bài fanpage, hoặc /help để xem hướng dẫn.")

    async def write(self, chat_id: str, st: dict, variant: bool) -> None:
        await self.typing(chat_id)
        await self.send(chat_id, "✍️ Đang viết bài…")
        try:
            text = await generate_post(st["last"], variant)
        except PostError as e:
            await self.send(chat_id, str(e))
            return
        except Exception:
            log.exception("Lỗi viết bài")
            await self.send(chat_id, "❌ Có lỗi khi viết bài. Thử lại sau ít phút.")
            return
        await self.send(chat_id, text)  # bài riêng 1 tin để nhấn giữ -> sao chép
        await self.send(chat_id, FOOTER)


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    await ZaloBot(os.environ["ZALO_BOT_TOKEN"]).run()


if __name__ == "__main__":
    asyncio.run(main())
