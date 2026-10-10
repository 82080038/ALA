# 🏗️ Arsitektur Teknis — Autonomous Legal Agent (ALA)

> Dokumen ini menjelaskan arsitektur lengkap sistem ALA, termasuk pola desain Polyglot Persistence, alur data, integrasi antar komponen, dan keputusan teknis.

---

## 1. Arsitektur Tingkat Tinggi (High-Level Architecture)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND LAYER                               │
│          Next.js 14+ (TypeScript) + Tailwind CSS + shadcn/ui        │
│   ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌────────────┐  │
│   │ Crime    │  │ Legal        │  │ Workflow   │  │ Knowledge  │  │
│   │ Trend    │  │ Articles     │  │ Flowchart  │  │ Status     │  │
│   │ View     │  │ View         │  │ View       │  │ (ALCD)     │  │
│   └──────────┘  └──────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP/REST
┌──────────────────────────▼──────────────────────────────────────────┐
│                       API LAYER (FastAPI)                            │
│                                                                      │
│   POST /api/analyze-trend    POST /api/approve-workflow             │
│   GET  /api/cases            GET  /api/alcd/status                  │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────┐       │
│   │              Authentication & Authorization             │       │
│   │        (RBAC + Tenant Isolation + Token Tiering)        │       │
│   └─────────────────────────────────────────────────────────┘       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│          AUTONOMOUS KNOWLEDGE LAYER (ALCD Module)                   │
│   ┌─────────────────────────────────────────────────────────┐      │
│   │  Ontology      Source        Document     Self-         │      │
│   │  Generator ──▶ Discoverer ──▶ Parser ──▶  Evaluator     │      │
│   │      │              │            │            │         │      │
│   │      ▼              ▼            ▼            ▼         │      │
│   │  ontology_     Google      Chunk &       Gap detection  │      │
│   │  nodes         Search      Embed         + re-research  │      │
│   └─────────────────────────────────────────────────────────┘      │
│              ▲ self-eval loop (continuous)  │                       │
│              └─────────────────────────────┘                       │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                 ORCHESTRATION LAYER (LangGraph)                      │
│                                                                      │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐      │
│   │    Legal      │  │   Internet    │  │   Synthesis &     │      │
│   │  Foundation   │──▶   Crawler     │──▶  Developer        │      │
│   │    Agent      │  │    Agent      │  │    Agent          │      │
│   └───────┬───────┘  └───────┬───────┘  └─────────┬─────────┘      │
│           │                  │                     │                 │
│           ▼                  ▼                     ▼                 │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐      │
│   │ ChromaDB+Neo4j│  │ Google Search │  │  Docker Sandbox   │      │
│   │ (RAG + Graph) │  │ BeautifulSoup │  │  (Safe Execution) │      │
│   └───────────────┘  └───────────────┘  └───────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                    DATA LAYER (Polyglot Persistence)                 │
│         *** ALL databases start EMPTY — populated by ALCD ***       │
│   *** Legal knowledge = GLOBAL namespace (shared across tenants)   │
│       Operational data = TENANT-scoped via institution_id ***      │
│                                                                      │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐        │
│   │ PostgreSQL  │    │  ChromaDB   │    │     Neo4j       │        │
│   │ (Relational)│    │  (Vector)   │    │    (Graph)      │        │
│   │             │    │             │    │                 │        │
│   │ • Users (T) │    │ Starts      │    │ Starts          │        │
│   │ • Cases (T) │    │ EMPTY →     │    │ EMPTY →         │        │
│   │ • Audit (T) │    │ ALCD auto-  │    │ ALCD auto-      │        │
│   │ • Knowledge │    │ populates   │    │ builds cross-   │        │
│   │   Reg. (G)  │    │ with all    │    │ references      │        │
│   │ • Ontology  │    │ Indonesian  │    │ across all      │        │
│   │   Nodes (G) │    │ laws        │    │ laws            │        │
│   │ • Self-Eval │    │ GLOBAL:     │    │ GLOBAL:         │        │
│   │   Logs (G)  │    │ indonesian_ │    │ LegalArticle,   │        │
│   │             │    │ laws        │    │ CrimeTrend      │        │
│   │ (T)=tenant  │    │ TENANT:     │    │ TENANT:         │        │
│   │ (G)=global  │    │ tenant_*    │    │ Suspect, Accts, │        │
│   │             │    │ collections │    │ IP, Phone       │        │
│   └─────────────┘    └─────────────┘    └─────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Pola Desain: Polyglot Persistence

