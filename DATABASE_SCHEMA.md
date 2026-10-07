# 🗄️ Skema Database — Autonomous Legal Agent (ALA)

> Dokumen ini menjabarkan skema lengkap untuk ketiga database yang digunakan dalam arsitektur Polyglot Persistence ALA.

---

## 0. Model Tenancy: Pengetahuan GLOBAL vs Data Operasional TENANT

ALA memisahkan data menjadi dua scope yang **TIDAK BOLEH** dicampur:

| Data | Scope | Isolasi |
|------|-------|---------|
| Hukum positif Indonesia (KUHP, KUHAP, UU ITE, UU Tipikor, UU Narkotika, UU TPPU, Perkap, Perja, Putusan MA) — koleksi ChromaDB `indonesian_laws`, node Neo4j `LegalArticle` + relasi lintas-UU, tabel `knowledge_registry` / `ontology_nodes` / `self_eval_logs` | **GLOBAL** | Satu namespace bersama untuk SEMUA institusi. **TANPA** `institution_id` — mencegah duplikasi data dan inkonsistensi basis pengetahuan |
| `CrimeTrend` (tren kejahatan dari sumber internet publik) | **GLOBAL** | Intelijen publik dibagikan lintas institusi |
| `cases` (kasus), `ai_audit_logs` (investigative logs), skrip AI kustom hasil generate, sesi pengguna | **TENANT** | Wajib `institution_id` — difilter via Row-Level Security PostgreSQL |
| Node Neo4j entitas kasus: `Suspect`, `BankAccount`, `IPAddress`, `PhoneNumber` | **TENANT** | Setiap node wajib properti `institution_id`; semua Cypher query difilter berdasarkan tenant context |

> **Aturan Emas:** ALCD menulis pengetahuan hukum ke namespace GLOBAL. Tenant isolation via `institution_id` **HANYA** diterapkan pada data operasional: Cases, Investigative Logs, Custom AI-Generated Scripts, dan User Sessions.

### Tier Entitlements (`users.tier_level`)

Setiap user memiliki `tier_level` yang menentukan batas token konteks per query:

| `tier_level` | Batas Konteks (`num_ctx`) | `num_predict` Maks |
|--------------|---------------------------|--------------------|
| `free` | 2.048 token | 512 |
| `premium_l1` | 8.192 token | 2.048 |
| `premium_l2` | 16.384 token | 4.096 |

Nilai efektif selalu `min(tier_cap, hardware_ceiling)` — middleware FastAPI mengklamp ke ceiling VRAM yang dihitung HIRO.

---

## 1. PostgreSQL — Relational Database

### 1.1 Tabel `users`

Menyimpan data personel Aparat Penegak Hukum (APH) yang memiliki akses ke sistem.

Sistem menggunakan model **multi-tenant** — setiap pengguna terikat pada satu `institution`. Tabel `institutions`, `feature_categories`, `features`, dan `institution_features` dikelola oleh ORM SQLAlchemy di `backend/app/models/tenant.py`.

```sql
CREATE TABLE institutions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,      -- POLRI, Kejaksaan, Mahkamah Agung
    type        VARCHAR(50) NOT NULL,       -- kepolisian, kejaksaan, pengadilan
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    badge_number    VARCHAR(50) UNIQUE,
    role            VARCHAR(50) NOT NULL CHECK (role IN
                    ('super_admin', 'admin_instansi', 'penyidik', 'jaksa', 'hakim')),
    unit            VARCHAR(255),
    tier_level      VARCHAR(20) DEFAULT 'free',   -- free, premium_l1, premium_l2
    password_hash   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_users_badge ON users(badge_number);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_institution ON users(institution_id);
```

