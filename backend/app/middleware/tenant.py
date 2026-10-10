"""
Middleware Isolasi Tenant — menyuntikkan konteks tenant ke setiap request.

Mekanisme:
1. Ekstrak institution_id dan user role dari token JWT (header Authorization).
2. Simpan ke request.state agar tersedia di seluruh endpoint.
3. Super Admin (`role = 'super_admin'`) dapat mengakses semua tenant.
4. Pengguna biasa hanya melihat data dari institusi mereka sendiri.

Fase 2: JWT HS256 aktif (header `Authorization: Bearer ...` dari
`POST /api/v1/auth/login`). Header `X-Institution-ID`/`X-User-Role`
hanya dihormati bila `AUTH_DEV_HEADERS=true` — fallback pengembangan
lokal, WAJIB dimatikan di deployment nyata.
"""
import logging
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_context_budget

logger = logging.getLogger("ala.middleware.tenant")


class TenantContext:
    """Konteks tenant yang disuntikkan ke setiap request."""

    def __init__(
        self,
        institution_id: UUID | None = None,
        user_id: UUID | None = None,
        user_role: str = "anonymous",
        tier_level: str = "free",
    ):
        self.institution_id = institution_id
        self.user_id = user_id
        self.user_role = user_role
        self.tier_level = tier_level
        # Token tiering SaaS: batas konteks efektif = min(tier_cap, ceiling HIRO)
        self.token_budget = get_context_budget(tier_level)

    @property
    def is_super_admin(self) -> bool:
        return self.user_role == "super_admin"

    @property
    def is_authenticated(self) -> bool:
        return self.user_role != "anonymous"

    @property
    def context_token_budget(self) -> int:
        """Batas num_ctx efektif untuk query pengguna ini."""
        return self.token_budget["num_ctx"]


# Path yang tidak memerlukan konteks tenant
_PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

# Nilai role & tier yang diizinkan (menolak nilai arbitrer dari header)
_ALLOWED_ROLES = frozenset(
    {"anonymous", "super_admin", "admin_instansi", "penyidik", "jaksa", "hakim"}
)
_ALLOWED_TIERS = frozenset({"free", "premium_l1", "premium_l2"})


class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """Middleware yang memastikan isolasi data antar-institusi."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Path publik — lewati tanpa konteks tenant
        if path in _PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            request.state.tenant = TenantContext()
            return await call_next(request)

        # --- Jalur utama: JWT Bearer ---
        authz = request.headers.get("Authorization", "")
        if authz.startswith("Bearer "):
            from app.auth import decode_token

            claims = decode_token(authz[7:].strip())
            if not claims:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token tidak valid atau kadaluarsa."},
                )
            try:
                tenant = TenantContext(
                    institution_id=(
                        UUID(claims["inst"]) if claims.get("inst") else None
                    ),
                    user_id=UUID(claims["sub"]) if claims.get("sub") else None,
                    user_role=claims.get("role", "anonymous"),
                    tier_level=claims.get("tier", "free"),
                )
                if tenant.user_role not in _ALLOWED_ROLES:
                    raise ValueError("role")
                # Klaim tier divalidasi sama ketatnya dengan jalur header
                # dev — klaim arbitrer (token lama/bug) tidak boleh lolos.
                if tenant.tier_level not in _ALLOWED_TIERS:
                    raise ValueError("tier")
                request.state.tenant = tenant
                return await call_next(request)
            except (ValueError, KeyError):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Klaim token tidak valid."},
                )

        # --- Fallback dev (AUTH_DEV_HEADERS=true): header pengujian ---
        from app.config import settings

        if not settings.auth_dev_headers:
            request.state.tenant = TenantContext()
            return await call_next(request)

        raw_institution_id = request.headers.get("X-Institution-ID")
        raw_user_id = request.headers.get("X-User-ID")
        user_role = request.headers.get("X-User-Role", "anonymous")
        tier_level = request.headers.get("X-Tier-Level", "free")

        if user_role not in _ALLOWED_ROLES:
            return JSONResponse(
                status_code=400,
                content={"detail": "X-User-Role tidak dikenal."},
            )
        if tier_level not in _ALLOWED_TIERS:
            return JSONResponse(
                status_code=400,
                content={"detail": "X-Tier-Level tidak dikenal."},
            )

        institution_id = None
        user_id = None

        if raw_institution_id:
            try:
                institution_id = UUID(raw_institution_id)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "X-Institution-ID bukan UUID yang valid."},
                )

        if raw_user_id:
            try:
                user_id = UUID(raw_user_id)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "X-User-ID bukan UUID yang valid."},
                )

        tenant = TenantContext(
            institution_id=institution_id,
            user_id=user_id,
            user_role=user_role,
            tier_level=tier_level,
        )
        request.state.tenant = tenant

        return await call_next(request)


def get_tenant(request: Request) -> TenantContext:
    """Dependency injection — ambil konteks tenant dari request."""
    return getattr(request.state, "tenant", TenantContext())
