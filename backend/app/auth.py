"""Autentikasi lokal — JWT HS256 + bcrypt. Zero-cost, tanpa layanan eksternal.

Token diterbitkan oleh `POST /api/v1/auth/login` setelah verifikasi
`password_hash` di tabel `users`. Klaim: sub (user_id), inst
(institution_id), role, tier, iat, exp.

Catatan: `bcrypt` dipakai langsung (bukan passlib) — passlib 1.7.4 tidak
kompatibel dengan bcrypt ≥4.x (gagal deteksi backend).
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger("ala.auth")

_ALG = "HS256"


def hash_password(plain: str) -> str:
    # bcrypt maksimal 72 byte — potong eksplisit (bcrypt 5.x raise)
    return bcrypt.hashpw(plain.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode()[:72], hashed.encode())
    except Exception:
        return False


def create_token(
    user_id: uuid.UUID,
    institution_id: uuid.UUID | None,
    role: str,
    tier: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "inst": str(institution_id) if institution_id else None,
        "role": role,
        "tier": tier,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALG)


def decode_token(token: str) -> dict | None:
    """Kembalikan klaim valid atau None (kadaluarsa/signature salah)."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_ALG])
    except JWTError:
        return None
