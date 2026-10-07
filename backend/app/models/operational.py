"""
Model ORM untuk tabel operasional & registri ALCD.

Scope tenancy (lihat DATABASE_SCHEMA.md §0):
- TENANT (institution_id wajib + RLS): Case, AiAuditLog
- GLOBAL (tanpa institution_id): KnowledgeRegistry, OntologyNode, SelfEvalLog

Catatan: `scripts/init_db.py` (DDL mentah) adalah sumber kebenaran skema.
Model di sini untuk kemudahan query SQLAlchemy — jaga tetap selaras.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.postgres import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# TENANT — Kasus
# ---------------------------------------------------------------------------

class Case(Base):
    """Kasus investigasi — data operasional tenant (RLS via institution_id)."""

    __tablename__ = "cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id = Column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False
    )
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        String(50),
        nullable=False,
        default="open",
    )
    priority = Column(String(20), default="medium")
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    case_number = Column(String(100), unique=True, nullable=True)
    crime_type = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'closed', 'archived')",
            name="ck_cases_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_cases_priority",
        ),
    )


# ---------------------------------------------------------------------------
# TENANT — Immutable Audit Log (append-only)
# ---------------------------------------------------------------------------

class AiAuditLog(Base):
    """Log audit aktivitas AI — immutable, tenant-scoped, menyimpan
    chain-of-custody bukti digital (SHA-256 before/after)."""

    __tablename__ = "ai_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # nullable — aksi sistem/super_admin boleh tanpa institusi
    institution_id = Column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=True
    )
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    request_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(50), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    query_input = Column(Text, nullable=True)
    action_taken = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    crime_trend = Column(JSONB, nullable=True)
    legal_articles = Column(JSONB, nullable=True)
    code_generated = Column(Text, nullable=True)
    execution_result = Column(JSONB, nullable=True)

    # Chain of custody (kepatuhan KUHAP) — hash bukti sebelum & sesudah
    evidence_sha256_before = Column(String(64), nullable=True)
    evidence_sha256_after = Column(String(64), nullable=True)

    metadata_ = Column("metadata", JSONB, default=dict)

    __table_args__ = (
        CheckConstraint(
            "action IN ('analyze', 'approve', 'reject', 'execute', 'error')",
            name="ck_audit_action",
        ),
    )


# ---------------------------------------------------------------------------
# GLOBAL — Registri pengetahuan ALCD (tanpa institution_id)
# ---------------------------------------------------------------------------

class KnowledgeRegistry(Base):
    """Registri semua UU yang ditemukan & di-ingest ALCD — GLOBAL."""

    __tablename__ = "knowledge_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    law_name = Column(String(255), nullable=False)
    law_number = Column(String(100), nullable=True)
    law_category = Column(String(50), nullable=False)
    source_url = Column(Text, nullable=False)
    source_domain = Column(String(255), nullable=True)
    discovery_date = Column(DateTime(timezone=True), default=_utcnow)
    ingestion_status = Column(String(50), nullable=False, default="pending")
    chunk_count = Column(Integer, default=0)
    article_count = Column(Integer, default=0)
    last_verified = Column(DateTime(timezone=True), nullable=True)
    verification_score = Column(Float, default=0.0)
    gaps_identified = Column(ARRAY(Text), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class OntologyNode(Base):
    """Node ontologi pengetahuan yang dirumuskan ALCD — GLOBAL."""

    __tablename__ = "ontology_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(255), nullable=False)
    subcategory = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)
    priority = Column(Integer, nullable=False, default=1)
    status = Column(String(50), nullable=False, default="pending")
    parent_id = Column(UUID(as_uuid=True), ForeignKey("ontology_nodes.id"), nullable=True)
    knowledge_score = Column(Float, default=0.0)
    laws_ingested = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    parent = relationship("OntologyNode", remote_side=[id])


class SelfEvalLog(Base):
    """Log evaluasi diri ALCD (pertanyaan uji + skor) — GLOBAL."""

    __tablename__ = "self_eval_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    ontology_node_id = Column(
        UUID(as_uuid=True), ForeignKey("ontology_nodes.id"), nullable=True
    )
    question = Column(Text, nullable=False)
    generated_answer = Column(Text, nullable=True)
    answer_quality = Column(Float, nullable=False)
    gap_description = Column(Text, nullable=True)
    remediation_action = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)