| Kolom | Tipe | Constraint | Deskripsi |
|-------|------|-----------|-----------|
| `id` | `UUID` | PK, auto-generated | Identifier unik |
| `institution_id` | `UUID` | FK → institutions, NOT NULL | Institusi pemilik user (isolasi tenant) |
| `name` | `VARCHAR(255)` | NOT NULL | Nama lengkap personel |
| `email` | `VARCHAR(255)` | UNIQUE, NOT NULL | Email resmi |
| `badge_number` | `VARCHAR(50)` | UNIQUE | Nomor badge/NRP |
| `role` | `VARCHAR(50)` | NOT NULL, CHECK | `super_admin`, `admin_instansi`, `penyidik`, `jaksa`, `hakim` |
| `unit` | `VARCHAR(255)` | — | Unit kerja (mis. Cyber Crime) |
| `tier_level` | `VARCHAR(20)` | DEFAULT 'free' | Tier akses fitur: `free`, `premium_l1`, `premium_l2` |
| `password_hash` | `VARCHAR(255)` | NOT NULL | Hash password (bcrypt) |
| `is_active` | `BOOLEAN` | DEFAULT TRUE | Status aktif akun |
| `created_at` | `TIMESTAMPTZ` | DEFAULT NOW() | Waktu pembuatan |
| `updated_at` | `TIMESTAMPTZ` | DEFAULT NOW() | Waktu update terakhir |

### 1.2 Tabel `cases`

Menyimpan data kasus yang sedang ditangani.

```sql
CREATE TABLE cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),  -- ISOLASI TENANT
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

CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_assigned ON cases(assigned_to);
CREATE INDEX idx_cases_crime_type ON cases(crime_type);
CREATE INDEX idx_cases_institution ON cases(institution_id);
```

| Kolom | Tipe | Constraint | Deskripsi |
|-------|------|-----------|-----------|
| `id` | `UUID` | PK | Identifier unik |
| `institution_id` | `UUID` | FK → institutions, NOT NULL | Pemilik kasus — isolasi tenant (RLS) |
| `title` | `VARCHAR(500)` | NOT NULL | Judul kasus |
| `description` | `TEXT` | — | Deskripsi detail kasus |
| `status` | `VARCHAR(50)` | CHECK | Status: `open`, `in_progress`, `closed`, `archived` |
| `priority` | `VARCHAR(20)` | CHECK | Prioritas: `low`, `medium`, `high`, `critical` |
| `assigned_to` | `UUID` | FK → users | Personel yang ditugaskan |
| `case_number` | `VARCHAR(100)` | UNIQUE | Nomor kasus resmi |
| `crime_type` | `VARCHAR(255)` | — | Jenis kejahatan |
| `created_at` | `TIMESTAMPTZ` | DEFAULT NOW() | Waktu pembuatan |
| `updated_at` | `TIMESTAMPTZ` | DEFAULT NOW() | Waktu update terakhir |
| `closed_at` | `TIMESTAMPTZ` | — | Waktu kasus ditutup |

### 1.3 Tabel `ai_audit_logs`

**Immutable audit log** — mencatat seluruh aktivitas AI untuk akuntabilitas. Tabel ini bersifat **append-only** (tidak boleh UPDATE atau DELETE) dan **tenant-scoped** (setiap baris terikat `institution_id`).

Tabel ini juga menyimpan **chain-of-custody evidence** (KUHAP): checksum SHA-256 file bukti yang dihitung oleh kode yang digenerate AI — sebelum dan sesudah pemrosesan — sebagai jaminan integritas data di pengadilan.

```sql
CREATE TABLE ai_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id),  -- ISOLASI TENANT
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
    evidence_sha256_before CHAR(64),   -- Chain of custody: hash SHA-256 file bukti SEBELUM proses
    evidence_sha256_after  CHAR(64),   -- Chain of custody: hash SHA-256 file bukti SESUDAH proses
    metadata        JSONB DEFAULT '{}' -- Termasuk tier_level & clamp token (num_ctx) yang diterapkan
);

-- Immutable: Revoke UPDATE and DELETE
-- REVOKE UPDATE, DELETE ON ai_audit_logs FROM ala_user;

CREATE INDEX idx_audit_timestamp ON ai_audit_logs(timestamp);
CREATE INDEX idx_audit_action ON ai_audit_logs(action);
CREATE INDEX idx_audit_user ON ai_audit_logs(user_id);
CREATE INDEX idx_audit_request ON ai_audit_logs(request_id);
CREATE INDEX idx_audit_institution ON ai_audit_logs(institution_id);
```

