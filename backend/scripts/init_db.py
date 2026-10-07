"""
Inisialisasi skema PostgreSQL untuk ALA.

Membuat SEMUA tabel dalam keadaan KOSONG — tanpa data pra-muat.
Basis pengetahuan hukum dipopulasi secara otonom oleh modul ALCD.

Penggunaan:
    # Dari dalam kontainer API (working dir /app):
    docker compose exec api python scripts/init_db.py

    # Dari host (dengan DATABASE_URL yang sesuai):
    python backend/scripts/init_db.py
"""
import os
import sys
from pathlib import Path

# Pastikan paket `app` dapat diimpor saat skrip dijalankan langsung
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database.postgres import Base  # noqa: E402
from app.models import tenant as _tenant_models  # noqa: E402, F401

# init_db butuh DDL → pakai koneksi ADMIN (superuser), bukan ala_app.
# Runtime aplikasi tetap memakai database_url (ala_app, tunduk RLS).
engine = create_engine(
    settings.database_admin_url or settings.database_url
)

# Tabel yang dikelola di luar model ORM multi-tenant.
# Mengikuti definisi di DATABASE_SCHEMA.md.
# Scope: cases & ai_audit_logs = TENANT (institution_id wajib);
# knowledge_registry, ontology_nodes, self_eval_logs = GLOBAL (tanpa tenant).
_EXTRA_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'closed', 'archived')),
    priority        VARCHAR(20) DEFAULT 'medium'
                    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    assigned_to     UUID REFERENCES users(id),
    case_number     VARCHAR(100) UNIQUE,
    crime_type      VARCHAR(255),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at       TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_assigned ON cases(assigned_to);
CREATE INDEX IF NOT EXISTS idx_cases_crime_type ON cases(crime_type);
CREATE INDEX IF NOT EXISTS idx_cases_institution ON cases(institution_id);

CREATE TABLE IF NOT EXISTS ai_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- nullable: mencakup aksi sistem/super_admin tanpa institusi;
    -- baris tenant selalu membawa institution_id
    institution_id  UUID REFERENCES institutions(id),
    timestamp       TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    request_id      UUID NOT NULL,
    action          VARCHAR(50) NOT NULL
                    CHECK (action IN ('analyze', 'approve', 'reject', 'execute', 'error')),
    user_id         UUID REFERENCES users(id),
    case_id         UUID REFERENCES cases(id),
    query_input     TEXT,
    action_taken    TEXT NOT NULL,
    rationale       TEXT,
    crime_trend     JSONB,
    legal_articles  JSONB,
    code_generated  TEXT,
    execution_result JSONB,
    evidence_sha256_before CHAR(64),
    evidence_sha256_after  CHAR(64),
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON ai_audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON ai_audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_user ON ai_audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_request ON ai_audit_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_institution ON ai_audit_logs(institution_id);

CREATE TABLE IF NOT EXISTS knowledge_registry (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    law_name            VARCHAR(255) NOT NULL,
    law_number          VARCHAR(100),
    law_category        VARCHAR(50) NOT NULL
                        CHECK (law_category IN ('materiil', 'formil', 'regulasi', 'yurisprudensi')),
    source_url          TEXT NOT NULL,
    source_domain       VARCHAR(255),
    discovery_date      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ingestion_status    VARCHAR(50) NOT NULL DEFAULT 'pending'
                        CHECK (ingestion_status IN ('pending', 'downloading', 'parsing',
                                                    'embedding', 'completed', 'failed', 'verified')),
    chunk_count         INTEGER DEFAULT 0,
    article_count       INTEGER DEFAULT 0,
    last_verified       TIMESTAMP WITH TIME ZONE,
    verification_score  FLOAT DEFAULT 0.0,
    gaps_identified     TEXT[],
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kr_law_name ON knowledge_registry(law_name);
CREATE INDEX IF NOT EXISTS idx_kr_category ON knowledge_registry(law_category);
CREATE INDEX IF NOT EXISTS idx_kr_status ON knowledge_registry(ingestion_status);

CREATE TABLE IF NOT EXISTS ontology_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category        VARCHAR(255) NOT NULL,
    subcategory     VARCHAR(255),
    description     TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 5),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'completed', 'gap_detected')),
    parent_id       UUID REFERENCES ontology_nodes(id),
    knowledge_score FLOAT DEFAULT 0.0,
    laws_ingested   INTEGER DEFAULT 0,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onto_category ON ontology_nodes(category);
CREATE INDEX IF NOT EXISTS idx_onto_status ON ontology_nodes(status);
CREATE INDEX IF NOT EXISTS idx_onto_parent ON ontology_nodes(parent_id);

CREATE TABLE IF NOT EXISTS self_eval_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ontology_node_id    UUID REFERENCES ontology_nodes(id),
    question            TEXT NOT NULL,
    generated_answer    TEXT,
    answer_quality      FLOAT NOT NULL CHECK (answer_quality BETWEEN 0.0 AND 1.0),
    gap_description     TEXT,
    remediation_action  TEXT,
    resolved            BOOLEAN DEFAULT FALSE,
    resolved_at         TIMESTAMP WITH TIME ZONE,
    metadata            JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_selfeval_timestamp ON self_eval_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_selfeval_node ON self_eval_logs(ontology_node_id);