ALA menggunakan **tiga jenis database** yang masing-masing dioptimalkan untuk use case spesifik:

### 2.1 Relational Database — PostgreSQL 15+

**Tujuan:** Menyimpan data terstruktur dengan integritas transaksional (ACID).

| Aspek | Detail |
|-------|--------|
| **Port** | 5432 |
| **Use Case** | User management, case tracking, immutable audit log |
| **ORM** | SQLAlchemy |
| **Driver** | `psycopg2-binary` |
| **Tabel Utama** | `users`, `cases`, `ai_audit_logs` |

**Keunggulan untuk ALA:**
- Audit log **immutable** (append-only) untuk kepatuhan hukum
- Foreign key constraints menjamin konsistensi data kasus
- Role-Based Access Control (RBAC) untuk personel APH

### 2.2 Vector Database — ChromaDB (Open Source, Local)

**Tujuan:** Menyimpan embeddings dokumen hukum untuk pencarian semantik (RAG).

| Aspek | Detail |
|-------|--------|
| **Mode** | Service `ala-chroma` (server HTTP di `:8001`, persist di `.chroma/`) |
| **Scope** | **GLOBAL** — `indonesian_laws` dibagikan ke semua institusi (no `institution_id` pada metadata) |
| **Embedding Model** | `intfloat/multilingual-e5-small` (384-dim, prefix `query:`/`passage:` wajib) — dikonfigurasi via `EMBEDDING_MODEL`; jalur upgrade terdokumentasi ke `LazarusNLP/all-indo-e5-small-v4` / BGE-M3-ind (**ganti model = wajib re-embed seluruh koleksi**) |
| **Chunking Strategy** | 500 karakter per chunk, 50 karakter overlap; setiap chunk pasal diawali anchor hierarki (`[BAB II · Bagian Kesatu]`) |
| **Metadata Fields** | `law_name`, `article_number`, `topic`, `law_category`, `source_url`, `discovery_date`, `verified` |
| **Koleksi** | `indonesian_laws` (GLOBAL); `tenant_<institution_id>_*` hanya untuk data operasional tenant jika dibutuhkan kelak |
| **Initial State** | **EMPTY** — populated autonomously by the ALCD module |

> **Anti-duplikasi:** Hukum positif Indonesia identik untuk semua institusi. Menduplikasikan `indonesian_laws` per tenant membuang storage/VRAM dan membuka risiko inkonsistensi — oleh karena itu koleksi hukum bersifat GLOBAL dan query RAG tidak difilter tenant.

**Proses Ingestion (Autonomous via ALCD — multi-channel):**
1. ALCD module generates legal ontology and identifies required knowledge
2. **Fondasi doktrin dulu** — 21 konsep berjenjang (pengantar ilmu hukum → perundangan → materiil → acara → delik khusus) ditulis LLM sebagai gloss, kategori `doktrin`, `verified=False`
3. **Korpus terverifikasi** (`external_corpus.py`): SPKT `spkt://` (UU+rujukan+putusan MK), LexisAI `lexisai://` (re-embed), riset APH `aph://` (30 dok kurasi), HuggingFace `hf://laws` (1.924 UU/105K pasal JDIH BPK), `hf://putusan` (putusan MA terstruktur)
4. **Crawl otonom** hanya untuk celah yang tersisa: Google Search → unduh (HTML/PDF, OCR fallback ocrmypdf+tesseract `ind`) → parse (Bab/Bagian/Paragraf/Pasal + klausa TENTANG) → verifikasi identitas↔isi & status≠dicabut
5. Chunk → embedding E5 → ChromaDB + graph rujukan → Neo4j + registry → evaluasi deterministik (`_EXPECTED_LAW_IDS` + registry — LLM-judge hanya ke `self_eval_logs`)
6. **Struktur formal pasca-ingest**: `element_parser` menempelkan unsur delik (`elements`) ke chunk pasal pidana + node Neo4j; `putusan_kaidah` menempelkan ratio/amar (`kaidah`) ke seksi putusan; `build_norm_hierarchy` membangun rel `LegalDoc` (SUPERIOR_TO/NEWER_THAN/SPECIALIS_OF)