| Kolom | Tipe | Constraint | Deskripsi |
|-------|------|-----------|-----------|
| `id` | `UUID` | PK | Identifier unik |
| `institution_id` | `UUID` | FK → institutions, NOT NULL | Pemilik log — isolasi tenant (RLS) |
| `timestamp` | `TIMESTAMPTZ` | NOT NULL | Waktu aktivitas |
| `request_id` | `UUID` | NOT NULL | ID request pipeline |
| `action` | `VARCHAR(50)` | CHECK | Jenis aksi: `analyze`, `approve`, `reject`, `execute`, `error` |
| `user_id` | `UUID` | FK → users | User yang melakukan aksi |
| `case_id` | `UUID` | FK → cases | Kasus terkait (opsional) |
| `query_input` | `TEXT` | — | Query input dari user |
| `action_taken` | `TEXT` | NOT NULL | Deskripsi aksi yang diambil |
| `rationale` | `TEXT` | — | Alasan/justifikasi AI |
| `crime_trend` | `JSONB` | — | Data tren kejahatan (JSON) |
| `legal_articles` | `JSONB` | — | Pasal hukum relevan (JSON) |
| `code_generated` | `TEXT` | — | Kode yang digenerate AI (skrip kustom tenant) |
| `execution_result` | `JSONB` | — | Hasil eksekusi kode (JSON) |
| `evidence_sha256_before` | `CHAR(64)` | — | SHA-256 file bukti sebelum pemrosesan — wajib jika skrip menyentuh evidence |
| `evidence_sha256_after` | `CHAR(64)` | — | SHA-256 file bukti sesudah pemrosesan — harus identik dengan `_before` |
| `metadata` | `JSONB` | DEFAULT `{}` | Metadata tambahan (mis. `tier_level`, `num_ctx` efektif) |

### 1.4 Tabel `knowledge_registry` *(NEW — ALCD Module — SCOPE: GLOBAL)*

Mencatat setiap undang-undang yang ditemukan dan di-ingest secara otonom oleh ALCD. **GLOBAL** — satu registri untuk seluruh platform, tanpa `institution_id`.

```sql
CREATE TABLE knowledge_registry (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    law_name            VARCHAR(255) NOT NULL,
    law_number          VARCHAR(100),
    law_category        VARCHAR(50) NOT NULL CHECK (law_category IN ('materiil', 'formil', 'regulasi', 'yurisprudensi')),
    source_url          TEXT NOT NULL,
    source_domain       VARCHAR(255),
    discovery_date      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ingestion_status    VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (ingestion_status IN ('pending', 'downloading', 'parsing', 'embedding', 'completed', 'failed', 'verified')),
    chunk_count         INTEGER DEFAULT 0,
    article_count       INTEGER DEFAULT 0,
    last_verified       TIMESTAMP WITH TIME ZONE,
    verification_score  FLOAT DEFAULT 0.0,
    gaps_identified     TEXT[],
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_kr_law_name ON knowledge_registry(law_name);
CREATE INDEX idx_kr_category ON knowledge_registry(law_category);
CREATE INDEX idx_kr_status ON knowledge_registry(ingestion_status);
```

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `law_name` | `VARCHAR(255)` | Nama UU (e.g., "KUHP", "UU TPPU") |
| `law_number` | `VARCHAR(100)` | Nomor UU (e.g., "No. 8/2010") |
| `law_category` | `VARCHAR(50)` | Kategori: materiil, formil, regulasi, yurisprudensi |
| `source_url` | `TEXT` | URL sumber tempat dokumen ditemukan |
| `ingestion_status` | `VARCHAR(50)` | Status pipeline: pending → downloading → parsing → embedding → completed |
| `chunk_count` | `INTEGER` | Jumlah chunks yang di-embed ke ChromaDB |
| `verification_score` | `FLOAT` | Skor verifikasi silang (0.0–1.0) |
| `gaps_identified` | `TEXT[]` | Daftar gap yang teridentifikasi |

