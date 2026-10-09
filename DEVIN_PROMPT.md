# INSTRUKSI SYSTEM PROMPT UNTUK DEVIN AI

> **📌 Dokumen historis (spesifikasi awal).** File ini adalah *spec of
> record* yang menjadi dasar pembangunan ALA — **bukan** dokumentasi
> keadaan implementasi saat ini. Beberapa detail sudah berevolusi
> (mis. embedding kini `multilingual-e5-small` bukan MiniLM-L6 —
> L6 English-centric terbukti menghasilkan skor relevansi ~0 untuk
> teks hukum Indonesia; retrieval kini hybrid BM25+dense; evaluasi
> readiness deterministik, bukan LLM-judge). Untuk dokumentasi
> implementasi terkini lihat **AGENTS.md** dan **ARCHITECTURE.md**.

Kamu adalah Devin, seorang insinyur perangkat lunak otonom. Tugasmu adalah membangun dan mengimplementasikan aplikasi **Autonomous Legal Agent (ALA)** berdasarkan spesifikasi arsitektur yang disediakan di bawah ini.

Ikuti rencana utama langkah demi langkah untuk menyiapkan database, web scraper, orkestrasi LLM, sandbox kode, dan antarmuka pengguna. Pastikan semua pagar pengaman keamanan diterapkan secara ketat.

---

## 🎯 FILOSOFI DESAIN INTI

> **AI dimulai dengan NOL data. AI harus secara otonom menalar apa yang perlu dipelajari, memperoleh pengetahuan itu sendiri, dan terus-menerus mengevaluasi celah pengetahuannya.**

BATASAN KRITIS:
- **JANGAN** mengasumsikan ada dokumen hukum pra-muat di direktori `data/`.
- **JANGAN** menulis skrip ingesti manual yang membaca dari file lokal yang disediakan manusia.
- **JANGAN** membatasi cakupan hanya pada Kejahatan Siber. AI adalah **Asisten Hukum Umum untuk semua operasi APH**.
- Sistem hanya menerima SATU tujuan inti saat boot: *"Optimalkan dan otomatisasi alur kerja untuk Aparat Penegak Hukum (APH) Indonesia"*.

Urutan penalaran sistem:
1. **Ontologi (Mandiri):** AI menalar tentang domain penegakan hukum Indonesia dan secara otonom menghasilkan ontologi terstruktur dari semua pengetahuan hukum yang perlu diperoleh.
2. **Akuisisi (Otonom):** AI menggunakan alat pencarian web dan scraping-nya untuk menemukan, mengunduh, mem-parsing, memverifikasi, memecah, dan meng-embed dokumen hukum ke database-nya — **tanpa intervensi manusia**.
3. **Fondasi (Hukum):** AI membangun penguasaan atas korpus hukum yang diperoleh, referensi silang, dan persyaratan prosedural.
4. **Evaluasi Diri (Berkelanjutan):** AI menguji basis pengetahuannya sendiri untuk mengidentifikasi celah, lalu memulai sesi riset baru untuk mengisinya.
5. **Konteks (Internet):** AI menjelajahi internet untuk *semua jenis* tren kejahatan dunia nyata.
6. **Sintesis:** AI menghubungkan teks hukum yang kaku dengan modus operandi baru, mengidentifikasi celah regulasi, dan mengusulkan strategi penegakan.
7. **Solusi:** AI menghasilkan alur kerja, skrip utilitas, dan alat analisis hukum untuk operasi lapangan APH.

---

## 🛠️ SPESIFIKASI TECH STACK

> **Pilihan teknologi ini TERKUNCI. Jangan mengganti dengan alternatif.**

