# 📝 Changelog — Autonomous Legal Agent (ALA)

> Semua perubahan penting pada proyek ini didokumentasikan dalam file ini.
> Format mengikuti [Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/) dan proyek ini menggunakan [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added — Implementasi Fase 2 & 3 (diverifikasi live di Docker + dual-GPU Ollama)
- **Pipeline 4 agen penuh** — `legal_orchestrator.py` (LangGraph `StateGraph(ALA_State)`), `curriculum_designer.py` (Agent 0: ontologi→discover→parse→ingest→graph→self-eval), `legal_foundation.py` (Agent 1: RAG ChromaDB GLOBAL + xref Neo4j), `internet_crawler.py` (Agent 2: Google CSE → Google News RSS fallback, Playwright→httpx), `code_generator.py` (Agent 3: sintesis + codegen dengan `CUSTODY_SCAFFOLD` wajib)
- **Sub-modul ALCD** — `alcd/ontology_generator.py`, `source_discoverer.py` (CSE→DDG→BPK fallback + circuit breaker), `document_parser.py` (HTML/PDF→pasal, retry 403-backoff), `autonomous_ingestor.py` (chunk 500/50→embed→ChromaDB GLOBAL upsert), `graph_builder.py` (node `LegalArticle` + `CROSS_REFERENCES`), `evaluator.py` (self-quiz + LLM-as-judge + klasterisasi fitur→tier)
- **Sandbox runtime nyata** — `sandbox/guardrails.py` (AST syntax + whitelist import + blacklist pola, `open()` hanya mode baca) + `execution_env.py` (Docker `network_mode: none`, `read_only`, `cap_drop=ALL`, `pids_limit`, 0.5 CPU, timeout 30s, mount bukti `:ro`); terverifikasi: kode aman jalan, loop∞ terbunuh 30s, kode jahat diblokir
- **API nyata** — `POST /api/v1/analyze-trend` (pipeline + audit), `POST /api/v1/approve-workflow` (re-scan guardrail → sandbox, hanya jika disetujui), `GET/POST /cases`, `GET /audit-logs`, `POST /graph/query` (Cypher read-only), `/alcd/status|trigger|ontology|gaps`; `admin.py` CRUD institusi/pengguna/fitur/tier nyata
- **Role `ala_app` non-superuser** — `init_db.py` membuat role aplikasi terpisah (superuser `ala_user` selalu bypass RLS → RLS sebelumnya dorman); `DATABASE_URL` runtime→`ala_app`, `DATABASE_ADMIN_URL`→init; RLS `WITH CHECK` menolak INSERT lintas-tenant; REVOKE UPDATE/DELETE `ai_audit_logs` ditegakkan
- **`scripts/setup_dual_ollama.sh`** — otomatisasi override GPU 0 (`:11434`) + unit `ollama-coder.service` GPU 1 (`:11435`); terverifikasi: kedua model termuat pada GPU masing-masing (GPU0 2.367 MiB / GPU1 2.138 MiB)
- **`docker.sock` mount** ke service api untuk sandbox sibling-container

### Added — Fase 5: Dashboard Front-End (diverifikasi `tsc --noEmit` bersih + semua route 200)
- **Session identitas header-based** — `src/lib/session.tsx`: React context + localStorage; `IdentitySelector` di header memilih role/tier/`X-Institution-ID` (bridge sampai JWT siap)
- **`api-client.ts` lengkap** — `apiFetch` menyuntik header tenant ke semua request; `ApiError` mengekstrak `detail` FastAPI; fungsi typed untuk semua endpoint v1 + admin
- **Dashboard live** (`/`) — SWR polling `/status`, `/alcd/status`, `/health`: skor pengetahuan, UU ter-ingest, node ontologi, status Ollama + GPU/ctx
- **Analisis Tren** (`/analyze`) — form query → hasil pipeline (ringkasan hukum, pasal relevan, sumber tren, error pipeline) → viewer kode AI + flowchart Mermaid → tombol **Setujui & Jalankan / Tolak** (HITL) → hasil eksekusi sandbox
- **Konsol ALCD** (`/alcd`) — statistik GLOBAL, pohon ontologi per kategori dengan skor berwarna (`OntologyGraph`), daftar gap pengetahuan + aksi remediasi, tombol trigger bootstrap
- **Kasus** (`/cases`) — tabel kasus tenant + form buat kasus (RLS per `institution_id`)
- **Audit Log** (`/audit`) — tabel `AuditLogs` dengan kolom chain-of-custody `evidence_sha256_before → after`
- **Super Admin** (`/admin`) — CRUD institusi (3 tipe), daftar pengguna lintas-tenant + dropdown tier, tabel fitur dengan saran tier AI + override admin + toggle aktif; halaman menolak non-`super_admin`

### Added — Suite Uji & Hardening (24 tes lulus di container api)
- `backend/tests/` — pytest: `test_guardrails.py` (8), `test_parser.py` (7 — format pasal BPK, dedup, xref, chunking), `test_tier_budget.py` (5 — clamp `min(tier, hw)`), `test_sandbox_integration.py` (3 — eksekusi aman, blokir kode jahat, timeout 30s; auto-skip tanpa Docker socket)
- `conftest.py` — normalisasi `DEBUG` env non-boolean (shell host mengekspor `DEBUG=release` yang ditolak pydantic)

### Fixed — ditemukan via uji E2E Playwright headed (alur nyata di browser)
- `sandbox/Dockerfile` — image `ala-sandbox` kini menyertakan semua pustaka yang di-whitelist guardrails (`pandas`, `numpy`, `openpyxl`, `beautifulsoup4`, `lxml`, `pdfplumber`, `pypdf`, `python-docx`, `pillow`, `pytesseract`, `chardet`, `python-dateutil`) — sebelumnya hanya `regex` sehingga kode legal hasil AI gagal `ModuleNotFoundError`
- E2E headed penuh terverifikasi: identitas → buat institusi → kasus → ALCD bootstrap **otonom selesai** (`knowledge_score=0.902`, **24 UU** registry `completed`, **66 chunk** ChromaDB, **34 node** `LegalArticle` + xref Neo4j) → analisis tren → **HITL approve → eksekusi sandbox** → audit `analyze`+`execute` tercatat; 0 error JS

### Fixed — lanjutan
- `guardrails.py` — gap path sensitif: kini memblokir `~/.ssh`, `.gnupg`, `.aws`, `.kube`, `.docker`, kunci privat (`id_rsa`/`*.pem`), dan file `.env` (sebelumnya hanya `/etc`, `/proc`, `/sys`, `/root`, `/dev`, `..`)
- `postgres.py`/`config.py` — `echo` SQLAlchemy memakai flag `DB_ECHO` sendiri (default off); `DEBUG=true` tidak lagi membanjiri log dengan semua query SQL

### Fixed — ditemukan saat verifikasi live
- `requirements.txt` — pin seri 0.3.x (`langchain-core/community/ollama` + `langgraph 0.2.x` terakhir); tambah `psycopg[binary]` (SQLAlchemy 2.1 menjadikan psycopg v3 driver default), `pypdf`, `docker`
- HIRO `num_ctx` ceiling kini pakai VRAM GPU **terbesar tunggal** (bukan total 2×4GB→8192 yang over-commit)
- `num_predict` dinaikkan ke 2048 di VRAM≥4GB (codegen JSON terpotong di 1024)
- `open()` di guardrail memakai cek mode literal (bukan blokir total — scaffold custody butuh `"rb"`)
- Regex pasal mendukung format BPK `Pasal 1.`/`Pasal 1 ...` + dedup artikel; regex xref memperbaiki `to_law` salah-tangkap
- `SET LOCAL` → `set_config(..., true)` (SET tidak menerima parameter bind); `_tenant_db` menyetel GUC `app.tenant_id` per request
- `internet_crawler`: `asyncio.run` dalam konteks loop → fetch Playwright via thread terpisah; hasil parsial tidak lagi terhapus saat error
- Eksekusi sandbox: `put_archive` ditolak pada container `read_only` → kode dikirim via base64 ke tmpfs `/tmp`; user image `sandbox_user`
- `main.py`: `logging.basicConfig` agar log `ala.*` muncul di docker logs

### Added
- **Model Tenancy Global vs Tenant** — dokumentasi pemisahan ketat: pengetahuan hukum (ChromaDB `indonesian_laws`, Neo4j `LegalArticle`/`CrimeTrend`, `knowledge_registry`, `ontology_nodes`, `self_eval_logs`) bersifat GLOBAL lintas institusi; `institution_id` hanya untuk data operasional (cases, investigative logs, custom AI scripts, user sessions)
- **Chain of Custody KUHAP** — kolom `evidence_sha256_before`/`evidence_sha256_after` di `ai_audit_logs`; kode AI yang menyentuh file bukti wajib read-only + checksum SHA-256 sebelum/sesudah
- **Dual-GPU Ollama pinning** — dua instance Ollama: `qwen2.5:3b-instruct`→GPU 0 (`:11434`, `CUDA_VISIBLE_DEVICES=0`), `qwen2.5-coder:3b`→GPU 1 (`:11435`, `CUDA_VISIBLE_DEVICES=1`) untuk mencegah OOM
- **SaaS Token Tiering** — batas `num_ctx` per `tier_level`: `free`=2.048, `premium_l1`=8.192, `premium_l2`=16.384, diklamp oleh ceiling hardware HIRO; ditegakkan via middleware FastAPI

### Fixed
- `scripts/setup.sh` — perbaikan pemeriksaan Docker Compose (`command -v docker compose` selalu gagal; diganti `docker compose version`)
- `backend/app/database/chroma.py` — `get_chroma_client()` kini membaca `settings.chromadb_host`/`chromadb_port` (tidak lagi hardcode)
- `backend/app/database/postgres.py` — docstring dikoreksi (engine sinkron, bukan async)
- `backend/app/config.py` — migrasi `ChatOllama` ke paket `langchain_ollama` (depresiasi `langchain_community`); `Settings` kini menggunakan `SettingsConfigDict` (Pydantic v2)
- `backend/app/middleware/tenant.py` — validasi nilai `X-User-Role` dan `X-Tier-Level` terhadap daftar yang diizinkan
- `backend/app/models/tenant.py` — tambah kolom `badge_number`, `unit`, `updated_at` pada `User` (selaras DATABASE_SCHEMA.md)
- `backend/scripts/init_db.py` — **baru**: inisialisasi semua tabel (multi-tenant + ALCD + audit log immutable)
- `backend/app/agents/legal_foundation.py` & `legal_orchestrator.py` — **baru**: stub Agen 1 dan orkestrator LangGraph

### Changed
- `requirements.txt` — tambah `langchain-ollama`
- `.env.example` / `.env` — tambah variabel opsional `GOOGLE_CSE_ID`/`GOOGLE_CSE_API_KEY` untuk ALCD & crawler
- `API.md` — base URL `localhost:8080`, prefix `/api/v1`, role multi-tenant, catatan status implementasi
- `AGENTS.md` — penyedia LLM diganti OpenAI/Gemini → Ollama lokal; jalur file agen diselaraskan ke `backend/app/agents/`
- `SECURITY.md` — matriks RBAC multi-tenant (`super_admin`, `admin_instansi`, `penyidik`, `jaksa`, `hakim`); hapus kunci API cloud dari contoh `.env`
- `DEPLOYMENT.md` — env vars diselaraskan dengan Ollama; service `app` → `api`; port host 8080; contoh respons `/health` diperbarui
- `DATABASE_SCHEMA.md` — tabel `users` multi-tenant (+`institutions`); metadata ChromaDB `source_file` → `source_url`/`discovery_date`/`verified`
- `PLAN.md` — task 2.6 ke Ollama; status Fase 1 infra ditandai selesai; Streamlit → Next.js
- `CONTRIBUTING.md` — jalur file diperbarui ke struktur `backend/`; referensi `ingest_laws.py`/`seed_graph.py` dihapus
- `README.MD` & `DEVIN_PROMPT.md` — pohon struktur proyek diselaraskan dengan implementasi `backend/` aktual

### Planned
- Setup Docker Compose infrastructure (PostgreSQL, Neo4j, ChromaDB)
- Python environment & dependency management
- **ALCD Module (Autonomous Legal Curriculum Designer):**
  - `alcd/ontology_generator.py` — Self-directed knowledge ontology
  - `alcd/source_discoverer.py` — Autonomous legal source discovery
  - `alcd/document_parser.py` — Download, parse, verify legal documents
  - `alcd/autonomous_ingestor.py` — Chunk, embed, store in ChromaDB
  - `alcd/graph_builder.py` — Auto-build Neo4j cross-references
  - `alcd/self_evaluator.py` — Self-quiz, gap detection, re-research
  - `alcd/curriculum_agent.py` — ALCD orchestrator (Agent 0)
- Internet Crawler Agent (`agents/crawler_agent.py`)
- Legal Foundation Agent (`agents/legal_agent.py`)
- Synthesis & Developer Agent (`agents/developer_agent.py`)
- LangGraph orchestrator with 4 agents (`agents/legal_orchestrator.py`)
- FastAPI backend: `/api/analyze-trend`, `/api/approve-workflow`, `/api/alcd/*`
- Docker sandbox untuk eksekusi kode aman
- Guardrail filter untuk keamanan kode AI
- Web dashboard (HTML5 + TailwindCSS) with ALCD knowledge status view
- Human-in-the-Loop approval workflow
- Immutable audit logging

---

## [0.3.0] — 2026-10-07

### Added
- **🧠 Autonomous Legal Curriculum Designer (ALCD) Module — Zero-Data Start**
  - System now starts with **ZERO pre-loaded legal documents**
  - AI autonomously reasons what laws it needs, discovers them from the internet, and ingests them
  - New `alcd/` directory with 7 sub-modules:
    - `ontology_generator.py` — LLM-driven knowledge tree generation
    - `source_discoverer.py` — Google Search for JDIH, BPK, MA repositories
    - `document_parser.py` — HTML/PDF download, parsing, content extraction
    - `autonomous_ingestor.py` — Chunking, embedding, ChromaDB storage
    - `graph_builder.py` — Automated Neo4j cross-reference building
    - `self_evaluator.py` — Self-quiz, LLM-as-judge scoring, gap detection
    - `curriculum_agent.py` — ALCD pipeline orchestrator (Agent 0)
  - New PostgreSQL tables: `knowledge_registry`, `ontology_nodes`, `self_eval_logs`
  - New API endpoints: `GET /api/alcd/status`, `POST /api/alcd/trigger`, `GET /api/alcd/ontology`, `GET /api/alcd/gaps`
  - ALCD configuration via environment variables (`ALCD_ENABLED`, `ALCD_MIN_READINESS_SCORE`, etc.)
  - Agent pipeline expanded from 3 to 4 agents: ALCD (Agent 0) → Legal Foundation → Internet Crawler → Synthesis & Developer

### Changed
- **⚠️ DATA PARADIGM: No more pre-loaded documents**
  - Removed `data/` directory and all manual ingestion scripts (`ingest_laws.py`, `seed_graph.py`)
  - ChromaDB and Neo4j now start **EMPTY** and are populated autonomously by ALCD
  - `scripts/init_db.py` only creates empty tables (no data loading)
- Shared state (`ALA_State`) expanded with `knowledge_ready`, `knowledge_score`, `ontology_coverage` fields
- Health check endpoint now includes ALCD readiness status
- Permission matrix updated with ALCD endpoints
- Security checklist expanded with ALCD crawl rate limiting and trusted domain policies

### Updated
- `DEVIN_PROMPT.md` — Complete rewrite: zero-data philosophy, ALCD module, updated project structure
- `ARCHITECTURE.md` — New ALCD layer in all diagrams, autonomous data flow, updated ChromaDB/Neo4j sections
- `AGENTS.md` — New Agent 0 (ALCD) with full documentation, 4-agent pipeline
- `README.MD` — Updated description with ALCD steps, replaced `data/` with `alcd/` in project structure
- `DATABASE_SCHEMA.md` — 3 new tables, ChromaDB starts empty, autonomous population process
- `API.md` — 4 new ALCD endpoints, updated health check, updated rate limiting
- `PLAN.md` — Fase 1 rebuilt around ALCD module, dependency diagram updated
- `DEPLOYMENT.md` — ALCD env vars, removed manual ingestion steps, updated troubleshooting
- `SECURITY.md` — ALCD permissions, data retention, deployment checklist

---

## [0.2.0] — 2026-10-07

### Changed
- **⚠️ PARADIGM SHIFT: Cakupan Diperluas dari Kejahatan Siber ke Seluruh Hukum Pidana**
  - Sistem sebelumnya terlalu terfokus pada kejahatan siber saja
  - Sekarang mencakup **seluruh spektrum tugas APH**: pidana umum, korupsi, narkotika, TPPU, kejahatan transnasional, kejahatan siber, dll.
- **Urutan Logika AI Dibalik (Law-First Pipeline):**
  - Sebelumnya: Internet Crawler → Legal Analyzer → Developer
  - Sekarang: **Legal Foundation Agent (FIRST)** → Internet Crawler Agent → Synthesis & Developer Agent
  - AI menguasai hukum terlebih dahulu, baru mengontekstualisasikan dengan tren kejahatan
- **Korpus Hukum Diperluas:**
  - Sebelumnya: KUHP, KUHAP, UU ITE (3 sumber)
  - Sekarang: KUHP, KUHAP, UU ITE, UU Tipikor, UU Narkotika, UU TPPU, Perkap, Perja, Putusan MA (9+ sumber)
- **Agent 3 Ditingkatkan** menjadi Synthesis & Developer Agent:
  - Menambahkan fase sintesis (menghubungkan hukum dengan realitas)
  - Identifikasi celah regulasi (*loophole*)
  - Validasi semua output terhadap KUHAP (hukum acara)
- **Metadata ChromaDB** ditambahkan field `law_category` (materiil/formil/regulasi/yurisprudensi)
- **Neo4j Cross-References** diperluas dari intra-UU menjadi lintas-UU

### Updated
- `README.MD` — Deskripsi baru dengan 5 poin urutan logika sistem
- `DEVIN_PROMPT.md` — Core Design Philosophy, law-first pipeline, expanded data ingestion
- `ARCHITECTURE.md` — Diagram diperbaiki: Legal Foundation Agent pertama, data layer diperluas
- `AGENTS.md` — Reorder agen, shared state diperbarui, contoh output universal
- `PLAN.md` — Roadmap disesuaikan: law-first agent development, multi-unit pilot
- `API.md` — Response schema diperluas: `legal_foundation`, `synthesis`
- `DATABASE_SCHEMA.md` — Metadata `law_category`, cakupan UU diperluas
- `SECURITY.md` — Data classification diperluas
- `DEPLOYMENT.md` — Ingestion command diperbarui untuk semua sumber hukum

---

## [0.1.0] — 2026-10-07

### Added
- **Dokumentasi Proyek Lengkap:**
  - `README.MD` — Overview proyek, tech stack, quick start guide
  - `ARCHITECTURE.md` — Arsitektur teknis Polyglot Persistence, data flow, layer diagram
  - `PLAN.md` — Roadmap 5 fase dengan milestone, deliverables, dan kriteria keberhasilan
  - `API.md` — Dokumentasi REST API endpoints (analyze-trend, approve-workflow, cases, audit-logs, graph query)
  - `DATABASE_SCHEMA.md` — Skema lengkap PostgreSQL, ChromaDB, dan Neo4j
  - `AGENTS.md` — Dokumentasi sistem multi-agent (Crawler, Legal Analyzer, Developer)
  - `SECURITY.md` — Kebijakan keamanan, guardrails AI, sandbox isolation, RBAC
  - `DEPLOYMENT.md` — Panduan deployment development & production
  - `CONTRIBUTING.md` — Panduan kontribusi, coding standards, branching strategy
  - `CHANGELOG.md` — Riwayat perubahan versi (file ini)
  - `DEVIN_PROMPT.md` — Prompt instruksi untuk Devin AI builder

### Defined
- Arsitektur Polyglot Persistence: PostgreSQL + ChromaDB + Neo4j
- Multi-agent pipeline: Internet Crawler → Legal Analyzer → Developer Agent
- Security model: Defense in Depth (6 layers)
- RBAC roles: admin, investigator, analyst
- Sandbox constraints: no network, read-only, 256MB memory, 30s timeout

---

## Version History Format

Setiap rilis didokumentasikan dengan kategori berikut:

| Kategori | Deskripsi |
|----------|-----------|
| **Added** | Fitur baru |
| **Changed** | Perubahan pada fitur yang sudah ada |
| **Deprecated** | Fitur yang akan dihapus di versi mendatang |
| **Removed** | Fitur yang dihapus |
| **Fixed** | Perbaikan bug |
| **Security** | Perbaikan kerentanan keamanan |