### 1.5 Tabel `ontology_nodes` *(NEW — ALCD Module — SCOPE: GLOBAL)*

Menyimpan peta pengetahuan (knowledge tree) yang dibuat AI secara mandiri. **GLOBAL** — ontologi hukum positif dibagikan lintas institusi.

```sql
CREATE TABLE ontology_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category        VARCHAR(255) NOT NULL,
    subcategory     VARCHAR(255),
    description     TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 5),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'gap_detected')),
    parent_id       UUID REFERENCES ontology_nodes(id),
    knowledge_score FLOAT DEFAULT 0.0,
    laws_ingested   INTEGER DEFAULT 0,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_onto_category ON ontology_nodes(category);
CREATE INDEX idx_onto_status ON ontology_nodes(status);
CREATE INDEX idx_onto_parent ON ontology_nodes(parent_id);
```

### 1.6 Tabel `self_eval_logs` *(NEW — ALCD Module — SCOPE: GLOBAL)*

Mencatat hasil evaluasi diri AI terhadap basis pengetahuannya. **GLOBAL** — evaluasi mutu pengetahuan berlaku untuk seluruh platform.

```sql
CREATE TABLE self_eval_logs (
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

CREATE INDEX idx_selfeval_timestamp ON self_eval_logs(timestamp);
CREATE INDEX idx_selfeval_node ON self_eval_logs(ontology_node_id);
CREATE INDEX idx_selfeval_quality ON self_eval_logs(answer_quality);
```

### 1.7 Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────────┐
│    users     │       │    cases     │       │  ai_audit_logs   │
├──────────────┤       ├──────────────┤       ├──────────────────┤
│ id (PK)      │◄──┐   │ id (PK)      │◄──┐   │ id (PK)          │
│ name         │   │   │ title        │   │   │ timestamp        │
│ email        │   │   │ description  │   │   │ request_id       │
│ badge_number │   └───│ assigned_to  │   │   │ action           │
│ role         │       │ status       │   └───│ case_id (FK)     │
│ unit         │       │ priority     │       │ user_id (FK)     │──┐
│ password_hash│       │ case_number  │       │ query_input      │  │
│ is_active    │       │ crime_type   │       │ action_taken     │  │
│ created_at   │       │ created_at   │       │ rationale        │  │
│ updated_at   │       │ updated_at   │       │ code_generated   │  │
└──────────────┘       │ closed_at    │       │ execution_result │  │
       ▲               └──────────────┘       │ metadata         │  │
       │                                      └──────────────────┘  │
       └────────────────────────────────────────────────────────────┘
