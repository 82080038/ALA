"""Rate limiting — sliding window per (IP, aturan path).

Zero-cost: tanpa Redis/layanan eksternal. Penyimpanan utama adalah
SQLite bersama (WAL) sehingga kuota dihitung benar walau uvicorn
dijalankan multi-worker — file di-share seluruh proses di host ini
dan bertahan melintasi restart (brute-force login tidak reset saat
API di-restart). Bila DB bermasalah, fallback ke deque in-memory
per-proses (degradasi aman: tetap membatasi, hanya per-worker).

Melindungi endpoint mahal (job LLM, eksekusi sandbox) dan login
(anti brute-force).
"""
import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

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

_DB_PATH = os.environ.get(
    "RATELIMIT_DB",
    str(Path.home() / ".chroma" / "ratelimit.db"))
# Fallback per-proses bila SQLite gagal — tetap membatasi, hanya
# tidak lintas-worker.
_hits: "dict[tuple[str, str], deque]" = {}
_lock = threading.Lock()
_local = threading.local()

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS rl_hits ("
    "  k TEXT NOT NULL, ts REAL NOT NULL);"
    "CREATE INDEX IF NOT EXISTS ix_rl_hits ON rl_hits (k, ts);"
)


def _conn() -> sqlite3.Connection:
    """Koneksi SQLite per-thread — object tidak thread-safe."""
    con = getattr(_local, "con", None)
    if con is None:
        Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(_DB_PATH, timeout=5)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=3000")
        con.executescript(_SCHEMA)
        _local.con = con
    return con


# Bersihkan baris kedaluwarsa secara global tiap ~100 hit agar file
# tidak membengkak (per-key sudah dibersihkan tiap hit).
_sweep_counter = 0


def _check_sqlite(key: str, limit: int, window: int) -> int | None:
    """Kembalikan sisa detik tunggu bila limit terlampaui; None bila lolos.
    Raise pada kegagalan DB — pemanggil jatuh ke fallback in-memory."""
    global _sweep_counter
    now = time.time()
    con = _conn()
    con.execute("BEGIN IMMEDIATE")  # write lock — check+insert atomik
    retry: int | None = None
    try:
        con.execute("DELETE FROM rl_hits WHERE k=? AND ts<?",
                    (key, now - window))
        n = con.execute(
            "SELECT COUNT(*) FROM rl_hits WHERE k=?", (key,)).fetchone()[0]
        if n >= limit:
            oldest = con.execute(
                "SELECT MIN(ts) FROM rl_hits WHERE k=?", (key,)
            ).fetchone()[0]
            retry = int(window - (now - oldest)) + 1
        else:
            con.execute(
                "INSERT INTO rl_hits (k, ts) VALUES (?,?)", (key, now))
            _sweep_counter += 1
            if _sweep_counter % 100 == 0:
                con.execute(
                    "DELETE FROM rl_hits WHERE ts<?", (now - 3600,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return retry


def _check_memory(key: str, limit: int, window: int) -> int | None:
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return int(window - (now - q[0])) + 1
        q.append(now)
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method
        for rule_method, prefix, limit, window in _RULES:
            if method == rule_method and path.startswith(prefix):
                ip = request.client.host if request.client else "?"
                key = f"{ip}|{rule_method}:{prefix}"
                try:
                    retry = _check_sqlite(key, limit, window)
                except Exception:
                    retry = _check_memory(key, limit, window)
                if retry is not None:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Terlalu banyak request — "
                                      f"coba lagi dalam {retry}s."},
                        headers={"Retry-After": str(retry)},
                    )
                break
        return await call_next(request)