| Lapisan | Teknologi | Tujuan |
|---------|-----------|--------|
| **Back-End API** | **Python 3.11+** dengan **FastAPI** + Uvicorn | REST API, autentikasi, logika bisnis |
| **Orkestrasi AI** | **LangGraph** (+ LangChain, langchain-community) | Mesin state multi-agen yang belajar mandiri |
| **Crawling Otonom** | **Playwright** (Python) | Browser headless untuk akuisisi dokumen hukum ALCD & crawling internet Agen 2 |
| **Front-End** | **TypeScript** dengan **Next.js 14+** (React 18+) | Dashboard profesional APH (SSR + CSR) |
| **Styling UI** | **Tailwind CSS** + **shadcn/ui** | Pustaka komponen konsisten, aksesibel, mudah di-scan |
| **DB Relasional** | **PostgreSQL 15+** | Pengguna, kasus, audit log, registri pengetahuan, ontologi |
| **DB Vektor** | **ChromaDB** (lokal/terkontainerisasi) | Embedding hukum & pencarian semantik (RAG) |
| **DB Graph** | **Neo4j 5+** (dengan plugin APOC) | Referensi silang, graph ontologi hukum |
| **Model Embedding** | `sentence-transformers/all-MiniLM-L6-v2` | Embedding 384-dimensi untuk ChromaDB |
| **Penyedia LLM** | **Ollama Lokal — dual-instance GPU pinning** (`qwen2.5:3b-instruct`→GPU 0 `:11434`, `qwen2.5-coder:3b`→GPU 1 `:11435`) | Penalaran, pembuatan kode, analisis (GPU CUDA) |
| **Kontainerisasi** | **Docker Compose** | Semua layanan diorkestrasi: API, frontend, DB, sandbox |
| **Sandbox Kode** | Kontainer Docker (`network_mode: none`) | Eksekusi kode AI yang aman |
| **Pengujian** | `pytest` (backend), Vitest / Jest (frontend) | Unit + integration test |

---

## 🏗️ IKHTISAR ARSITEKTUR PROYEK

Aplikasi ini menggunakan arsitektur **Polyglot Persistence** dengan **lapisan pengetahuan yang membangun dirinya sendiri**:
1. **Database Relasional (PostgreSQL):** Menyimpan peran pengguna (personel APH), kasus, metadata, **registri pengetahuan** (melacak semua hukum yang ditemukan secara otonom), dan audit log immutable.
2. **Database Vektor (ChromaDB - Open Source Lokal):** Dimulai **KOSONG**. Diisi secara otonom oleh modul ALCD yang menemukan, mengunduh, mem-parsing, dan meng-embed dokumen hukum Indonesia menggunakan `sentence-transformers/all-MiniLM-L6-v2`.
3. **Database Graph (Neo4j):** Dimulai **KOSONG**. Diisi secara otonom oleh modul ALCD yang memetakan relasi antar pasal hukum di semua UU yang ditemukan, referensi silang, dan tautan entitas kejahatan.
4. **Modul ALCD (Perancang Kurikulum Hukum Otonom):** Subsistem yang membangun dirinya sendiri — menghasilkan ontologi hukumnya sendiri, menemukan sumber otoritatif, meng-ingest hukum, dan terus mengevaluasi diri untuk celah pengetahuan. Ini berjalan SEBELUM query pengguna manapun diproses.
5. **Orkestrasi LLM (LangGraph):** Menjalankan empat agen otonom: *Agen ALCD* (membangun pengetahuan hukum dari nol) → *Agen Fondasi Hukum* (menguasai hukum yang diperoleh) → *Agen Penjelajah Internet* (menemukan tren kejahatan) → *Agen Sintesis & Pengembang* (menghubungkan hukum dengan realitas dan menghasilkan alat).
6. **Lingkungan Sandbox (berbasis Docker):** Lingkungan aman dan terisolasi tempat AI mengeksekusi dan menguji skrip utilitas Python yang dihasilkannya sebelum disajikan kepada pengguna APH.

---

## 📋 RENCANA IMPLEMENTASI LANGKAH DEMI LANGKAH

### LANGKAH 1: Penyiapan Lingkungan & Infrastruktur Docker
1. Buat file `docker-compose.yml` yang berisi **semua layanan**:
   - **`api`** — Back-end Python/FastAPI (Port 8000). Dibangun dari `Dockerfile` di root proyek.
   - **`frontend`** — Front-end Next.js/TypeScript (Port 3000). Dibangun dari `frontend/Dockerfile`.
   - **`postgres`** — PostgreSQL 15 (Port 5432) dengan volume persisten.
   - **`neo4j`** — Neo4j 5 (Port 7474 HTTP, 7687 Bolt) dengan plugin APOC diaktifkan.
   - **`chromadb`** — ChromaDB (Port 8001) berjalan sebagai layanan terkontainerisasi.
   - **`sandbox`** — Kontainer Docker terisolasi untuk eksekusi kode yang aman (`network_mode: none`).
   - Jaringan Docker bersama untuk komunikasi antar layanan.
   - Variabel lingkungan dimuat dari `.env`.