```

---

## 2. ChromaDB — Vector Database

### 2.1 Koleksi: `indonesian_laws` *(SCOPE: GLOBAL — dibagikan semua institusi)*

Menyimpan embeddings dari **seluruh dokumen hukum positif Indonesia** untuk pencarian semantik. Koleksi ini dimulai **KOSONG** dan dipopulasi secara otonom oleh modul ALCD.

> **GLOBAL NAMESPACE — WAJIB:** Koleksi `indonesian_laws` adalah sumber pengetahuan bersama untuk **SEMUA institusi**. Dokumen hukum **TIDAK PERNAH** diduplikasi per tenant dan metadata chunk **TIDAK** mengandung `institution_id`. Query RAG terhadap koleksi ini tidak difilter berdasarkan tenant.
>
> Jika di masa depan diperlukan embedding untuk **data operasional tenant** (mis. bukti kasus), gunakan koleksi terpisah bernama `tenant_<institution_id>_*` — DILARANG mencampur data operasional ke dalam `indonesian_laws`.

| Aspek | Konfigurasi |
|-------|--------------|
| **Collection Name** | `indonesian_laws` |
| **Scope** | **GLOBAL** — shared legal knowledge, no tenant filter |
| **Embedding Function** | `sentence-transformers/all-MiniLM-L6-v2` |
| **Embedding Dimension** | 384 |
| **Distance Metric** | Cosine similarity |
| **Initial State** | **EMPTY** — populated autonomously by ALCD module |

### 2.2 Struktur Dokumen

Setiap dokumen dalam koleksi memiliki:

```python
{
    "id": "kuhp_pasal_362_chunk_001",        # Unique ID
    "document": "Setiap Orang yang mengambil...",  # Text chunk (500 chars)
    "embedding": [0.023, -0.156, ...],        # 384-dim vector (auto-generated)
    "metadata": {
        "law_name": "KUHP",                   # Nama undang-undang
        "article_number": "Pasal 362",        # Nomor pasal
        "topic": "Pencurian",                 # Topik/kategori
        "law_category": "materiil",           # Kategori hukum
        "chunk_index": 0,                     # Index chunk dalam pasal
        "total_chunks": 3,                    # Total chunks pasal ini
        "source_url": "https://jdih.../kuhp", # URL sumber (ditemukan ALCD)
        "discovery_date": "2026-10-07",       # Tanggal ditemukan ALCD
        "verified": true                      # Terverifikasi lintas sumber
    }
}
```

### 2.3 Metadata Fields

| Field | Tipe | Deskripsi |
|-------|------|-----------|
| `law_name` | `string` | Nama UU: `KUHP`, `KUHAP`, `UU_ITE`, `UU_TIPIKOR`, `UU_NARKOTIKA`, `UU_TPPU`, `PERKAP`, `PERJA`, `PUTUSAN_MA` |
| `article_number` | `string` | Nomor pasal: `Pasal 30`, `Pasal 362`, dll. |
| `topic` | `string` | Topik: `Pencurian`, `Akses Ilegal`, `Penipuan`, `Korupsi`, `Narkotika`, `Pencucian Uang`, dll. |
| `law_category` | `string` | Kategori: `materiil`, `formil`, `regulasi`, `yurisprudensi` |
| `chunk_index` | `integer` | Index chunk (0-based) |
| `total_chunks` | `integer` | Total chunks untuk pasal tersebut |
| `source_url` | `string` | URL sumber tempat ALCD menemukan dokumen |
| `discovery_date` | `string` | Tanggal dokumen ditemukan (ISO 8601) |
| `verified` | `boolean` | Apakah konten terverifikasi lintas minimal 2 sumber |

### 2.4 Chunking Strategy

```
Dokumen asli (contoh Pasal 362 KUHP):
┌────────────────────────────────────────────────────────────────┐
│  "Setiap Orang yang mengambil suatu Barang, yang seluruhnya   │
│   atau sebagian milik orang lain, dengan maksud untuk         │
│   dimiliki secara melawan hukum, dipidana karena pencurian    │
│   dengan pidana penjara paling lama 5 (lima) tahun atau       │
│   pidana denda paling banyak kategori V..."                   │
└────────────────────────────────────────────────────────────────┘
                            │
                   Chunking (500 char, 50 overlap)
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Chunk 0  │  │ Chunk 1  │  │ Chunk 2  │
        │ 500 char │  │ 500 char │  │ remaining│
        │          │  │←50 overlap│  │←50 overlap│
        └──────────┘  └──────────┘  └──────────┘