CREATE INDEX IF NOT EXISTS idx_selfeval_quality ON self_eval_logs(answer_quality);
"""

# Migrasi idempotent untuk DB yang sudah ada (kolom tenant & custody baru).
_MIGRATE_COLUMNS_DDL = """
ALTER TABLE cases ADD COLUMN IF NOT EXISTS institution_id UUID REFERENCES institutions(id);
ALTER TABLE ai_audit_logs ADD COLUMN IF NOT EXISTS institution_id UUID REFERENCES institutions(id);
ALTER TABLE ai_audit_logs ADD COLUMN IF NOT EXISTS evidence_sha256_before CHAR(64);
ALTER TABLE ai_audit_logs ADD COLUMN IF NOT EXISTS evidence_sha256_after CHAR(64);
CREATE INDEX IF NOT EXISTS idx_cases_institution ON cases(institution_id);
CREATE INDEX IF NOT EXISTS idx_audit_institution ON ai_audit_logs(institution_id);
"""

# Row-Level Security — HANYA untuk data operasional tenant.
# Pengetahuan hukum (knowledge_registry, ontology_nodes, self_eval_logs,
# ChromaDB indonesian_laws, Neo4j LegalArticle) tetap GLOBAL.
# Aplikasi meng-set GUC `app.tenant_id` per request/transaction.
_RLS_DDL = """
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'cases' AND policyname = 'tenant_isolation'
    ) THEN
        -- GUC kosong (super_admin/sistem) → akses penuh; GUC terisi →
        -- hanya baris milik tenant tersebut
        CREATE POLICY tenant_isolation ON cases
            USING (NULLIF(current_setting('app.tenant_id', true), '') IS NULL
                   OR institution_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (NULLIF(current_setting('app.tenant_id', true), '') IS NULL
                        OR institution_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    END IF;
END $$;

ALTER TABLE ai_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_audit_logs FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'ai_audit_logs' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON ai_audit_logs
            USING (NULLIF(current_setting('app.tenant_id', true), '') IS NULL
                   OR institution_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (NULLIF(current_setting('app.tenant_id', true), '') IS NULL
                        OR institution_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    END IF;
END $$;
"""

# Role aplikasi non-superuser — WAJIB agar RLS benar-benar ditegakkan.
# (ala_user adalah superuser dari POSTGRES_USER → selalu bypass RLS.)
# Password diambil dari env APP_DB_PASSWORD / POSTGRES_PASSWORD.
_APP_ROLE_DDL = """
DO $$
DECLARE
    app_pass TEXT := NULLIF(current_setting('app.db_password', true), '');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ala_app') THEN
        EXECUTE format(
            'CREATE ROLE ala_app LOGIN PASSWORD %L', app_pass);
    END IF;
END $$;

GRANT CONNECT ON DATABASE ala_db TO ala_app;
GRANT USAGE ON SCHEMA public TO ala_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ala_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ala_app;
"""

# Immutability audit log — cabut izin UPDATE/DELETE dari user aplikasi.
# Append-only: INSERT/SELECT diizinkan, mutasi histori ditolak.
# Best-effort: diabaikan jika role sudah dicabut.
_AUDIT_REVOKE_DDL = """
REVOKE UPDATE, DELETE ON ai_audit_logs FROM ala_user;
REVOKE UPDATE, DELETE ON ai_audit_logs FROM ala_app;
"""


def init_db() -> None:
    """Buat semua tabel (kosong) dan terapkan constraint keamanan."""
    print(f"Menghubungkan ke: "
          f"{settings.database_admin_url or settings.database_url}")

    # Password untuk role aplikasi non-superuser
    app_db_password = os.environ.get(
        "APP_DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD", "")
    if not app_db_password:
        print("[PERINGATAN] APP_DB_PASSWORD/POSTGRES_PASSWORD kosong — "
              "role ala_app akan dibuat tanpa password jika belum ada")

    # 0. Role aplikasi non-superuser (syarat RLS bekerja)
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.db_password', :pw, false)"),
            {"pw": app_db_password},
        )
        conn.execute(text(_APP_ROLE_DDL))
    print("[OK] Role aplikasi 'ala_app' (non-superuser) siap")

    # 1. Tabel ORM multi-tenant (institutions, users, feature_categories,
    #    features, institution_features)
    Base.metadata.create_all(bind=engine)
    print("[OK] Tabel multi-tenant dibuat (institutions, users, "
          "feature_categories, features, institution_features)")

    # 2. Tabel operasional & ALCD via DDL mentah
    with engine.begin() as conn:
        conn.execute(text(_EXTRA_TABLES_DDL))
    print("[OK] Tabel operasional dibuat (cases, ai_audit_logs, "
          "knowledge_registry, ontology_nodes, self_eval_logs)")

    # 3. Migrasi kolom baru pada tabel lama (idempotent)
    with engine.begin() as conn:
        conn.execute(text(_MIGRATE_COLUMNS_DDL))
    print("[OK] Migrasi kolom tenant + chain-of-custody diterapkan")

    # 4. Row-Level Security untuk data operasional tenant
    try:
        with engine.begin() as conn:
            conn.execute(text(_RLS_DDL))
        print("[OK] RLS aktif pada cases & ai_audit_logs "
              "(pengetahuan hukum tetap GLOBAL)")
    except Exception as exc:
        print(f"[INFO] RLS dilewati ({exc}) — terapkan manual bila perlu")

    # 5. Tegakkan immutability audit log
    try:
        with engine.begin() as conn:
            conn.execute(text(_AUDIT_REVOKE_DDL))
        print("[OK] REVOKE UPDATE/DELETE pada ai_audit_logs diterapkan")
    except Exception as exc:
        print(f"[INFO] REVOKE dilewati ({exc}) — terapkan manual bila perlu")

    print("Selesai. Semua tabel dibuat KOSONG — data hukum diisi oleh ALCD.")


if __name__ == "__main__":
    init_db()
