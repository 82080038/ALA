# 🏛️ Autonomous Legal Agent (ALA)

> **Sistem Agen AI Otonom untuk Membantu Aparat Penegak Hukum (APH) Indonesia**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-orange.svg)](https://github.com/langchain-ai/langgraph)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()

---

## 📖 Deskripsi

**Autonomous Legal Agent (ALA)** adalah sistem kecerdasan buatan otonom yang dirancang untuk memperkuat kapabilitas Aparat Penegak Hukum (APH) Indonesia. Sistem ini bekerja dengan mempelajari seluruh spektrum hukum positif, menghubungkannya secara dinamis dengan realitas kejahatan yang berkembang di internet, dan secara mandiri menciptakan program/alur bantu kerja lapangan APH.

Sistem ini dimulai dengan **NOL data hukum** dan beroperasi dengan urutan logika sebagai berikut:

1. **Perancangan Kurikulum Mandiri (ALCD)** — AI secara otonom merumuskan *ontologi pengetahuan* — peta terstruktur dari seluruh hukum dan regulasi yang dibutuhkan APH (KUHP, KUHAP, UU ITE, UU Tipikor, UU Narkotika, UU TPPU, Perkap, Perja, dsb.) tanpa intervensi manusia.
2. **Akuisisi Data Otonom** — AI menjelajahi internet untuk menemukan, mengunduh, mem-parsing, dan meng-embed dokumen hukum dari sumber resmi (JDIH, BPK, Mahkamah Agung) ke Vector & Graph Database.
3. **Evaluasi Diri Berkelanjutan** — AI menguji pengetahuannya sendiri, mengidentifikasi celah, dan secara mandiri memulai riset ulang untuk mengisi kekurangan.
4. **Penguasaan Yurisdiksi Hukum** — Setelah basis pengetahuan terbangun, AI membangun landasan hukum komprehensif untuk setiap query pengguna.
5. **Konteks Tren Kejahatan Universal via Internet** — Melakukan penjelajahan internet otonom untuk memetakan *segala jenis tren kejahatan baru* (pidana umum, korupsi, narkotika, TPPU, kejahatan transnasional, hingga kejahatan siber).
6. **Sintesis & Otomatisasi** — Menghubungkan teks hukum dengan modus operandi baru, mengidentifikasi celah regulasi, lalu menghasilkan alur kerja dan kode program utilitas siap pakai di dalam lingkungan *sandbox* yang aman.
7. **Akuntabilitas Mutlak (Audit Trail)** — Mencatat setiap proses penalaran dan pembaruan logika AI ke dalam log *immutable*.

---

## 🏗️ Tech Stack

| Lapisan | Teknologi | Fungsi |
|---------|-----------|--------|
| **Back-End API** | **Python 3.11+** / FastAPI + Uvicorn | REST API, autentikasi, logika bisnis |
| **Orkestrasi AI** | **LangGraph** (+ LangChain) | Mesin state multi-agen yang belajar mandiri |
| **Penyedia LLM** | **Ollama Lokal** (qwen2.5:3b-instruct / qwen2.5-coder:3b) | Penalaran, pembuatan kode, analisis (akselerasi GPU CUDA) |
| **Crawling Otonom** | **Playwright** (Python) | Browser headless untuk ALCD & crawling internet |
| **Model Embedding** | `sentence-transformers/all-MiniLM-L6-v2` | Embedding semantik 384-dimensi (lokal/offline) |
| **DB Relasional** | **PostgreSQL 15+** | Pengguna, kasus, audit log, registri pengetahuan |
| **DB Vektor** | **ChromaDB** (terkontainerisasi) | Embedding hukum & pencarian semantik (diisi secara otonom) |
| **DB Graph** | **Neo4j 5+** (dengan APOC) | Referensi silang, graph ontologi hukum |
| **Front-End** | **TypeScript** / **Next.js 14+** (React 18+) | Dashboard profesional APH (SSR + CSR) |
| **Styling UI** | **Tailwind CSS** + **shadcn/ui** | Pustaka komponen konsisten & aksesibel |
| **Sandbox Kode** | Docker (`network_mode: none`) | Eksekusi kode yang dihasilkan AI secara terisolasi |
| **Infrastruktur** | **Docker Compose** | 5 layanan: api, frontend, postgres, neo4j, chromadb |

---

## 📂 Struktur Proyek

```
ALA/
├── README.MD                 # Penjelasan umum proyek (file ini)
├── ARCHITECTURE.md           # Arsitektur teknis sistem
├── PLAN.md                   # Roadmap pengembangan
├── DEVIN_PROMPT.md           # Prompt instruksi untuk Devin AI
├── API.md                    # Dokumentasi API endpoints
├── DATABASE_SCHEMA.md        # Skema database lengkap
├── AGENTS.md                 # Dokumentasi sistem multi-agent
├── SECURITY.md               # Kebijakan keamanan & guardrails
├── DEPLOYMENT.md             # Panduan deployment
├── CONTRIBUTING.md           # Panduan kontribusi
├── CHANGELOG.md              # Riwayat perubahan versi
├── PROMPTING.md              # Mega-plan & konteks eksekusi
│
├── docker-compose.yml        # 5 layanan: api, frontend, postgres, neo4j, chromadb
├── .env.example              # Template environment variables
│
├── backend/                  # FastAPI back-end (Python 3.11+)
│   ├── Dockerfile            # Image back-end (CUDA 12.4 runtime)
│   ├── requirements.txt      # Dependensi lengkap
│   ├── requirements-core.txt # Dependensi ringan (build cepat)
│   ├── main.py               # Titik masuk FastAPI + health check
│   ├── app/
│   │   ├── config.py         # Settings + HIRO (hardware profiler)
│   │   ├── agents/           # Sistem multi-agen LangGraph
│   │   │   ├── legal_orchestrator.py   # State machine 4 agen
│   │   │   ├── curriculum_designer.py  # ALCD orchestrator (Agent 0)
│   │   │   ├── legal_foundation.py     # Legal Foundation (Agent 1)
│   │   │   ├── internet_crawler.py     # Internet Crawler (Agent 2)
│   │   │   ├── code_generator.py       # Synthesis & Developer (Agent 3)
│   │   │   ├── evaluator.py            # Self-evaluation & guardrails
│   │   │   └── alcd/                   # Sub-modul ALCD (ontology, ingestor, dst.)
│   │   ├── api/v1/           # Router & endpoint API v1
│   │   ├── database/         # Klien postgres.py, chroma.py, neo4j.py
│   │   ├── middleware/       # Isolasi tenant multi-institusi
│   │   ├── models/           # Model ORM multi-tenant (SQLAlchemy)
│   │   └── sandbox/          # Eksekusi kode terisolasi (Docker)
│   └── scripts/
│       └── init_db.py        # Inisialisasi tabel (KOSONG, tanpa data)
│
├── scripts/
│   ├── setup.sh              # Setup otomatis (Linux/macOS)
│   └── setup.ps1             # Setup otomatis (Windows)
│
├── frontend/                 # Dashboard Next.js (TypeScript)
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── next.config.js
│   └── src/
│       ├── app/              # Next.js App Router (layout, dashboard)
│       ├── components/       # Komponen UI (shadcn/ui)
│       └── lib/              # Klien API, utilitas
│
└── tests/                    # Pengujian Python (pytest) — Fase 3+
```

> **CATATAN:** TIDAK ADA direktori `data/` dengan dokumen hukum pra-muat. Semua data ditemukan dan di-ingest secara otonom oleh modul ALCD.

---

## 🚀 Mulai Cepat

### Prasyarat

- **Python 3.11+**
- **Docker & Docker Compose**
- **Ollama** terinstall dengan model `qwen2.5:3b-instruct` dan `qwen2.5-coder:3b`
- **GPU NVIDIA** dengan minimal 4 GB VRAM (untuk akselerasi inferensi)

### 1. Clone Repositori

```bash
git clone <repo-url>
cd ALA
```

### 2. Siapkan Variabel Lingkungan

```bash
cp .env.example .env
# Edit .env dan sesuaikan konfigurasi Ollama jika diperlukan
```

### 3. Jalankan Infrastruktur

```bash
docker compose up -d
```

Ini akan memulai semua layanan: API, Frontend, PostgreSQL, Neo4j, dan ChromaDB.

### 4. Verifikasi Semua Layanan

```bash
# Cek status semua kontainer
docker ps

# Cek kesehatan API (termasuk koneksi Ollama)
curl http://localhost:8080/health
```

Akses dashboard di `http://localhost:3000`
Akses API docs di `http://localhost:8080/docs`

---

## 📚 Dokumentasi

| Dokumen | Keterangan |
|---------|-----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arsitektur teknis lengkap (Polyglot Persistence, data flow) |
| [PLAN.md](PLAN.md) | Roadmap pengembangan per fase |
| [API.md](API.md) | Dokumentasi REST API endpoints |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | Skema tabel PostgreSQL, koleksi ChromaDB, node/edge Neo4j |
| [AGENTS.md](AGENTS.md) | Dokumentasi sistem multi-agent (LangGraph) |
| [SECURITY.md](SECURITY.md) | Kebijakan keamanan, guardrails, dan compliance |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Panduan deployment production |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Panduan kontribusi developer |
| [CHANGELOG.md](CHANGELOG.md) | Riwayat perubahan versi |
| [DEVIN_PROMPT.md](DEVIN_PROMPT.md) | Prompt instruksi untuk Devin AI builder |

---

## ⚖️ Lisensi

Proyek ini bersifat **proprietary** dan dikembangkan untuk keperluan internal Aparat Penegak Hukum (APH) Indonesia. Distribusi tanpa izin dilarang.

---

## 📬 Kontak

Untuk pertanyaan dan kolaborasi, hubungi tim pengembang ALA.