```

### 2.5 Contoh Query

```python
results = collection.query(
    query_texts=["hukuman untuk akses ilegal sistem komputer"],
    n_results=5,
    where={"law_name": "UU_ITE"},  # Optional filter
    include=["documents", "metadatas", "distances"]
)
```

---

## 3. Neo4j — Graph Database

> **Scope Model:** Node `LegalArticle` dan `CrimeTrend` berada di namespace **GLOBAL** (tanpa `institution_id`) — pengetahuan hukum & intelijen publik dibagikan lintas institusi. Node entitas kasus (`Suspect`, `BankAccount`, `IPAddress`, `PhoneNumber`) bersifat **TENANT** — wajib memiliki properti `institution_id` dan setiap Cypher query WAJIB difilter berdasarkannya.

### 3.1 Node Labels & Properties

#### `LegalArticle` *(GLOBAL)*
```cypher
CREATE (a:LegalArticle {
    law_name: "UU ITE",
    article_number: "Pasal 30",
    title: "Akses Ilegal",
    content: "Setiap Orang dengan sengaja dan tanpa hak...",
    ayat: "Ayat 1",
    chapter: "BAB VII",
    penalty_min: "6 tahun",
    penalty_max: "8 tahun",
    fine_max: "Rp 800.000.000"
})
```

| Property | Tipe | Deskripsi |
|----------|------|-----------|
| `law_name` | string | Nama UU |
| `article_number` | string | Nomor pasal |
| `title` | string | Judul pasal |
| `content` | string | Isi lengkap pasal |
| `ayat` | string | Ayat spesifik (jika ada) |
| `chapter` | string | Bab dalam UU |
| `penalty_min` | string | Pidana minimum |
| `penalty_max` | string | Pidana maksimum |
| `fine_max` | string | Denda maksimum |

#### `Suspect` *(TENANT — wajib `institution_id`)*
```cypher
CREATE (s:Suspect {
    institution_id: "uuid-institusi",
    name: "John Doe",
    alias: "JD",
    id_number: "3201xxxx",
    nationality: "Indonesia",
    status: "tersangka"
})
```

#### `BankAccount` *(TENANT — wajib `institution_id`)*
```cypher
CREATE (b:BankAccount {
    institution_id: "uuid-institusi",
    bank_name: "BRI",
    account_number: "1234567890",
    holder_name: "John Doe",
    status: "frozen"
})
```

#### `IPAddress` *(TENANT — wajib `institution_id`)*
```cypher
CREATE (ip:IPAddress {
    institution_id: "uuid-institusi",
    address: "192.168.1.100",
    isp: "Telkom Indonesia",
    location: "Jakarta, ID",
    first_seen: datetime("2026-01-15"),
    last_seen: datetime("2026-09-30")
})
```

#### `PhoneNumber` *(TENANT — wajib `institution_id`)*
```cypher
CREATE (p:PhoneNumber {
    institution_id: "uuid-institusi",
    number: "+6281234567890",
    provider: "Telkomsel",
    registered_name: "John Doe",
    status: "active"
})
```

#### `CrimeTrend` *(GLOBAL — intelijen publik bersama)*
```cypher
CREATE (ct:CrimeTrend {
    name: "Pencucian Uang via Cryptocurrency",
    description: "Skema pencucian uang menggunakan aset kripto lintas negara",
    category: "TPPU",
    first_detected: date("2026-03-01"),
    severity: "high"
})
```

### 3.2 Relationship Types

```cypher
-- Referensi silang antar pasal
(a1:LegalArticle)-[:CROSS_REFERENCES {context: "akses ilegal"}]->(a2:LegalArticle)

-- Kontradiksi antar pasal
(a1:LegalArticle)-[:CONTRADICTS {note: "definisi berbeda"}]->(a2:LegalArticle)

-- Pasal menggantikan pasal lain (lex specialis)
(a1:LegalArticle)-[:SUPERSEDES {effective_date: date("2023-01-01")}]->(a2:LegalArticle)

-- Kepemilikan rekening
(s:Suspect)-[:OWNS {since: date("2020-06-15")}]->(b:BankAccount)

-- Penggunaan IP
(s:Suspect)-[:USES_IP {period: "2026-01 to 2026-09"}]->(ip:IPAddress)

-- Penggunaan nomor telepon
(s:Suspect)-[:USES_PHONE {since: date("2025-03-01")}]->(p:PhoneNumber)

-- Transfer antar rekening
(b1:BankAccount)-[:LINKED_TO {
    total_amount: 50000000,
    transaction_count: 15,
    period: "2026-01 to 2026-06"
}]->(b2:BankAccount)