> **NOTE:** There are NO pre-loaded documents. The `data/` directory only holds caches (HF parquet di `backend/data/hf/`). All legal data is acquired autonomously — via verified corpora first, crawl only for residual gaps.

**Kategori Hukum (`law_category`):**
- `materiil` — Hukum pidana materiil (KUHP, UU ITE, UU Tipikor, UU Narkotika, UU TPPU)
- `formil` — Hukum acara pidana (KUHAP 8/1981 & 20/2025)
- `regulasi` — Peraturan teknis (Perkap, Perja, UU non-pidana)
- `yurisprudensi` — Putusan MA/MK
- `doktrin` — Ilmu hukum dasar & riset domain terkurasi (APH) — **bukan teks primer**, tidak disitasi sebagai UU

**Proses Query (RAG hybrid):**
1. Query → embedding E5 (`query:` prefix) → dense cosine candidates
2. BM25 leksikal (indeks lokal, stopword Indonesia; snapshot disk di
   `BM25_INDEX_PATH` agar cold-start tak rebuild) → kandidat literal
3. RRF fusion + boost `retrieval_feedback` historis + boost deterministik
   `_mention_boosts` (UU/Pasal yang disebut eksplisit di query)
4. Reranker cross-encoder lokal (`RERANKER_MODEL`, default mMARCO-MiniLM)
   mengurutkan top-48 — urutan saja; relevance_score tetap cosine dense
5. Kandidat digabung, dedupe per (UU, pasal) → konteks LLM
6. Jawaban → audit sitasi 3 sumbu → abstain jika bukti lemah/ungrounded

### 2.3 Graph Database — Neo4j 5+ (dengan APOC Plugin)

**Tujuan:** Memetakan relasi kompleks antar entitas hukum dan kasus kejahatan.

| Aspek | Detail |
|-------|--------|
| **Port HTTP** | 7474 |
| **Port Bolt** | 7687 |
| **Plugin** | APOC (Awesome Procedures on Cypher) |
| **Driver** | `neo4j` Python driver |

**Node Types:**

| Node Label | Scope | Properties | Deskripsi |
|------------|-------|-----------|-----------|
| `LegalArticle` | **GLOBAL** | `law_name`, `article_number`, `title`, `content`, `elements`?, `kaidah`?, `amar`? | Pasal hukum / seksi putusan — dibagikan semua institusi; `elements` = unsur delik JSON, `kaidah`/`amar` = kaidah putusan terstruktur |
| `LegalDoc` | **GLOBAL** | `name`, `scope` | Simpul level-peraturan untuk relasi normatif (hirarki/amandemen) |
| `Suspect` | **TENANT** | `institution_id`, `name`, `alias`, `id_number` | Tersangka — terisolasi per institusi |
| `BankAccount` | **TENANT** | `institution_id`, `bank_name`, `account_number`, `holder_name` | Rekening bank |
| `IPAddress` | **TENANT** | `institution_id`, `address`, `isp`, `location` | Alamat IP |
| `PhoneNumber` | **TENANT** | `institution_id`, `number`, `provider` | Nomor telepon |
| `CrimeTrend` | **GLOBAL** | `name`, `description`, `first_detected` | Tren kejahatan dari sumber publik — dibagikan |

**Relationship Types:**