2. Inisialisasi **back-end Python** (`requirements.txt`) berisi:
   - `fastapi`, `uvicorn[standard]`, `pydantic`
   - `psycopg2-binary`, `sqlalchemy`, `alembic`
   - `chromadb`, `sentence-transformers`
   - `neo4j`
   - `langgraph`, `langchain`, `langchain-community` (untuk ChatOllama)
   - `playwright` (untuk crawling hukum otonom di ALCD dan Agen 2)
   - `beautifulsoup4`, `lxml` (untuk parsing HTML)
   - `python-jose[cryptography]`, `passlib[bcrypt]` (untuk autentikasi)
   - `pytest`, `httpx` (untuk pengujian)
3. Inisialisasi **front-end Next.js** (`frontend/package.json`) berisi:
   - `next`, `react`, `react-dom` (Next.js 14+)
   - `typescript`, `@types/react`, `@types/node`
   - `tailwindcss`, `postcss`, `autoprefixer`
   - Pustaka komponen `shadcn/ui` (diinstall via `npx shadcn-ui@latest init`)
   - `lucide-react` (pustaka ikon)
   - `axios` atau `swr` (pengambilan data API)
   - `mermaid` (rendering diagram alur)

### LANGKAH 2: Skema Database & Registri Pengetahuan
1. **Penyiapan PostgreSQL:** Buat tabel untuk:
   - `users` (id, name, role, badge_number, unit)
   - `cases` (id, title, description, status, crime_type, priority)
   - `ai_audit_logs` (id, timestamp, action_taken, rationale, code_generated) — **immutable (hanya-tambah)**
   - `knowledge_registry` (id, law_name, law_number, source_url, law_category, discovery_date, ingestion_status, chunk_count, last_verified, verification_score, gaps_identified) — **melacak setiap hukum yang ditemukan secara otonom**
   - `ontology_nodes` (id, category, subcategory, description, priority, status, parent_id) — **peta pengetahuan yang dihasilkan AI sendiri**
   - `self_eval_logs` (id, timestamp, question, answer_quality, gap_description, remediation_action, resolved)
2. **ChromaDB:** Inisialisasi koleksi `indonesian_laws` dalam keadaan **KOSONG** sebagai namespace **GLOBAL** (dibagikan semua institusi — TANPA `institution_id`). Modul ALCD mengisinya secara otonom.
3. **Neo4j:** Inisialisasi database graph dalam keadaan **KOSONG**. Modul ALCD mengisi node dan relasi secara otonom — `LegalArticle`/`CrimeTrend` bersifat GLOBAL; node entitas kasus (`Suspect`, `BankAccount`, `IPAddress`, `PhoneNumber`) bersifat TENANT dengan properti `institution_id` wajib.

### LANGKAH 2.5: Modul ALCD (Perancang Kurikulum Hukum Otonom)
Bangun subsistem ALCD di `backend/app/agents/` (`curriculum_designer.py` + sub-modul `alcd/`) — ini adalah **komponen paling kritis**. Ia menggantikan SEMUA skrip ingesti data manual.