-- Tren melanggar pasal
(ct:CrimeTrend)-[:VIOLATES {applicability: "langsung"}]->(a:LegalArticle)
```

### 3.3 Contoh Cypher Queries

**Cari semua pasal yang di-cross-reference oleh Pasal 30 UU ITE:**
```cypher
MATCH (a:LegalArticle {law_name: "UU ITE", article_number: "Pasal 30"})
      -[:CROSS_REFERENCES]->(related:LegalArticle)
RETURN related.law_name, related.article_number, related.title
```

**Cari semua entitas terkait tersangka (WAJIB filter tenant):**
```cypher
MATCH (s:Suspect {name: "John Doe", institution_id: $tenant_id})-[r]->(entity)
WHERE entity.institution_id = $tenant_id OR entity:LegalArticle OR entity:CrimeTrend
RETURN type(r) AS relationship, labels(entity) AS entity_type, entity
```

**Cari jalur antar dua rekening (money trail — tenant-scoped):**
```cypher
MATCH path = shortestPath(
    (b1:BankAccount {account_number: "1234567890", institution_id: $tenant_id})
    -[:LINKED_TO*..5]-
    (b2:BankAccount {account_number: "0987654321", institution_id: $tenant_id})
)
RETURN path
```

### 3.4 Graph Visualization

```
                    ┌──────────────┐
                    │  CrimeTrend  │
                    │ Phishing APK │
                    └──────┬───────┘
                           │ VIOLATES
                    ┌──────▼───────┐         ┌──────────────┐
                    │ LegalArticle │─CROSS_──▶│ LegalArticle │
                    │ UU ITE Ps 30 │ REFS    │ UU ITE Ps 32 │
                    └──────────────┘         └──────────────┘
                    
    ┌─────────┐  OWNS   ┌─────────────┐  LINKED_TO  ┌─────────────┐
    │ Suspect │────────▶│ BankAccount │────────────▶│ BankAccount │
    │ John Doe│         │ BRI xxxxxx  │             │ BCA xxxxxx  │
    └────┬────┘         └─────────────┘             └─────────────┘
         │
         ├── USES_IP ──▶ [IPAddress: 192.168.1.100]
         │
         └── USES_PHONE ──▶ [PhoneNumber: +6281xxx]
```

---

## 4. Migrasi & Autonomous Population

### 4.1 Inisialisasi PostgreSQL

```bash
# Di dalam container API (working dir /app = ./backend)
docker compose exec api python scripts/init_db.py

# Atau dari host:
python backend/scripts/init_db.py
```

Script ini akan:
1. Membuat semua tabel jika belum ada (`institutions`, `users`, `feature_categories`, `features`, `institution_features`, `cases`, `ai_audit_logs`, `knowledge_registry`, `ontology_nodes`, `self_eval_logs`)
2. Menerapkan constraints dan indexes
3. Mencabut izin UPDATE/DELETE pada `ai_audit_logs` (immutability)

> **NOTE:** Script ini **HANYA** membuat tabel kosong. Tidak ada data hukum yang di-load. Lokasi file: `backend/scripts/init_db.py`.

### 4.2 ChromaDB & Neo4j — Autonomous Population via ALCD

Tidak ada manual ingestion script. Semua data hukum di-discover, di-download, di-parse, dan di-embed secara **otonom** oleh modul ALCD (`backend/app/agents/curriculum_designer.py`).

Proses ALCD:
1. **Ontology Generation** — AI merumuskan knowledge tree dari core objective
2. **Source Discovery** — AI mencari sumber resmi via Google Search (JDIH, BPK, MA)
3. **Download & Parse** — AI mengunduh dan mengekstrak konten hukum (HTML/PDF)
4. **Chunk & Embed** — AI memotong teks dan menyimpan embedding ke koleksi `indonesian_laws` di ChromaDB
5. **Graph Building** — AI mengidentifikasi cross-references dan membangun relasi di Neo4j
6. **Self-Evaluation** — AI menguji pengetahuannya sendiri, mengisi gap secara mandiri
7. **Registration** — Setiap UU yang di-ingest dicatat di tabel `knowledge_registry`

Lihat `AGENTS.md` (Agent 0: ALCD) untuk detail lengkap.