| Relationship | Dari → Ke | Deskripsi |
|-------------|-----------|-----------|
| `CROSS_REFERENCES` | LegalArticle → LegalArticle | Referensi silang antar pasal |
| `CITES` | LegalArticle → LegalArticle | Sitasi nyata: putusan→pasal yang dikutip; juga dasar hukum konsiderans (diekspos sebagai `LEGAL_BASIS` di `/alcd/ontology`) |
| `CONTRADICTS` | LegalArticle → LegalArticle | Kontradiksi antar pasal |
| `SUPERSEDES` | LegalArticle → LegalArticle | Pasal menggantikan pasal lain |
| `REVOKES` / `AMENDS` | LegalDoc → LegalDoc | Pencabutan/amandemen dari klausul teks (arah: pencabut→dicabut) |
| `SUPERIOR_TO` | LegalDoc → LegalDoc | UU dasar hukum → peraturan pelaksana (dari CITES konsiderans) |
| `NEWER_THAN` | LegalDoc → LegalDoc | Lex posteriori: satu wilayah ontologi + subjek sama + tahun lebih baru |
| `SPECIALIS_OF` | LegalDoc → LegalDoc | Lex specialis: UU pidana sektoral → KUHP (+`co_cited` bukti empiris) |
| `OWNS` | Suspect → BankAccount | Kepemilikan rekening |
| `USES_IP` | Suspect → IPAddress | Penggunaan IP address |
| `USES_PHONE` | Suspect → PhoneNumber | Penggunaan nomor telepon |
| `LINKED_TO` | BankAccount → BankAccount | Transfer antar rekening |
| `VIOLATES` | CrimeTrend → LegalArticle | Tren melanggar pasal tertentu |

### 2.4 Model Multi-Tenancy: Pengetahuan GLOBAL vs Operasional TENANT

ALA adalah platform B2B SaaS multi-institusi, tetapi **basis pengetahuan hukum bersifat global**:

```
┌────────────────────────── GLOBAL (shared, no institution_id) ──────────────────────────┐
│  ChromaDB `indonesian_laws`  │  Neo4j LegalArticle (CROSS_REFERENCES/CITES/CONTRADICTS/ │
│  (KUHP, KUHAP, UU ITE, ...)  │  SUPERSEDES) + LegalDoc (SUPERIOR_TO/NEWER_THAN/        │
│                              │  SPECIALIS_OF/REVOKES/AMENDS) + CrimeTrend             │
│  PostgreSQL: knowledge_registry, ontology_nodes, self_eval_logs                        │
└───────────────────────────────────────────────────────────────────────────────────────┘
┌──────────────────── TENANT (wajib institution_id + RLS) ───────────────────────────────┐
│  PostgreSQL: users, cases, ai_audit_logs (investigative logs), user sessions           │
│  Skrip AI kustom (code_generated) per tenant                                           │
│  Neo4j: Suspect, BankAccount, IPAddress, PhoneNumber (properti institution_id)         │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

**Aturan:**
1. ALCD menulis SELURUH pengetahuan hukum ke namespace GLOBAL — tidak ada duplikasi per institusi.
2. `institution_id` HANYA berlaku pada data operasional: **Cases, Investigative Logs, Custom AI-Generated Scripts, User Sessions**.
3. Setiap Cypher query pada node TENANT wajib menyertakan filter `institution_id` dari `tenant_context`.
4. Query RAG ke `indonesian_laws` dan traversal ke `LegalArticle` TIDAK difilter tenant.

---

## 3. Alur Data (Data Flow)

### 3.1 Alur Bootstrap (ALCD — Runs at Startup)

```
[System Boot — ZERO DATA]
    → ALCD Module activates
    → Phase 1: Ontology Generation
        → LLM reasons about APH domain
        → Generates structured knowledge tree
        → Stores in ontology_nodes table
    → Phase 2: Doctrine Foundation (belajar ilmu hukum dulu)
        → 21 konsep berjenjang ditulis LLM sebagai gloss
        → Kategori doktrin — konteks konseptual, bukan sitasi primer
    → Phase 3: Verified Corpus Import (external_corpus.py)
        → spkt:// (~49 UU + rujukan resolved + putusan MK)
        → lexisai:// (amandemen ITE/Tipikor/KPK, KUHAP 8/1981)
        → aph:// (riset domain terkurasi — alur SPP per lembaga)
        → hf://laws (1.924 UU / 105K pasal JDIH BPK)
        → hf://putusan (putusan MA pidana; HF_PUTUSAN_MAX)
        → Idempotent: dedupe (nomor,tahun) / source_url
    → Phase 4: Autonomous Acquisition (celah yang tersisa saja)
        → For each ontology node:
            → Discover sources (Google Search / BPK / JDIH)
            → Download & parse (OCR fallback untuk PDF scan)
            → Verify identity↔subject↔status (dokumen usang ditolak)
            → Chunk, embed → ChromaDB
            → Build cross-references → Neo4j
            → Register in knowledge_registry
    → Phase 5: Self-Evaluation
        → Deterministic scoring (registry ∩ _EXPECTED_LAW_IDS)
        → LLM-as-judge hanya ke self_eval_logs (tidak menggerakkan
          readiness — pernah rubber-stamp 0.977 pada korpus salah)
        → Gold benchmark tersedia: scripts/eval_gold.py (P@k/MRR)
        → If score < threshold → re-research gaps
    → System ready to accept user queries