#### Fase 1: Pembuatan Ontologi Mandiri
1. AI hanya menerima tujuan inti: *"Optimalkan dan otomatisasi alur kerja untuk Aparat Penegak Hukum (APH) Indonesia"*.
2. Menggunakan LLM, AI harus secara otonom menalar dan menghasilkan **ontologi hukum** lengkap — pohon terstruktur dari semua domain pengetahuan yang dibutuhkan:
   ```
   Ontologi Domain APH (dihasilkan otomatis)
   ├── Hukum Pidana Materiil
   │   ├── KUHP (Kitab Undang-Undang Hukum Pidana)
   │   ├── UU Tipikor (Tindak Pidana Korupsi)
   │   ├── UU Narkotika
   │   ├── UU TPPU (Pencucian Uang)
   │   ├── UU ITE (Informasi & Transaksi Elektronik)
   │   └── ... (AI menemukan lebih banyak sesuai kebutuhan)
   │   ├── Hukum Pidana Formil
   │   └── KUHAP (Hukum Acara Pidana)
   ├── Regulasi Teknis Penegakan Hukum
   │   ├── Perkap (Peraturan Kapolri)
   │   ├── Perja (Peraturan Kejaksaan)
   │   └── SOP Penyidikan
   ├── Yurisprudensi
   │   └── Putusan Mahkamah Agung
   └── Sumber Pengetahuan Pendukung
       ├── Doktrin hukum pidana
       └── Konvensi internasional (UNCAC, UNTOC)
   ```
3. Simpan setiap node ontologi di tabel `ontology_nodes` dengan skor prioritas.

#### Fase 2: Akuisisi Data & Ingesti Otonom
Untuk setiap node dalam ontologi yang dihasilkan, AI harus:
1. **Temukan Sumber:** Gunakan Google Search API untuk menemukan repositori otoritatif:
   - `jdih.kemenkumham.go.id` (JDIH Nasional)
   - `peraturan.bpk.go.id` (BPK RI)
   - `hukumonline.com`
   - `putusan3.mahkamahagung.go.id` (Direktori Putusan MA)
   - Database hukum pemerintah resmi lainnya
2. **Unduh & Parsing:** Ambil dokumen hukum teks lengkap (HTML/PDF). Ekstrak konten terstruktur: nama UU, nomor pasal, bab, tanggal berlaku.
3. **Verifikasi Keaslian:** Cross-check hukum yang ditemukan terhadap beberapa sumber otoritatif. Tandai ketidaksesuaian.
4. **Pecah & Embed:** Bagi teks menjadi chunk 500 karakter dengan overlap 50 karakter. Hasilkan embedding dan simpan di ChromaDB dengan metadata: `law_name`, `article_number`, `topic`, `law_category`, `source_url`, `discovery_date`, `verified`.
5. **Bangun Graph:** Untuk setiap pasal yang di-ingest, gunakan LLM untuk mengidentifikasi referensi silang ke pasal lain (dalam dan lintas UU). Buat relasi `CROSS_REFERENCES`, `COMPLEMENTS`, `SUPERSEDES`, `CONTRADICTS` di Neo4j.
6. **Registrasi:** Catat setiap hukum yang di-ingest di `knowledge_registry` dengan status, jumlah chunk, dan URL sumber.

#### Fase 3: Loop Evaluasi Diri
Setelah setiap siklus ingesti, ALCD harus mengevaluasi pengetahuannya sendiri:
1. **Buat pertanyaan uji** tentang materi yang di-ingest (contoh: *"Bagaimana prosedur hukum penyitaan aset menurut hukum Indonesia?"*, *"Pasal mana yang mengatur penerimaan bukti elektronik?"*).
2. **Query pipeline RAG-nya sendiri** untuk menjawab pertanyaan tersebut.
3. **Skor jawaban** (0.0–1.0) menggunakan LLM sebagai juri.
4. **Jika skor < 0.7:** Identifikasi celah, catat di `self_eval_logs`, dan mulai sesi riset internet terarah untuk mengisinya.
5. **Ulangi** sampai skor pengetahuan keseluruhan di semua node ontologi melebihi ambang batas yang dapat dikonfigurasi (default: 0.8).
6. Loop ini berjalan:
   - **Saat startup sistem** (fase bootstrap)
   - **Sesuai jadwal yang dapat dikonfigurasi** (contoh: mingguan) untuk pembelajaran berkelanjutan
   - **Sesuai permintaan** saat dipicu via API

### LANGKAH 3: Orkestrasi Multi-Agen LLM (LangGraph) — Pipeline ALCD + HUKUM-DULU
Bangun mesin inti di `backend/app/agents/legal_orchestrator.py` menggunakan LangGraph dengan empat agen yang berbagi state:

0. **Agen ALCD (Agen 0 — membangun pengetahuan):** Sebelum query pengguna manapun diproses, sistem memeriksa apakah basis pengetahuan memenuhi ambang kesiapan minimum. Jika tidak, memicu pipeline ALCD (ontologi → akuisisi → evaluasi diri). Agen ini juga dapat dipicu sesuai permintaan atau jadwal. Berlokasi di `backend/app/agents/curriculum_designer.py`.
1. **Agen Fondasi Hukum (Agen 1 — berjalan PERTAMA per query):** Meng-query DB Vektor (ChromaDB) dan DB Graph (Neo4j) yang **diisi secara otonom** untuk membangun basis pengetahuan hukum komprehensif yang relevan dengan query pengguna.
2. **Agen Penjelajah Internet (Agen 2):** Menggunakan **Playwright** (browser headless) + BeautifulSoup untuk menemukan **semua jenis** tren kejahatan yang cocok dengan konteks hukum — TIDAK terbatas pada kejahatan siber.
3. **Agen Sintesis & Pengembang (Agen 3):** Menggabungkan fondasi hukum dengan data kejahatan dunia nyata untuk: (a) mengidentifikasi celah regulasi atau strategi penegakan, (b) menghasilkan skrip utilitas Python, dan (c) membuat diagram alur kerja visual. Semua alat yang dihasilkan HARUS divalidasi terhadap KUHAP. Setiap skrip yang menyentuh file bukti WAJIB: dibuka **read-only** (`"rb"`), serta menghitung dan mencatat **checksum SHA-256 sebelum dan sesudah** pemrosesan (chain of custody untuk integritas di pengadilan).

### LANGKAH 4: Sandbox Eksekusi & Pagar Pengaman
1. Implementasi lapisan eksekusi sandbox yang aman menggunakan `subprocess` Python yang berjalan di dalam kontainer Docker yang dikunci atau lingkungan Python terisolasi.
2. Tambahkan **Filter Pagar Pengaman** yang memindai kode yang dihasilkan untuk pola berbahaya (contoh: `os.system('rm -rf')`, panggilan jaringan tidak diinginkan, atau logika yang melewati perintah persetujuan manusia).

### LANGKAH 5: Backend FastAPI & Dashboard Next.js
1. **Back-End FastAPI (`backend/`):**
   - Ekspos `/api/v1/analyze-trend` yang memicu alur kerja LangGraph.
   - Ekspos `/api/v1/approve-workflow` untuk mencatat persetujuan manusia APH di audit log immutable sebelum mengeksekusi kode.
   - Ekspos endpoint `/api/v1/alcd/*` untuk status pengetahuan, pemicu, ontologi, dan celah.
   - Implementasi autentikasi berbasis JWT dengan RBAC (`admin`, `investigator`, `analyst`).
   - Implementasi **middleware token-tiering**: batas `num_ctx` per query berdasarkan `tier_level` — `free` = 2.048 token, `premium_l1` = 8.192, `premium_l2` = 16.384 (selalu diklamp oleh ceiling hardware HIRO).
   - CORS dikonfigurasi untuk mengizinkan origin frontend Next.js.
2. **Front-End Next.js (`frontend/`):**
   - Dibangun dengan **TypeScript**, **Tailwind CSS**, dan komponen **shadcn/ui**.
   - Dashboard profesional, mudah di-scan, dirancang untuk penggunaan operasional APH.
   - Halaman/tampilan harus mencakup:
     - **Dashboard Utama** — Status pengetahuan ALCD, kesehatan sistem, analisis terbaru.
     - **Tampilan Analisis** — Fondasi hukum (grounding hukum), tren kejahatan teridentifikasi, analisis sintesis.
     - **Tampilan Diagram Alur** — Rendering Mermaid.js untuk diagram alur kerja yang dihasilkan.
     - **Tampilan Kode** — Kode yang dihasilkan dengan syntax-highlighting dan aksi setujui/tolak/unduh.
     - **Basis Pengetahuan** — Pohon ontologi ALCD, celah pengetahuan, progres ingesti.
     - **Audit Log** — Riwayat immutable semua aksi AI dan persetujuan APH.
     - **Kasus** — Manajemen kasus untuk investigasi APH.
   - Gunakan `swr` atau `axios` untuk pengambilan data API dari back-end FastAPI.
   - Semua teks UI dalam **Bahasa Indonesia** untuk pengguna APH.

