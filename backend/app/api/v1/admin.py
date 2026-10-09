"""
Endpoint Konsol Super Admin — manajemen institusi, pengguna, fitur, dan tier.
Hanya dapat diakses oleh pengguna dengan role 'super_admin'.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.postgres import get_db
from app.middleware.tenant import TenantContext, get_tenant
from app.models.tenant import (
    Feature,
    Institution,
    InstitutionFeature,
    User,
)

logger = logging.getLogger("ala.api.admin")

router = APIRouter(prefix="/admin", tags=["super-admin"])

_TIERS = {"free", "premium_l1", "premium_l2"}


def _parse_uuid(value: str) -> uuid.UUID:
    """Parse UUID path param — 404 (bukan 500) jika tidak valid."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(404, "ID bukan UUID yang valid.")


def _require_super_admin(request: Request) -> TenantContext:
    """Dependency — tolak akses jika bukan Super Admin."""
    tenant = get_tenant(request)
    if not tenant.is_super_admin:
        raise HTTPException(
            status_code=403,
            detail="Akses ditolak. Hanya Super Admin yang dapat mengakses endpoint ini.",
        )
    return tenant


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InstitutionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    type: str = Field(..., pattern="^(kepolisian|kejaksaan|pengadilan)$")


class TierUpdate(BaseModel):
    tier_level: str


class UserCreate(BaseModel):
    institution_id: str
    name: str = Field(..., min_length=2, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)
    role: str = Field(..., pattern="^(super_admin|admin_instansi|penyidik|jaksa|hakim)$")
    tier_level: str = "free"
    badge_number: Optional[str] = None
    unit: Optional[str] = None


# ---------------------------------------------------------------------------
# Manajemen Institusi
# ---------------------------------------------------------------------------

@router.get("/institutions")
async def list_institutions(
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Daftar semua institusi yang terdaftar di platform."""
    rows = db.scalars(select(Institution).order_by(Institution.name)).all()
    return {"institutions": [{
        "id": str(i.id), "name": i.name, "type": i.type,
        "is_active": i.is_active,
        "user_count": len(i.users) if i.users else 0,
    } for i in rows]}


@router.post("/institutions", status_code=201)
async def create_institution(
    body: InstitutionCreate,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Buat institusi baru (POLRI, Kejaksaan, Mahkamah Agung, dll)."""
    inst = Institution(name=body.name, type=body.type)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return {"id": str(inst.id), "name": inst.name, "type": inst.type}


# ---------------------------------------------------------------------------
# Manajemen Pengguna Lintas-Institusi
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_all_users(
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Daftar semua pengguna di seluruh institusi."""
    rows = db.scalars(select(User).order_by(User.name).limit(500)).all()
    return {"users": [{
        "id": str(u.id), "name": u.name, "email": u.email,
        "role": u.role, "tier_level": u.tier_level,
        "institution_id": str(u.institution_id),
        "is_active": u.is_active,
    } for u in rows]}


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreate,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Buat pengguna APH baru — password disimpan sebagai hash bcrypt."""
    from app.auth import hash_password

    if body.tier_level not in _TIERS:
        raise HTTPException(400, f"tier_level harus salah satu: {_TIERS}")
    if not db.get(Institution, _parse_uuid(body.institution_id)):
        raise HTTPException(404, "Institusi tidak ditemukan.")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email sudah terdaftar.")
    user = User(
        institution_id=uuid.UUID(body.institution_id),
        name=body.name,
        email=email,
        password_hash=hash_password(body.password),
        role=body.role,
        tier_level=body.tier_level,
        badge_number=body.badge_number,
        unit=body.unit,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": str(user.id), "email": user.email, "role": user.role}


@router.post("/users/{user_id}/tier")
async def set_user_tier(
    user_id: str,
    body: TierUpdate,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Tetapkan tier akses pengguna (free, premium_l1, premium_l2)."""
    if body.tier_level not in _TIERS:
        raise HTTPException(400, f"tier_level harus salah satu: {_TIERS}")
    user = db.get(User, _parse_uuid(user_id))
    if not user:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    user.tier_level = body.tier_level
    db.commit()
    return {"user_id": user_id, "tier_level": user.tier_level}


# ---------------------------------------------------------------------------
# Manajemen Fitur & Tier Override
# ---------------------------------------------------------------------------

@router.get("/features")
async def list_features(
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Daftar semua fitur beserta saran tier dari AI."""
    rows = db.scalars(select(Feature).order_by(Feature.name)).all()
    return {"features": [{
        "id": str(f.id), "name": f.name, "slug": f.slug,
        "required_tier": f.required_tier,
        "is_ai_generated": f.is_ai_generated,
        "ai_complexity_score": f.ai_complexity_score,
        "ai_cuda_weight": f.ai_cuda_weight,
        "ai_suggested_tier": f.ai_suggested_tier,
        "admin_approved_tier": f.admin_approved_tier,
        "is_active": f.is_active,
    } for f in rows]}


@router.post("/features/{feature_id}/override-tier")
async def override_feature_tier(
    feature_id: str,
    body: TierUpdate,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Override tier fitur yang disarankan AI — keputusan akhir admin."""
    if body.tier_level not in _TIERS:
        raise HTTPException(400, f"tier_level harus salah satu: {_TIERS}")
    feature = db.get(Feature, _parse_uuid(feature_id))
    if not feature:
        raise HTTPException(404, "Fitur tidak ditemukan.")
    feature.admin_approved_tier = body.tier_level
    feature.required_tier = body.tier_level
    db.commit()
    return {"feature_id": feature_id,
            "required_tier": feature.required_tier}


@router.post("/features/{feature_id}/toggle")
async def toggle_feature(
    feature_id: str,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Aktivasi/deaktivasi fitur secara global."""
    feature = db.get(Feature, _parse_uuid(feature_id))
    if not feature:
        raise HTTPException(404, "Fitur tidak ditemukan.")
    feature.is_active = not feature.is_active
    db.commit()
    return {"feature_id": feature_id, "is_active": feature.is_active}


# ---------------------------------------------------------------------------
# Pemetaan Institusi ↔ Fitur
# ---------------------------------------------------------------------------

@router.get("/institution-features/{institution_id}")
async def list_institution_features(
    institution_id: str,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Daftar fitur yang diaktifkan untuk institusi tertentu."""
    inst_uuid = _parse_uuid(institution_id)
    rows = db.scalars(
        select(InstitutionFeature).where(
            InstitutionFeature.institution_id == inst_uuid)
    ).all()
    return {"institution_id": institution_id, "features": [{
        "feature_id": str(m.feature_id), "is_enabled": m.is_enabled,
    } for m in rows]}


@router.post("/institution-features/{institution_id}/{feature_id}")
async def assign_feature_to_institution(
    institution_id: str,
    feature_id: str,
    tenant: TenantContext = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    """Tetapkan/aktifkan fitur ke institusi tertentu."""
    inst_uuid = _parse_uuid(institution_id)
    feat_uuid = _parse_uuid(feature_id)
    existing = db.scalar(
        select(InstitutionFeature).where(
            InstitutionFeature.institution_id == inst_uuid,
            InstitutionFeature.feature_id == feat_uuid,
        )
    )
    if existing:
        existing.is_enabled = True
    else:
        db.add(InstitutionFeature(
            institution_id=inst_uuid,
            feature_id=feat_uuid,
            is_enabled=True,
            enabled_by=tenant.user_id,
        ))
    db.commit()
    return {"institution_id": institution_id, "feature_id": feature_id,
            "is_enabled": True}
