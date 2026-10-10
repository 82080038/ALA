"""Rate limiting in-memory — sliding window per (IP, aturan path).

Zero-cost: tanpa Redis/layanan eksternal. Melindungi endpoint mahal
(job LLM, eksekusi sandbox) dan login (anti brute-force). Bersifat
per-proses — cukup untuk deployment single-node standalone.
"""
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# (method, path-prefix) → (maks request, jendela detik).
# Method dibatasi POST — GET /analyze-trend/{id} adalah poller status
# (tiap beberapa detik) dan tidak boleh menghabiskan kuota job mahal.
_RULES: "list[tuple[str, str, int, int]]" = [
    ("POST", "/api/v1/auth/login", 10, 60),
    ("POST", "/api/v1/analyze-trend", 10, 60),
    ("POST", "/api/v1/approve-workflow", 20, 60),
    ("POST", "/api/v1/alcd/trigger", 3, 300),
]

_hits: "dict[tuple[str, str], deque]" = {}
_lock = threading.Lock()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method
        for rule_method, prefix, limit, window in _RULES:
            if method == rule_method and path.startswith(prefix):
                ip = request.client.host if request.client else "?"
                key = (ip, f"{rule_method}:{prefix}")
                now = time.monotonic()
                with _lock:
                    q = _hits.setdefault(key, deque())
                    while q and now - q[0] > window:
                        q.popleft()
                    if len(q) >= limit:
                        retry = int(window - (now - q[0])) + 1
                        return JSONResponse(
                            status_code=429,
                            content={
                                "detail": "Terlalu banyak request — "
                                          f"coba lagi dalam {retry}s."},
                            headers={"Retry-After": str(retry)},
                        )
                    q.append(now)
                break
        return await call_next(request)
