"""Uji rate limiter — aturan per-method: poller GET /analyze-trend/{id}
tidak boleh menghabiskan kuota POST analyze-trend (bug: prefix match
menangkap polling status, 429 pada klien yang sah)."""
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware import ratelimit
from app.middleware.ratelimit import RateLimitMiddleware


def _app() -> TestClient:
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
    return TestClient(app)


def test_get_status_polling_not_limited():
    c = _app()
    for _ in range(15):
        r = c.get("/api/v1/analyze-trend/req-1")
        assert r.status_code == 200, "poller GET ter-limit — regresi"


def test_post_limit_still_enforced():
    c = _app()
    for _ in range(10):
        assert c.post("/api/v1/analyze-trend").status_code == 200
    r = c.post("/api/v1/analyze-trend")
    assert r.status_code == 429
    assert "Retry-After" in r.headers