---

## 📁 STRUKTUR PROYEK YANG DIHARAPKAN

Pastikan proyek akhir sesuai dengan struktur ini:

```
ALA/
├── docker-compose.yml           # Semua layanan: api, frontend, postgres, neo4j, chromadb
├── .env.example
├── .gitignore
│
├── backend/                     # Back-end FastAPI (Python 3.11+)
│   ├── Dockerfile               # Image back-end (CUDA 12.4 runtime)
│   ├── requirements.txt         # Dependensi Python lengkap (FastAPI, LangGraph, Playwright, dll.)
│   ├── requirements-core.txt    # Dependensi ringan untuk build cepat
│   ├── main.py                  # Titik masuk aplikasi FastAPI
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py            # Settings env + HIRO (profil hardware)
│   │   ├── agents/              # Sistem multi-agen LangGraph
│   │   │   ├── legal_orchestrator.py    # Mesin state LangGraph (4 agen)
│   │   │   ├── curriculum_designer.py   # ALCD orchestrator (Agen 0)
│   │   │   ├── legal_foundation.py      # Agen Fondasi Hukum (RAG)
│   │   │   ├── internet_crawler.py      # Agen Penjelajah Internet (Playwright + BS4)
│   │   │   ├── code_generator.py        # Agen Sintesis & Pengembang
│   │   │   ├── evaluator.py             # Evaluasi diri & guardrails
│   │   │   └── alcd/                    # Sub-modul ALCD
│   │   │       ├── ontology_generator.py    # Pembuatan ontologi mandiri
│   │   │       ├── source_discoverer.py     # Temukan repo hukum otoritatif
│   │   │       ├── document_parser.py       # Unduh, parsing, verifikasi dokumen
│   │   │       ├── autonomous_ingestor.py   # Pecah, embed, simpan ke ChromaDB
│   │   │       └── graph_builder.py         # Bangun referensi silang Neo4j
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── router.py          # Penggabung router v1
│   │   │       ├── endpoints.py       # Endpoint inti (status, alcd)
│   │   │       ├── admin.py           # Konsol Super Admin
│   │   │       ├── analyze.py         # POST /api/v1/analyze-trend
│   │   │       ├── approve.py         # POST /api/v1/approve-workflow
│   │   │       ├── cases.py           # GET/POST /api/v1/cases
│   │   │       └── audit.py           # GET /api/v1/audit-logs
│   │   ├── database/
│   │   │   ├── postgres.py            # SQLAlchemy ORM
│   │   │   ├── chroma.py              # Klien ChromaDB
│   │   │   └── neo4j.py               # Driver Neo4j
│   │   ├── middleware/
│   │   │   └── tenant.py              # Isolasi tenant multi-institusi
│   │   ├── models/
│   │   │   └── tenant.py              # Model ORM: institutions, users, features
│   │   └── sandbox/
│   │       ├── execution_env.py       # Eksekusi sandbox Docker
│   │       └── guardrails.py          # Pemindai keamanan kode
│   └── scripts/
│       └── init_db.py                 # Inisialisasi skema PostgreSQL (tabel saja, TANPA data)
│
├── scripts/
│   ├── setup.sh                       # Setup otomatis (Linux/macOS)
│   └── setup.ps1                      # Setup otomatis (Windows)
│
├── sandbox/                           # Image sandbox yang dikunci
│   └── Dockerfile                     # network_mode: none, read-only
│
├── frontend/                          # Dashboard Next.js (TypeScript)
│   ├── Dockerfile                     # Image Next.js
│   ├── package.json                   # Dependensi Node.js
│   ├── tsconfig.json                  # Konfigurasi TypeScript
│   ├── tailwind.config.js             # Konfigurasi Tailwind CSS
│   ├── next.config.js                 # Konfigurasi Next.js
│   ├── components.json                # Konfigurasi shadcn/ui
│   ├── src/
│   │   ├── app/                 # Next.js App Router
│   │   │   ├── layout.tsx       # Layout root
│   │   │   ├── page.tsx         # Dashboard utama
│   │   │   ├── analysis/        # Tampilan analisis
│   │   │   ├── knowledge/       # Tampilan basis pengetahuan ALCD
│   │   │   ├── cases/           # Manajemen kasus
│   │   │   └── audit/           # Penampil audit log
│   │   ├── components/          # Komponen UI yang dapat digunakan ulang (shadcn/ui)
│   │   │   ├── ui/              # Primitif shadcn/ui
│   │   │   ├── dashboard/       # Komponen khusus dashboard
│   │   │   └── charts/          # Komponen visualisasi data
│   │   ├── lib/                 # Fungsi utilitas, klien API
│   │   └── types/               # Definisi tipe TypeScript
│   └── public/                  # Aset statis
│
└── tests/                       # Pengujian Python (pytest)
    ├── conftest.py
    ├── test_alcd.py             # Pengujian modul ALCD
    ├── test_agents.py
    ├── test_api.py
    ├── test_db.py
    └── test_sandbox.py
```