```

### 3.2 Alur Analisis (Law-First Pipeline — Per Query)

```
[User Request] 
    → POST /api/analyze-trend
    → Readiness Check (is ALCD knowledge score ≥ threshold?)
        → If NO → trigger ALCD bootstrap first
        → If YES → proceed
    → LangGraph Orchestrator
    → Legal Foundation Agent (FIRST)
        → Hybrid retrieval: dense E5 ∪ BM25 (snapshot disk) → RRF
          + feedback boost + mention boost → cross-encoder rerank
        → Neo4j cross-reference lookup
        → Build comprehensive legal knowledge base
        → ABSTAIN bila bukti lemah / sitasi ungrounded
        → Validate against KUHAP procedural requirements
        → Citation audit 3-axis: eksistensi + fidelity + temporal
    → Internet Crawler Agent (SECOND)
        → Google Search API / BeautifulSoup
        → Discover ALL types of crime trends (universal)
        → Contextualize with legal foundation
    → Synthesis & Developer Agent (THIRD)
        → Connect legal text with real-world modus operandi
        → Identify regulatory gaps / enforcement strategies
        → Generate Python utility scripts
        → Generate workflow flowcharts
        → Validate tools against KUHAP
    → Return results to API
    → Display on Dashboard
```

### 3.3 Alur Approval & Eksekusi Kode (dengan Chain of Custody)

```
[Generated Code]
    → Guardrail Filter (scan for malicious patterns + chain-of-custody check)
        → Jika kode menyentuh file bukti: WAJIB ada scaffold read-only + SHA-256
    → Display to APH user for review
    → POST /api/approve-workflow (human approval)
    → Log approval to PostgreSQL ai_audit_logs (immutable)
    → Execute in Docker Sandbox (isolated)
        → File bukti di-mount :ro (read-only)
        → Kode mencatat SHA-256 file bukti SEBELUM pemrosesan
        → Kode mencatat SHA-256 file bukti SESUDAH pemrosesan
        → Kedua hash WAJIB identik → integritas terverifikasi
    → Simpan evidence_sha256_before / evidence_sha256_after ke ai_audit_logs
    → Return execution results
