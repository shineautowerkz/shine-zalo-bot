"""Client gọi API AlphaWash (JWT Bearer). Chỉ dùng các endpoint cần cho bot."""
import asyncio
import base64
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

import config

log = logging.getLogger("alphawash-api")


class BackendError(Exception):
    """Lỗi khi gọi AlphaWash.

    definitive=True : chắc chắn BE KHÔNG xử lý yêu cầu (4xx, không kết nối được) -> an toàn để thử lại.
    definitive=False: không rõ BE đã xử lý chưa (timeout, 5xx) -> KHÔNG tự thử lại lệnh ghi.
    """

    def __init__(self, message: str, *, status: int | None = None, definitive: bool = False):
        super().__init__(message)
        self.message, self.status, self.definitive = message, status, definitive


def _message_of(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200] or f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or data)[:300]
    return str(data)[:300]


def unwrap(data: Any) -> Any:
    """Nhiều endpoint bọc trong {success, message, data}."""
    if isinstance(data, dict) and "success" in data and "data" in data:
        if data.get("success") is False:
            raise BackendError(str(data.get("message") or "AlphaWash từ chối yêu cầu"), definitive=True)
        return data["data"]
    return data


class AlphaWashClient:
    def __init__(self, base_url: str | None = None, username: str | None = None,
                 password: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.username = username if username is not None else config.API_USERNAME
        self.password = password if password is not None else config.API_PASSWORD
        self._http = httpx.AsyncClient(base_url=(base_url or config.API_BASE_URL),
                                       timeout=config.API_TIMEOUT, transport=transport)
        self._token: str | None = None
        self._login_lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------------------------------------------------------------- auth / http
    async def _login(self) -> None:
        async with self._login_lock:
            try:
                r = await self._http.post("/api/auth/login",
                                          json={"username": self.username, "password": self.password})
            except httpx.HTTPError as e:
                raise BackendError("Không kết nối được AlphaWash.", definitive=isinstance(
                    e, (httpx.ConnectError, httpx.ConnectTimeout))) from e
            if r.status_code in (400, 401, 403):
                raise BackendError("Bot đăng nhập AlphaWash thất bại (sai tài khoản/mật khẩu bot).",
                                   status=r.status_code, definitive=True)
            if r.status_code >= 400:
                raise BackendError(f"AlphaWash lỗi khi đăng nhập ({r.status_code}).", status=r.status_code)
            try:
                body = unwrap(r.json()) or {}
            except ValueError as e:
                raise BackendError("AlphaWash trả dữ liệu đăng nhập không đọc được.") from e
            token = body.get("token") if isinstance(body, dict) else None
            if not token:
                raise BackendError("AlphaWash không trả token đăng nhập.")
            self._token = token

    async def request(self, method: str, path: str, *, json: Any = None,
                      params: dict | None = None) -> httpx.Response:
        if not self._token:
            await self._login()
        r = None
        for attempt in (1, 2):
            try:
                r = await self._http.request(method, path, json=json, params=params,
                                             headers={"Authorization": f"Bearer {self._token}"})
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                raise BackendError("Không kết nối được AlphaWash.", definitive=True) from e
            except httpx.TimeoutException as e:
                raise BackendError("AlphaWash phản hồi quá lâu.", definitive=False) from e
            except httpx.HTTPError as e:
                raise BackendError("Mất kết nối khi đang gọi AlphaWash.", definitive=False) from e
            if r.status_code in (401, 403) and attempt == 1:    # token hết hạn -> đăng nhập lại 1 lần
                self._token = None
                await self._login()
                continue
            break
        assert r is not None
        if r.status_code in (401, 403):
            raise BackendError("Tài khoản bot không đủ quyền với chức năng này.",
                               status=r.status_code, definitive=True)
        if r.status_code >= 500:
            raise BackendError(f"AlphaWash đang lỗi ({r.status_code}).", status=r.status_code, definitive=False)
        if r.status_code >= 400:
            raise BackendError(_message_of(r), status=r.status_code, definitive=True)
        return r

    async def _get(self, path: str, **params: Any) -> Any:
        r = await self.request("GET", path, params={k: v for k, v in params.items() if v is not None})
        try:
            return unwrap(r.json())
        except ValueError as e:
            raise BackendError("AlphaWash trả dữ liệu không đọc được.") from e

    async def _cached(self, key: str, ttl: float, fetch: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await fetch()
        self._cache[key] = (time.monotonic(), value)
        return value

    # ---------------------------------------------------------------- đọc
    async def check_plate(self, plate: str) -> dict:
        return await self._get("/api/vehicles/check-plate", plate=plate) or {}

    async def recent_vehicles(self, limit: int = 6) -> list[dict]:
        return await self._get("/api/quick-invoice/recent-vehicles", limit=limit) or []

    async def quick_services(self) -> list[dict]:
        return await self._cached("svc", 300, lambda: self._get("/api/quick-invoice/services")) or []

    async def brands_with_models(self) -> list[dict]:
        return await self._cached("brands", 1800, lambda: self._get("/api/brands/brands/with-models")) or []

    async def employees(self) -> list[dict]:
        """Chỉ giữ id, name, workStatus (API còn trả CCCD/STK ngân hàng — bot không lấy, không log)."""
        async def fetch() -> list[dict]:
            rows = await self._get("/api/employee/") or []
            return [{"id": e.get("id"), "name": e.get("name"), "workStatus": e.get("workStatus")}
                    for e in rows if e.get("id") is not None]
        return await self._cached("emp", 600, fetch)

    async def get_order(self, order_id: str) -> dict:
        return await self._get(f"/api/orders/{order_id}") or {}

    async def get_order_by_code(self, code: str) -> dict:
        return await self._get(f"/api/orders/code/{code}") or {}

    async def customer_invoices(self, customer_id: str, size: int = 50) -> list[dict]:
        page = await self._get(f"/api/customer/{customer_id}/invoices", page=0, size=size) or {}
        return page.get("content") or []

    async def dashboard(self, start: str, end: str, compare_start: str, compare_end: str) -> dict:
        r = await self.request("POST", "/api/dashboard", json={
            "startDate": start, "endDate": end,
            "compareStartDate": compare_start, "compareEndDate": compare_end})
        return unwrap(r.json()) or {}

    # ---------------------------------------------------------------- ghi
    async def create_order(self, payload: dict) -> str:
        """Trả về UUID phiếu. KHÔNG tự thử lại khi lỗi mơ hồ (tránh tạo trùng)."""
        r = await self.request("POST", "/api/orders/create-order", json=payload)
        try:
            value = unwrap(r.json())
        except ValueError:
            value = r.text
        order_id = value.strip().strip('"') if isinstance(value, str) else ""
        if not order_id:
            raise BackendError("AlphaWash không trả về mã phiếu — hãy kiểm tra trong AlphaWash trước khi tạo lại.")
        return order_id

    # ---------------------------------------------------------------- PDF hoá đơn (có QR)
    MAX_PDF_BYTES = 20 * 1024 * 1024

    @staticmethod
    def pdf_enabled() -> bool:
        return bool(((config.get_mapping().get("invoice_pdf") or {}).get("path") or "").strip())

    async def download_invoice_pdf(self, order_id: str, code: str) -> bytes:
        """Gọi endpoint PDF của BE (cấu hình trong api_mapping.json) và trả về bytes của file PDF."""
        cfg = config.get_mapping().get("invoice_pdf") or {}
        path = (cfg.get("path") or "").strip()
        if not path:
            raise BackendError("Chưa cấu hình endpoint PDF.", definitive=True)
        path = path.replace("{id}", order_id).replace("{code}", code)
        r = await self.request((cfg.get("method") or "GET").upper(), path)
        return await self._pdf_from_response(r)

    async def _pdf_from_response(self, r: httpx.Response) -> bytes:
        if r.content[:5] == b"%PDF-":
            return self._checked(r.content)
        try:
            body = unwrap(r.json())
        except ValueError as e:
            raise BackendError("AlphaWash không trả về file PDF hợp lệ.") from e
        candidates: list[str] = []
        if isinstance(body, str):
            candidates.append(body)
        elif isinstance(body, dict):
            for k in ("pdf", "base64", "content", "file", "data", "url", "link", "downloadUrl", "pdfUrl"):
                if isinstance(body.get(k), str):
                    candidates.append(body[k])
        for c in candidates:
            c = c.strip()
            if c.startswith(("http://", "https://")):
                return await self._fetch_pdf_url(c)
            try:
                raw = base64.b64decode(c.split(",", 1)[-1])       # cả dạng data:application/pdf;base64,...
            except Exception:  # noqa: BLE001
                continue
            if raw[:5] == b"%PDF-":
                return self._checked(raw)
        raise BackendError("AlphaWash không trả về file PDF hợp lệ.")

    async def _fetch_pdf_url(self, url: str) -> bytes:
        headers = {}
        if httpx.URL(url).host == self._http.base_url.host:       # chỉ gửi token cho đúng máy chủ AlphaWash
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            r = await self._http.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise BackendError("Không tải được file PDF từ AlphaWash.") from e
        if r.status_code >= 400 or r.content[:5] != b"%PDF-":
            raise BackendError("Link PDF của AlphaWash không trả file hợp lệ.", status=r.status_code)
        return self._checked(r.content)

    def _checked(self, data: bytes) -> bytes:
        if len(data) > self.MAX_PDF_BYTES:
            raise BackendError("File PDF quá lớn.")
        return data