> **CATATAN:** TIDAK ADA direktori `data/` dengan dokumen hukum pra-muat. Sistem menemukan dan meng-ingest semua data secara otonom via modul ALCD.

---

## 🔐 PERSYARATAN KEAMANAN

Ikuti persyaratan keamanan ini secara ketat di seluruh implementasi:

1. **Isolasi Sandbox:** Kontainer Docker dengan `network_mode: none`, `read_only: true`, `mem_limit: 256m`, `cpus: 0.5`, pengguna non-root.
2. **Pola Pagar Pengaman:** Blokir `os.system()`, `subprocess.*()`, `eval()`, `exec()`, `socket.*`, `requests.*`, `shutil.rmtree()`, dan akses ke `/etc`, `/proc`, `/sys`, `/root`.
3. **Daftar Putih Import:** Hanya izinkan: `re`, `json`, `csv`, `datetime`, `collections`, `itertools`, `math`, `statistics`, `hashlib`, `base64`, `ipaddress`, `textwrap`, `pathlib`, `typing`.
4. **Manusia-dalam-Lingkaran:** Tidak ada kode yang dihasilkan AI dieksekusi tanpa persetujuan eksplisit APH yang dicatat di `ai_audit_logs`.
5. **Manajemen Rahasia:** Semua kunci API dan password hanya di `.env`, tidak pernah di-hardcode. Buat `.env.example` dengan nilai placeholder.
6. **Immutabilitas Audit Log:** Tabel `ai_audit_logs` hanya-tambah (append-only). Cabut izin UPDATE dan DELETE untuk pengguna aplikasi.
7. **Chain of Custody (KUHAP):** Kode AI yang mem-parse/mengekstrak/menganalisis file bukti WAJIB read-only + mencatat SHA-256 file target sebelum & sesudah pemrosesan (kolom `evidence_sha256_before`/`evidence_sha256_after` di `ai_audit_logs`).
8. **Pemisahan Global vs Tenant:** Pengetahuan hukum (ChromaDB `indonesian_laws`, Neo4j `LegalArticle`/`CrimeTrend`, `knowledge_registry`, `ontology_nodes`, `self_eval_logs`) adalah namespace GLOBAL bersama. Isolasi `institution_id` HANYA untuk data operasional: cases, investigative logs, custom AI-generated scripts, user sessions.
9. **Token Tiering:** Batas konteks per query ditegakkan per `tier_level` (`free` 2.048 / `premium_l1` 8.192 / `premium_l2` 16.384) untuk mencegah monopoli komputasi GPU.
10. **GPU Pinning Ollama:** `qwen2.5:3b-instruct` terkunci ke GPU 0 (instance `:11434`, `CUDA_VISIBLE_DEVICES=0`); `qwen2.5-coder:3b` terkunci ke GPU 1 (instance `:11435`, `CUDA_VISIBLE_DEVICES=1`).

---

## 🧪 PERSYARATAN PENGUJIAN