```

---

## 4. Layer Orkestrasi: LangGraph Multi-Agent

Sistem menggunakan **LangGraph** sebagai state machine dengan **ALCD bootstrap** + urutan **law-first** per query:

```
                    ┌─────────────────┐
                    │   START STATE   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  ALCD Agent     │  ◄── AGENT 0 (bootstrap)
                    │  (Agent 0)      │
                    │                 │
                    │  • Check        │
                    │    readiness    │
                    │  • If not ready:│
                    │    ontology →   │
                    │    acquire →    │
                    │    self-eval    │
                    └────────┬────────┘
                             │ knowledge_ready=true
                    ┌────────▼────────┐
                    │  Legal          │
                    │  Foundation     │  ◄── AGENT 1
                    │  Agent          │
                    │                 │
                    │  • Query RAG    │
                    │  • Cross-ref    │
                    │  • Build legal  │
                    │    knowledge    │
                    └────────┬────────┘
                             │ legal_foundation
                    ┌────────▼────────┐
                    │  Internet       │
                    │  Crawler Agent  │  ◄── AGENT 2
                    │                 │
                    │  • Search web   │
                    │  • All crime    │
                    │    categories   │
                    │  • Parse HTML   │
                    └────────┬────────┘
                             │ crime_data
                    ┌────────▼────────┐
                    │  Synthesis &    │
                    │  Developer      │  ◄── AGENT 3
                    │  Agent          │
                    │                 │
                    │  • Connect law  │
                    │    with reality │
                    │  • Gen code     │
                    │  • Gen flowchart│
                    │  • Validate vs  │
                    │    KUHAP        │
                    └────────┬────────┘
                             │ output
                    ┌────────▼────────┐
                    │   END STATE     │
                    │  (return all)   │
                    └─────────────────┘
```

**Shared State Object:**
```python
class ALA_State(TypedDict):
    query: str                     # Input query dari user
    knowledge_ready: bool          # ALCD readiness flag (from Agent 0)
    knowledge_score: float         # Current ALCD knowledge score (0.0-1.0)
    ontology_coverage: dict        # Coverage per ontology node
    legal_articles: list[dict]     # Pasal hukum relevan (from Agent 1)
    cross_references: list[dict]   # Relasi antar pasal lintas UU
    legal_summary: str             # Ringkasan landasan hukum
    crime_data: list[dict]         # Hasil crawling internet (universal)
    crime_summary: str             # Ringkasan tren kejahatan
    synthesis: dict                # Sintesis hukum ↔ realitas
    generated_output: dict         # Kode + flowchart Mermaid yang digenerate
    audit_trail: list[dict]        # Log untuk audit
    errors: list[str]              # Error yang terkumpul per agen
