# Konteks Proyek ALA — Referensi Devin

## 🔐 Akses Sistem
- **Password Sudo:** `8208`

---

## 🛠️ Tech Stack (TERKUNCI — Lokal & Offline)

| Lapisan | Teknologi |
|---------|-----------|
| **Back-End** | Python 3.11+ / FastAPI + Uvicorn |
| **Orkestrasi AI** | LangGraph + LangChain |
| **Penyedia LLM** | **Ollama Lokal** (akselerasi GPU CUDA) |
| **LLM Penalaran (Agen 0-2)** | `qwen2.5:3b-instruct` via ChatOllama |
| **LLM Pembuat Kode (Agen 3)** | `qwen2.5-coder:3b` via ChatOllama |
| **Endpoint Ollama** | `http://host.docker.internal:11434` |
| **Embedding** | `sentence-transformers/all-MiniLM-L6-v2` (lokal/offline) |
| **Crawling Otonom** | Playwright (Python) |
| **Front-End** | TypeScript / Next.js 14+ / Tailwind CSS / shadcn/ui |
| **DB Relasional** | PostgreSQL 15+ |
| **DB Vektor** | ChromaDB (terkontainerisasi) |
| **DB Graph** | Neo4j 5+ (dengan APOC) |
| **Infrastruktur** | Docker Compose (5 layanan) |

---

## 🖥️ Profil Perangkat Keras GPU
- **GPU 0:** NVIDIA GeForce GTX 1050 Ti — 4 GB VRAM — **TERKUNCI** untuk `qwen2.5:3b-instruct` (Ollama `:11434`, `CUDA_VISIBLE_DEVICES=0`)
- **GPU 1:** NVIDIA GeForce GTX 1050 Ti — 4 GB VRAM — **TERKUNCI** untuk `qwen2.5-coder:3b` (Ollama `:11435`, `CUDA_VISIBLE_DEVICES=1`)
- **BATASAN:** Model maksimal = **3B parameter** (Q4). 7B+ akan OOM. Satu model per GPU (`OLLAMA_MAX_LOADED_MODELS=1`).

---

## 🐳 Layanan Docker & Port

| Layanan | Kontainer | Port Host | Port Internal |
|---------|-----------|-----------|---------------|
| FastAPI API | `ala-api` | **8080** | 8000 |
| Next.js Frontend | `ala-frontend` | **3000** | 3000 |
| PostgreSQL | `ala-postgres` | **5432** | 5432 |
| ChromaDB | `ala-chromadb` | **8001** | 8000 |
| Neo4j | `ala-neo4j` | **7474** / **7687** | 7474 / 7687 |

> **Catatan:** Port host 8000 digunakan oleh PHP. API dipetakan ke 8080.

---

## 🔗 Konfigurasi Ollama
- Ollama berjalan di **mesin host** (bukan di Docker) — **dua instance** untuk GPU pinning:
  - Instance #1 `:11434` → `CUDA_VISIBLE_DEVICES=0` → `qwen2.5:3b-instruct` (Agen 0–2)
  - Instance #2 `:11435` → `CUDA_VISIBLE_DEVICES=1` → `qwen2.5-coder:3b` (Agen 3)
- Override systemd: `/etc/systemd/system/ollama.service.d/override.conf` → `OLLAMA_HOST=0.0.0.0` (+ unit kedua `ollama-coder.service` untuk port 11435)
- Docker menjangkau Ollama via `extra_hosts: ["host.docker.internal:host-gateway"]`
- Env: `OLLAMA_REASONING_URL` (`:11434`) dan `OLLAMA_CODER_URL` (`:11435`, fallback ke reasoning)

---

## 📂 File Konfigurasi Penting
- `docker-compose.yml` — 5 layanan dengan healthcheck, jaringan, volume
- `.env` — Variabel Ollama, password DB, JWT, konfigurasi ALCD
- `backend/app/config.py` — Fungsi factory `get_llm_reasoning()` / `get_llm_coder()`
- `backend/requirements-core.txt` — Dependensi ringan (build Docker cepat)
- `backend/requirements.txt` — Dependensi lengkap (termasuk sentence-transformers, playwright)

---

## 🤖 Pipeline Agen (4 Agen via LangGraph)
1. **Agen 0 — ALCD** (Perancang Kurikulum Hukum Otonom): Membangun pengetahuan dari nol
2. **Agen 1 — Fondasi Hukum**: RAG via ChromaDB + referensi silang Neo4j
3. **Agen 2 — Penjelajah Internet**: Browser headless Playwright untuk tren kejahatan
4. **Agen 3 — Sintesis & Pengembang**: Pembuatan kode + diagram alur kerja

---

## 📋 Status Fase Mega-Plan
- [x] **Fase 1:** Lingkungan & Kerangka Dasar — SELESAI
- [x] **Fase 2:** Database Inti & Antarmuka Agen — SELESAI (RLS `ala_app` terverifikasi, audit append-only, tier budget)
- [x] **Fase 3:** Mesin Agen Otonom (LangGraph + Ollama lokal) — SELESAI (pipeline 4 agen berjalan end-to-end; ALCD loop BPK→PDF→embed→Chroma→Neo4j teruji)
- [x] **Fase 4:** Sandbox & Pembuatan Kode — SELESAI (guardrails AST + sandbox Docker terkunci terverifikasi live)
- [x] **Fase 5:** Integrasi Dashboard Front-End — SELESAI (6 halaman live: Dashboard, Analisis+HITL, ALCD, Kasus, Audit, Super Admin; `tsc --noEmit` bersih)

### Catatan Operasional (terverifikasi 2026-10)
- Sudo host: `8208` (dipakai untuk `scripts/setup_dual_ollama.sh` + `systemctl start docker`)
- DuckDuckGo diblokir ISP (Telkomsel DNS-hijack) → ALCD pakai fallback Google CSE → DDG → **BPK Search**; crawler berita pakai **Google News RSS**
- `ollama-coder.service` aktif di `:11435` (GPU 1); model dir dibagikan — pull hanya via `:11434`
- Role DB: `ala_user` = admin/DDL saja; runtime API = `ala_app` (non-superuser, tunduk RLS)

---

## 🛡️ Pagar Pengaman Inti
1. **Mulai Tanpa Data** — Tidak ada dokumen hukum pra-muat. ALCD membangun dari internet.
2. **Lokal-Utama** — Semua inferensi LLM via Ollama. Tanpa panggilan API cloud.
3. **Keselamatan Prosedural** — Jangan pernah melewati KUHAP.
4. **Tanpa Penimpaan** — Framework agen inti tidak disentuh oleh sandbox.
5. **Manusia-dalam-Lingkaran** — Semua kode yang dihasilkan AI memerlukan persetujuan APH.
6. **Chain of Custody** — Skrip AI pada file bukti: read-only + SHA-256 sebelum/sesudah (`evidence_sha256_before/after` di `ai_audit_logs`).
7. **Pengetahuan Global vs Tenant** — ChromaDB `indonesian_laws` & Neo4j `LegalArticle`/`CrimeTrend` = GLOBAL (tanpa `institution_id`); cases/logs/skrip/sesi = TENANT.
8. **Token Tiering** — `free`=2.048 ctx, `premium_l1`=8.192, `premium_l2`=16.384 (diklamp hardware HIRO).
9. **GPU Pinning** — reasoning→GPU 0, coder→GPU 1; dilarang berbagi GPU (anti-OOM).
