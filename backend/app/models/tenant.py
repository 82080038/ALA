"""
Model multi-tenant — Institusi, Pengguna, Kategori Fitur, Fitur.
Mendukung arsitektur B2B SaaS lintas-institusi (POLRI, Kejaksaan, Pengadilan).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from app.database.postgres import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Institusi
# ---------------------------------------------------------------------------

class Institution(Base):
    """Institusi penegak hukum yang dilayani platform."""

    __tablename__ = "institutions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)  # POLRI, Kejaksaan, Mahkamah Agung
    type = Column(String(50), nullable=False)    # kepolisian, kejaksaan, pengadilan
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relasi
    users = relationship("User", back_populates="institution", lazy="selectin")
    institution_features = relationship(
        "InstitutionFeature", back_populates="institution", lazy="selectin"
    )


# ---------------------------------------------------------------------------
# Pengguna
# ---------------------------------------------------------------------------

class User(Base):
    """Pengguna dengan ikatan institusi dan tier akses."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id = Column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False
    )
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    badge_number = Column(String(50), unique=True, nullable=True)  # NRP/badge APH
    unit = Column(String(255), nullable=True)                      # unit kerja
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    # super_admin, admin_instansi, penyidik, jaksa, hakim
    tier_level = Column(String(20), default="free")
    # free, premium_l1, premium_l2
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relasi
    institution = relationship("Institution", back_populates="users")


# ---------------------------------------------------------------------------
# Kategori Fitur (domain hukum)
# ---------------------------------------------------------------------------

class FeatureCategory(Base):
    """Kategori domain hukum untuk mengelompokkan fitur."""

    __tablename__ = "feature_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)  # Pidum, Tipikor, Cyber, Narkotika
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    # Relasi
    features = relationship("Feature", back_populates="category", lazy="selectin")


# ---------------------------------------------------------------------------
# Fitur Individual
# ---------------------------------------------------------------------------

class Feature(Base):
    """Fitur/alat individual — bisa dibuat manual atau dihasilkan AI."""

    __tablename__ = "features"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id = Column(
        UUID(as_uuid=True), ForeignKey("feature_categories.id"), nullable=False
    )
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    # Tier & akses
    required_tier = Column(String(20), default="free")
    # free, premium_l1, premium_l2

    # Metadata AI clustering
    is_ai_generated = Column(Boolean, default=False)
    ai_complexity_score = Column(Float, nullable=True)   # 0.0–1.0
    ai_cuda_weight = Column(Float, nullable=True)        # estimasi beban GPU
    ai_suggested_tier = Column(String(20), nullable=True)
    admin_approved_tier = Column(String(20), nullable=True)

    is_active = Column(Boolean, default=True)
    telemetry_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    # Relasi
    category = relationship("FeatureCategory", back_populates="features")
    institution_features = relationship(
        "InstitutionFeature", back_populates="feature", lazy="selectin"
    )


# ---------------------------------------------------------------------------
# Pemetaan Fitur ↔ Institusi (dikontrol Super Admin)
# ---------------------------------------------------------------------------

class InstitutionFeature(Base):
    """Pemetaan fitur ke institusi — hanya Super Admin yang dapat mengubah."""

    __tablename__ = "institution_features"
    __table_args__ = (
        UniqueConstraint("institution_id", "feature_id", name="uq_inst_feature"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id = Column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False
    )
    feature_id = Column(
        UUID(as_uuid=True), ForeignKey("features.id"), nullable=False
    )
    is_enabled = Column(Boolean, default=True)
    enabled_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    enabled_at = Column(DateTime(timezone=True), default=_utcnow)

    # Relasi
    institution = relationship("Institution", back_populates="institution_features")
    feature = relationship("Feature", back_populates="institution_features")