```

---

## 5. Layer Keamanan (Security Layer)

### 5.1 Sandbox Eksekusi

- Kode AI berjalan dalam **Docker container** terisolasi
- Tidak ada akses jaringan dari sandbox
- Filesystem read-only (kecuali `/tmp`)
- Timeout eksekusi: maksimal 30 detik
- Memory limit: 256MB

### 5.2 Guardrail Filter

Sebelum eksekusi, kode discan untuk pola berbahaya:

| Pola Diblokir | Alasan |
|---------------|--------|
| `os.system()`, `subprocess.call()` | Shell injection |
| `rm -rf`, `shutil.rmtree()` | Destructive operations |
| `socket`, `urllib`, `requests` | Unauthorized network access |
| `eval()`, `exec()` (nested) | Code injection |
| `open('/etc/...')` | Sensitive file access |

### 5.3 Human-in-the-Loop

- **Semua kode** yang digenerate AI harus mendapat persetujuan APH sebelum eksekusi
- Approval dicatat dalam `ai_audit_logs` dengan timestamp dan identitas approver
- Tidak ada auto-execute tanpa human approval

### 5.4 Chain of Custody Bukti Digital (Kepatuhan KUHAP)

Setiap skrip yang digenerate Agent 3 untuk mem-parse/mengekstrak/menganalisis file bukti **WAJIB** mematuhi:

1. **Akses Read-Only** — file bukti dibuka mode `"rb"` (binary read); mode tulis pada path bukti ditolak guardrail, dan sandbox me-mount file bukti dengan flag `:ro`
2. **Checksum SHA-256 sebelum & sesudah** — kode menghitung hash SHA-256 file target sebelum pemrosesan dan sesudahnya; kedua hash harus identik
3. **Pencatatan ke audit log** — hash disimpan ke `ai_audit_logs.evidence_sha256_before` / `evidence_sha256_after` sebagai jaminan integritas data di pengadilan
4. **Deteksi pelanggaran** — jika hash before ≠ after, hasil eksekusi ditandai `integrity: VIOLATED` dan kasus dinaikkan untuk review

### 5.5 Token Tiering & Keadilan Komputasi SaaS

Backend FastAPI menegakkan batas token konteks per query berdasarkan `users.tier_level`:

| `tier_level` | `num_ctx` maks | `num_predict` maks |
|--------------|----------------|--------------------|
| `free` | 2.048 | 512 |
| `premium_l1` | 8.192 | 2.048 |
| `premium_l2` | 16.384 | 4.096 |

- Middleware token-budget membaca `tier_level` dari `tenant_context` dan mengklamp `num_ctx`/`num_predict` sebelum pipeline LangGraph berjalan
- Nilai efektif = `min(tier_cap, hardware_ceiling_HIRO)` — GPU 4 GB tetap menjadi batas keras fisik
- Tujuannya: mencegah tenant free memonopoli GPU; premium tier mendapat context window penuh sesuai kemampuan hardware

---

## 6. Konfigurasi Infrastructure (Docker Compose)

> **Catatan:** Konfigurasi ini dirancang **lintas-platform** — berfungsi di Windows, Linux, dan macOS tanpa modifikasi.

```yaml
services:
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: ala-api
    ports: ["8080:8000"]              # Host 8080 → Container 8000
    depends_on:
      postgres: { condition: service_healthy }
      chromadb: { condition: service_started }
      neo4j:    { condition: service_healthy }
    # Lintas-platform: Windows/macOS sudah punya host.docker.internal.
    # Linux memerlukan mapping eksplisit di bawah ini.
    extra_hosts:
      - "host.docker.internal:host-gateway"
    env_file: .env
    environment:
      # Ollama dual-instance: reasoning di GPU 0 (:11434), coder di GPU 1 (:11435)
      - OLLAMA_REASONING_URL=${OLLAMA_REASONING_URL:-http://host.docker.internal:11434}
      - OLLAMA_CODER_URL=${OLLAMA_CODER_URL:-http://host.docker.internal:11435}
    volumes:
      - ./backend:/app
    deploy:                            # GPU passthrough untuk CUDA
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: ala-frontend
    ports: ["3000:3000"]
    depends_on:
      api: { condition: service_healthy }
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8080

  postgres:
    image: postgres:15-alpine
    container_name: ala-postgres
    ports: ["5432:5432"]
    volumes:
      - postgres_data:/var/lib/postgresql/data    # Named volume — lintas-platform
    environment:
      POSTGRES_DB: ala_db
      POSTGRES_USER: ala_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  chromadb:
    image: chromadb/chroma:latest
    container_name: ala-chromadb
    ports: ["8001:8000"]
    volumes:
      - chroma_data:/chroma/chroma                # Named volume — lintas-platform

  neo4j:
    image: neo4j:5-community
    container_name: ala-neo4j
    ports: ["7474:7474", "7687:7687"]
    volumes:
      - neo4j_data:/data                          # Named volume — lintas-platform
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["apoc"]'

# Named volumes — portabel di semua OS, menghindari bug izin bind-mount
volumes:
  postgres_data:
    name: ala_postgres_data
  chroma_data:
    name: ala_chroma_data
  neo4j_data:
    name: ala_neo4j_data

networks:
  ala-network:
    name: ala-network
    driver: bridge
```

---

## 7. Infrastruktur Lintas-Platform

ALA dirancang agar berjalan **identik** di Windows, Linux, dan macOS. Berikut adalah pagar pengaman yang ditegakkan:

### 7.1 Resolusi Host Docker

| OS | `host.docker.internal` | Konfigurasi |
|----|------------------------|-------------|
| Windows (Docker Desktop) | Native | Tanpa tambahan |
| macOS (Docker Desktop) | Native | Tanpa tambahan |
| Linux (Docker Engine) | Tidak tersedia | `extra_hosts: ["host.docker.internal:host-gateway"]` |

### 7.2 Operasi File Agnostik-OS

- **WAJIB:** `pathlib.Path` atau `os.path.join` untuk semua path file
- **DILARANG:** Hardcode `\` (Windows) atau `/` (Unix)
- Implementasi: `backend/app/config.py` mengimpor `pathlib.Path` dan `platform`

### 7.3 Named Volumes (Bukan Bind-Mount)

Semua database menggunakan **named volumes** Docker:
- `ala_postgres_data` — PostgreSQL
- `ala_chroma_data` — ChromaDB
- `ala_neo4j_data` — Neo4j

Alasan: Bind-mount (`./data/db:/var/lib/...`) menyebabkan bug `EACCES` / `Permission Denied` saat transisi antara:
- Linux rootless Docker ↔ root Docker
- Windows WSL2 filesystem ↔ NTFS

### 7.4 Deteksi RAM Lintas-Platform (HIRO)

| OS | Metode | Implementasi |
|----|--------|--------------|
| Linux | `/proc/meminfo` via `pathlib.Path` | `_detect_ram()` |
| Windows | `ctypes.windll.kernel32.GlobalMemoryStatusEx` | `_detect_ram()` |
| macOS | `shutil.disk_usage("/")` fallback | `_detect_ram()` |

### 7.5 Skrip Otomasi

| Skrip | Platform | Lokasi |
|-------|----------|---------|
| `setup.sh` | Linux / macOS | `scripts/setup.sh` |
| `setup.ps1` | Windows PowerShell | `scripts/setup.ps1` |

### 7.6 Alokasi Dual-GPU Ollama (HIRO — Anti-OOM)

Host menjalankan **2× NVIDIA GTX 1050 Ti (4 GB VRAM)**. Karena satu GPU 4 GB tidak dapat menampung dua model 3B Q4 secara aman, HIRO mengunci model ke GPU terdedikasi via **dua instance Ollama**:

| Instance | Port | Env | Model Terkunci | Konsumen |
|----------|------|-----|----------------|----------|
| Ollama #1 | `11434` | `CUDA_VISIBLE_DEVICES=0` | `qwen2.5:3b-instruct` | Agen 0–2 (penalaran) |
| Ollama #2 | `11435` | `CUDA_VISIBLE_DEVICES=1` | `qwen2.5-coder:3b` | Agen 3 (codegen) |

Konfigurasi per instance (systemd override atau env process):
- `OLLAMA_MAX_LOADED_MODELS=1` — hanya satu model resident per GPU
- `OLLAMA_NUM_PARALLEL=1` — tanpa konkurensi intra-instance (VRAM 4 GB ketat)
- `OLLAMA_KEEP_ALIVE=24h` — model tetap termuat, menghindari reload latency

Fallback HIRO: jika GPU 1 tidak terdeteksi, `OLLAMA_CODER_URL` fallback ke instance `:11434` dan request LLM diantrikan sekuensial — bukan paralel — agar tidak OOM.

---

## 8. Keputusan Teknis (ADR Summary)

| Keputusan | Alasan |
|-----------|--------|
| **ChromaDB** vs Pinecone | Open-source, berjalan lokal, tanpa biaya cloud, data sensitif tetap on-premise |
| **LangGraph** vs CrewAI | State machine eksplisit, kontrol granular atas alur agen, debugging lebih mudah |
| **PostgreSQL** vs MySQL | JSON support lebih baik, extensibility, komunitas enterprise |
| **FastAPI** vs Flask | Async native, auto-generate OpenAPI docs, Pydantic validation |
| **Next.js** vs Streamlit/HTML | Full SSR/CSR, TypeScript type safety, professional UI, shadcn/ui ecosystem |
| **Playwright** vs Selenium/Requests | Headless browser handles JS-heavy gov sites, async, reliable for ALCD crawling |
| **Docker Sandbox** vs E2B | Self-hosted, tanpa dependensi cloud, kontrol penuh atas isolasi |
| **all-MiniLM-L6-v2** vs OpenAI Embeddings | Gratis, berjalan lokal, cukup akurat untuk Bahasa Indonesia |

---

## 9. Referensi

- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Next.js Documentation](https://nextjs.org/docs)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [shadcn/ui Documentation](https://ui.shadcn.com/)
- [Playwright for Python](https://playwright.dev/python/)
- [Docker Compose Specification](https://docs.docker.com/compose/compose-file/)