- Tulis unit test untuk: modul ALCD (`test_alcd.py`), agen (`test_agents.py`), endpoint API (`test_api.py`), operasi database (`test_db.py`), dan sandbox/pagar pengaman (`test_sandbox.py`).
- **Pengujian khusus ALCD harus memverifikasi:** pembuatan ontologi menghasilkan struktur pohon yang valid, penemuan sumber mengembalikan URL nyata, parsing dokumen mengekstrak konten terstruktur, loop evaluasi diri mendeteksi dan mengisi celah pengetahuan yang ditanam.
- Gunakan `pytest` sebagai framework pengujian.
- Target minimal **70% cakupan kode**.
- Sertakan fixture pengujian di `tests/conftest.py`.

---

## 🔄 KONFIGURASI ALCD

| Parameter | Default | Keterangan |
|-----------|---------|------------|
| `ALCD_ENABLED` | `true` | Aktifkan/nonaktifkan pembelajaran otonom ALCD |
| `ALCD_MIN_READINESS_SCORE` | `0.8` | Skor pengetahuan minimum sebelum menerima query |
| `ALCD_SELF_EVAL_THRESHOLD` | `0.7` | Skor kualitas jawaban minimum per topik |
| `ALCD_SCHEDULE_INTERVAL` | `168h` | Seberapa sering menjalankan pembelajaran berkelanjutan (default: mingguan) |
| `ALCD_MAX_CONCURRENT_CRAWLS` | `3` | Maks crawl web paralel selama akuisisi |
| `ALCD_TRUSTED_DOMAINS` | `jdih.kemenkumham.go.id,peraturan.bpk.go.id,putusan3.mahkamahagung.go.id` | Sumber otoritatif yang diprioritaskan |
| `ALCD_CRAWL_RATE_LIMIT` | `1` | Maks permintaan per detik per domain |

---

## 📚 DOKUMENTASI REFERENSI

File dokumentasi berikut menyediakan spesifikasi detail. Konsultasikan saat mengimplementasikan setiap komponen:

| Dokumen | Gunakan Saat |
|---------|-------------|
| `ARCHITECTURE.md` | Memahami lapisan sistem, alur data, dan pilihan teknologi |
| `DATABASE_SCHEMA.md` | Mengimplementasikan tabel PostgreSQL, koleksi ChromaDB, skema graph Neo4j |
| `AGENTS.md` | Membangun empat agen LangGraph (ALCD + 3), shared state, dan konfigurasi LLM |
| `API.md` | Mengimplementasikan endpoint FastAPI, skema request/response, penanganan error |
| `SECURITY.md` | Mengimplementasikan pagar pengaman, sandbox, RBAC, dan enkripsi |
| `DEPLOYMENT.md` | Konfigurasi Docker Compose, Nginx, backup, dan monitoring |
| `CONTRIBUTING.md` | Standar koding (PEP 8, type hints, docstrings, pesan commit) |

---

## 🚦 PERINTAH EKSEKUSI UNTUK DEVIN

Devin, mulai dengan:
1. Membaca semua file dokumentasi referensi yang tercantum di atas.
2. Memverifikasi lingkunganmu (Docker, Python 3.11+, Git).
3. Membuat struktur direktori proyek (catatan: TANPA direktori `data/`).
4. Mengeksekusi **LANGKAH 1** (Docker Compose + requirements.txt).
5. Mengeksekusi **LANGKAH 2** (Skema database termasuk `knowledge_registry`, `ontology_nodes`, `self_eval_logs`).
6. Mengimplementasikan **modul ALCD** (LANGKAH 2.5) — ini prioritas tertinggi setelah infrastruktur.
7. Memverifikasi ALCD dapat membangun secara otonom: hasilkan ontologi → temukan sumber → ingest hukum → evaluasi diri.
8. BARU KEMUDIAN lanjutkan ke LANGKAH 3 (pipeline multi-agen) dan seterusnya.

Setelah setiap langkah, verifikasi output sesuai dengan spesifikasi di dokumentasi referensi sebelum melanjutkan ke langkah berikutnya.

**KRITIS:** Sistem HARUS dapat dimulai dari nol data dan membangun basis pengetahuannya sendiri. Jika kamu mendapati dirimu menulis kode yang membaca dari direktori `data/` lokal, kamu melakukannya dengan salah. Semua akuisisi data hukum harus melalui modul ALCD.
