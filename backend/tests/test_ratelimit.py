"""Uji rate limiter — aturan per-method: poller GET /analyze-trend/{id}
tidak boleh menghabiskan kuota POST analyze-trend (bug: prefix match
menangkap polling status, 429 pada klien yang sah). Store SQLite
dipatch ke file temporer per-test."""
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware import ratelimit
from app.middleware.ratelimit import RateLimitMiddleware


@pytest.fixture()
def client(tmp_path):
    old = ratelimit._DB_PATH
    ratelimit._DB_PATH = str(tmp_path / "rl_test.db")
    ratelimit._local.con = None  # paksa koneksi baru di path baru
    ratelimit._hits.clear()

    async def ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/api/v1/analyze-trend", ok, methods=["POST"]),
            Route("/api/v1/analyze-trend/{rid}", ok, methods=["GET"]),
        ],
        middleware=[Middleware(RateLimitMiddleware)],
    )
    yield TestClient(app)
    ratelimit._DB_PATH = old
    ratelimit._local.con = None


def test_get_status_polling_not_limited(client):
    for _ in range(15):
        r = client.get("/api/v1/analyze-trend/req-1")
        assert r.status_code == 200, "poller GET ter-limit — regresi"


def test_post_limit_still_enforced(client):
    for _ in range(10):
        assert client.post("/api/v1/analyze-trend").status_code == 200
    r = client.post("/api/v1/analyze-trend")
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_store_shared_across_connections(client):
    """State di SQLite → hit terhitung walau koneksi/thread berbeda
    (simulasi multi-worker)."""
    ratelimit._local.con = None
    for _ in range(10):
        assert client.post("/api/v1/analyze-trend").status_code == 200
    ratelimit._local.con = None  # 'proses' lain, DB sama
    assert client.post("/api/v1/analyze-trend").status_code == 429
