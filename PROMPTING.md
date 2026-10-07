# PROMPT UTAMA & MEGA-PLAN DEVIN: AUTONOMOUS LEGAL AGENT (ALA)

## 🎯 TUJUAN SISTEM
Membangun sistem intelijen otonom berkepatuhan tinggi untuk Aparat Penegak Hukum (APH) Indonesia. Sistem dimulai dengan NOL dokumen pra-muat. Sistem harus secara otonom menalar hukum apa yang dibutuhkan, menjelajahi internet untuk mengunduhnya, memetakannya ke database polyglot, melakukan evaluasi diri, dan menghasilkan alur kerja/alat utilitas di dalam sandbox yang aman.

---

## 🛠️ KUNCI TECH STACK (LOKAL & OFFLINE)
- **Back-End / AI:** Python 3.11+, FastAPI, LangGraph, Playwright
- **Penyedia LLM:** **Ollama** lokal — akselerasi GPU CUDA pada mesin host
  - **Penalaran Hukum (Agen 0–2):** `qwen2.5:3b-instruct` (~1.9 GB VRAM)
  - **Pembuatan Kode (Agen 3):** `qwen2.5-coder:3b` (~1.9 GB VRAM)
  - Koneksi: `http://host.docker.internal:11434` dari kontainer Docker
- **Model Embedding:** `sentence-transformers/all-MiniLM-L6-v2` lokal via HuggingFace (mampu offline)
- **Front-End:** TypeScript, Next.js (App Router), Tailwind CSS, Shadcn/ui
- **Database:** Arsitektur Polyglot via Docker Compose
  1. PostgreSQL (Data Transaksional, Audit Log, Manajemen Kasus)
  2. ChromaDB (Pencarian Vektor / RAG untuk hukum yang di-crawl)
  3. Neo4j (Database Graph untuk ontologi hukum dan pemetaan relasi)

### Profil Perangkat Keras GPU
| GPU | Model | VRAM | Peran (TERKUNCI) |
|-----|-------|------|-------|
| GPU 0 | NVIDIA GeForce GTX 1050 Ti | 4 GB | **Eksklusif** — `qwen2.5:3b-instruct` (Agen 0–2: ALCD, Fondasi Hukum, Penjelajah) |
| GPU 1 | NVIDIA GeForce GTX 1050 Ti | 4 GB | **Eksklusif** — `qwen2.5-coder:3b` (Agen 3: Sintesis & Pengembang) |

> **BATASAN:** Ukuran model maksimal = **3B parameter** (kuantisasi Q4). Model 7B+ akan OOM pada 4GB VRAM.
>
> **WAJIB — Pinning Dual-GPU:** Kedua model **TIDAK BOLEH** berbagi GPU yang sama. `qwen2.5:3b-instruct` dikunci penuh ke **GPU 0** dan `qwen2.5-coder:3b` dikunci penuh ke **GPU 1** untuk mencegah crash Out-Of-Memory (OOM). Lihat bagian HIRO §1a untuk konfigurasi runtime.

---

## 🚀 PENYESUAIAN KODE — INTEGRASI OLLAMA

Saat menginisialisasi klien LLM di `backend/app/config.py`, gunakan ChatOllama:

```python
from langchain_community.chat_models import ChatOllama

# Model penalaran hukum (Agen 0-2: ALCD, Fondasi Hukum, Penjelajah Internet)
# Instance Ollama #1 — TERKUNCI ke GPU 0 (CUDA_VISIBLE_DEVICES=0)
llm_reasoning = ChatOllama(
    model="qwen2.5:3b-instruct",
    base_url="http://host.docker.internal:11434",   # OLLAMA_REASONING_URL
    temperature=0.2,
)

# Model pembuatan kode (Agen 3: Sintesis & Pengembang)
# Instance Ollama #2 — TERKUNCI ke GPU 1 (CUDA_VISIBLE_DEVICES=1)
llm_coder = ChatOllama(
    model="qwen2.5-coder:3b",
    base_url="http://host.docker.internal:11435",   # OLLAMA_CODER_URL
    temperature=0.1,
)
```

> **Dual-instance Ollama:** GPU pinning dicapai dengan menjalankan **dua instance Ollama** di host — instance `:11434` dengan `CUDA_VISIBLE_DEVICES=0` (khusus `qwen2.5:3b-instruct`) dan instance `:11435` dengan `CUDA_VISIBLE_DEVICES=1` (khusus `qwen2.5-coder:3b`). Jika hanya satu instance yang tersedia, `OLLAMA_CODER_URL` fallback ke `OLLAMA_REASONING_URL`.

---

## ⚡ HARDWARE INTELLIGENCE & RESOURCE OPTIMIZER (HIRO)

Sistem secara otomatis memprofilkan sumber daya perangkat keras saat startup dan mengunci parameter eksekusi optimal. Implementasi di `backend/app/config.py`.

### 1. Deteksi GPU & Akselerasi CUDA
- Menggunakan `torch.cuda` untuk mendeteksi GPU NVIDIA yang kompatibel.
- **Jika CUDA tersedia:** Semua tugas LLM dan Embedding berat secara otomatis diarahkan ke GPU. Parameter Ollama (`num_ctx`, `num_predict`) dioptimalkan berdasarkan VRAM yang tersedia.
- **Fallback:** Jika TIDAK ada GPU CUDA, sistem secara anggun beralih ke eksekusi CPU tanpa error fatal.

### 1a. Alokasi Dual-GPU — Isolasi Model per GPU (Ollama CUDA Tuning)

Host menjalankan **2× NVIDIA GTX 1050 Ti (4 GB VRAM masing-masing)**. Untuk mencegah dua model 3B berebut VRAM pada satu GPU (OOM crash), HIRO **WAJIB** mengunci setiap model ke GPU khusus:

| Instance Ollama | Port | `CUDA_VISIBLE_DEVICES` | Model Terkunci | Melayani |
|-----------------|------|----------------------|----------------|----------|
| Instance #1 | `11434` | `0` | `qwen2.5:3b-instruct` | Agen 0–2 (penalaran) |
| Instance #2 | `11435` | `1` | `qwen2.5-coder:3b` | Agen 3 (codegen) |

Definisi environment host (contoh systemd override per instance):
```bash
# /etc/systemd/system/ollama.service.d/override.conf  (instance utama — GPU 0)
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"

# /etc/systemd/system/ollama-coder.service.d/override.conf  (instance coder — GPU 1)
Environment="OLLAMA_HOST=0.0.0.0:11435"
Environment="CUDA_VISIBLE_DEVICES=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
```

Aturan HIRO:
- `get_ollama_reasoning_url()` → `OLLAMA_REASONING_URL` (default `http://host.docker.internal:11434`)
- `get_ollama_coder_url()` → `OLLAMA_CODER_URL` (default `http://host.docker.internal:11435`, fallback ke reasoning URL jika instance tunggal)
- `OLLAMA_MAX_LOADED_MODELS=1` + `OLLAMA_NUM_PARALLEL=1` per instance — satu model per GPU, tanpa spillover VRAM
- Verifikasi saat startup: `print_hardware_report()` mencetak pemetaan model→GPU; jika GPU 1 hilang, sistem fallback ke instance tunggal dengan antrian sekuensial (bukan paralel)

### 2. Alokasi Memori Model Embedding (HuggingFace Offline)
- Untuk `sentence-transformers/all-MiniLM-L6-v2`, pemetaan perangkat dikonfigurasi secara dinamis:
  ```python
  from app.config import get_embedding_device
  device = get_embedding_device()  # "cuda" atau "cpu"
  ```

### 3. Optimasi Core CPU & RAM
- Pool worker paralel: `max(1, os.cpu_count() - 1)`.
- Batas Sandbox: mikro-kontainer tidak pernah melebihi **25% total RAM host**.

### 4. Parameter Ollama Dinamis Berdasarkan VRAM

| VRAM Tersedia | `num_ctx` | `num_predict` |
|---------------|-----------|---------------|
| ≥ 8 GB        | 8192      | 2048          |
| ≥ 4 GB        | 4096      | 1024          |
| ≥ 2 GB        | 2048      | 512           |
| < 2 GB (CPU)  | 2048      | 256           |

### Fungsi Utilitas HIRO

| Fungsi | Kegunaan |
|--------|----------|
| `get_embedding_device()` | `"cuda"` atau `"cpu"` untuk model embedding |
| `get_max_workers()` | Worker paralel optimal untuk crawling/indexing |
| `get_sandbox_mem_limit()` | Batas memori sandbox (misal `"3968m"`) |
| `print_hardware_report()` | Cetak laporan profil ke konsol saat startup |

---

## 🏢 MODUL: MULTI-TENANT LINTAS-INSTITUSI B2B SAAS & KLASTERISASI AI

ALA dirancang sebagai platform **B2B SaaS multi-tenant** yang melayani berbagai institusi penegak hukum Indonesia secara terisolasi. Setiap institusi memiliki data, kasus, dan alat AI-nya sendiri yang terisolasi ketat.

### 1. Skema Multi-Tenancy Database (PostgreSQL 15+)

```sql
-- Institusi yang dilayani platform
CREATE TABLE institutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,            -- POLRI, Kejaksaan, Mahkamah Agung, dll
    type VARCHAR(50) NOT NULL,             -- kepolisian, kejaksaan, pengadilan
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Pengguna dengan ikatan institusi dan tier
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id UUID NOT NULL REFERENCES institutions(id),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,             -- super_admin, admin_instansi, penyidik, jaksa, hakim
    tier_level VARCHAR(20) DEFAULT 'free', -- free, premium_l1, premium_l2
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Kategori fitur (domain hukum)
CREATE TABLE feature_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,            -- Pidum, Tipikor, Cyber, Narkotika, TPPU, dll
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Fitur individual (alat, alur kerja, skrip)
CREATE TABLE features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES feature_categories(id),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    required_tier VARCHAR(20) DEFAULT 'free',  -- free, premium_l1, premium_l2
    is_ai_generated BOOLEAN DEFAULT FALSE,
    ai_complexity_score FLOAT,                  -- 0.0–1.0, dihitung oleh Evaluator Agent
    ai_cuda_weight FLOAT,                       -- estimasi beban GPU
    ai_suggested_tier VARCHAR(20),              -- saran tier dari AI
    admin_approved_tier VARCHAR(20),            -- tier final dari Super Admin
    is_active BOOLEAN DEFAULT TRUE,
    telemetry_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Pemetaan fitur ke institusi (kontrol Super Admin)
CREATE TABLE institution_features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id UUID NOT NULL REFERENCES institutions(id),
    feature_id UUID NOT NULL REFERENCES features(id),
    is_enabled BOOLEAN DEFAULT TRUE,
    enabled_by UUID REFERENCES users(id),       -- Super Admin yang mengaktifkan
    enabled_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(institution_id, feature_id)
);
```

### 2. Klasterisasi Fitur Otonom oleh AI

Ketika AI menghasilkan alat/alur kerja baru (via Agen 3: Sintesis & Pengembang):

1. **Agen Evaluator** menganalisis:
   - **Kompleksitas** — jumlah langkah, kedalaman penalaran hukum
   - **Beban komputasi** — estimasi CUDA weight (waktu inferensi GPU)
   - **Domain hukum** — Pidum, Tipikor, Cyber, Narkotika, TPPU, dll

2. **AI secara otonom menetapkan:**
   - `feature_category` — mengelompokkan ke kategori domain yang sesuai
   - `ai_suggested_tier` — menyarankan tingkat akses berdasarkan kompleksitas:

| Kompleksitas | Beban CUDA | Saran Tier AI |
|-------------|-----------|--------------|
| Rendah (< 0.3) | Ringan | `free` |
| Sedang (0.3–0.7) | Moderat | `premium_l1` |
| Tinggi (> 0.7) | Berat (forensik, multi-UU) | `premium_l2` |

3. **Super Admin memvalidasi** — saran AI bersifat rekomendasi. Hanya Super Admin yang dapat menetapkan `admin_approved_tier` final.

### 3. Konsol Super Admin Global

Super Admin (`role = 'super_admin'`) memiliki otoritas tunggal untuk:

- **Override tier AI** — mengubah `required_tier` dari saran AI ke keputusan manual
- **Aktivasi/Deaktivasi fitur** — mengontrol `is_active` secara global
- **Pemetaan institusi-fitur** — menentukan kategori fitur mana yang dapat diakses oleh institusi dan tier mana
- **Manajemen pengguna lintas-institusi** — membuat Admin Instansi, menetapkan tier
- **Audit trail** — semua perubahan dicatat di `ai_audit_logs` (immutable)

### 4. Jaminan Isolasi Tenant

```
┌─────────────────────────────────────────────────────┐
│                  SUPER ADMIN                         │
│          (Satu-satunya otoritas global)              │
├──────────┬──────────────┬───────────────────────────┤
│  POLRI   │  Kejaksaan   │  Mahkamah Agung           │
│  ┌─────┐ │  ┌─────────┐ │  ┌──────┐                │
│  │Data │ │  │Data     │ │  │Data  │                │
│  │Kasus│ │  │Perkara  │ │  │Vonis │                │
│  │Alat │ │  │Alat     │ │  │Alat  │                │
│  └─────┘ │  └─────────┘ │  └──────┘                │
│ TERISOLASI│  TERISOLASI  │  TERISOLASI              │
└──────────┴──────────────┴───────────────────────────┘
```

Mekanisme isolasi:
- **Row-Level Security (RLS)** pada PostgreSQL — setiap query difilter berdasarkan `institution_id` dari token JWT pengguna
- **Middleware tenant** di FastAPI — menyuntikkan `tenant_context` ke setiap request
- **Tidak ada akses lintas-institusi** kecuali diotorisasi eksplisit oleh Super Admin via tabel `institution_features`

### 5. Pemisahan Pengetahuan GLOBAL vs Data Operasional TENANT

**ATURAN KETAT:** Isolasi `institution_id` **HANYA** berlaku untuk data operasional. Pengetahuan hukum bersifat **GLOBAL** dan dibagikan ke semua institusi.

| Lapisan Data | Scope | Aturan |
|--------------|-------|--------|
| ChromaDB `indonesian_laws` (KUHP, KUHAP, UU ITE, dll. hasil ALCD) | **GLOBAL** | Satu namespace bersama — **DILARANG** diduplikasi per institusi. Tidak ada filter `institution_id` pada query RAG hukum |
| Neo4j `LegalArticle` + relasi `CROSS_REFERENCES`/`CONTRADICTS`/`SUPERSEDES` | **GLOBAL** | Graph hukum positif dibagikan lintas institusi |
| Neo4j `CrimeTrend` (tren dari sumber publik) | **GLOBAL** | Intelijen publik dibagikan; tautan ke kasus tetap per-tenant |
| PostgreSQL `knowledge_registry`, `ontology_nodes`, `self_eval_logs` | **GLOBAL** | Registri pengetahuan ALCD — satu untuk seluruh platform |
| PostgreSQL `cases`, `ai_audit_logs` (investigative logs) | **TENANT** | Wajib `institution_id` — terisolasi via RLS |
| Skrip AI kustom (`generated code` per kasus/tenant) | **TENANT** | Disimpan dengan `institution_id`; tidak terlihat lintas institusi |
| PostgreSQL `users`, sesi pengguna | **TENANT** | `institution_id` wajib; sesi terikat institusi |
| Neo4j `Suspect`, `BankAccount`, `IPAddress`, `PhoneNumber` | **TENANT** | Node entitas kasus wajib properti `institution_id` |

Justifikasi: hukum positif Indonesia identik untuk semua institusi — menduplikasikannya per tenant membuang VRAM/storage dan membuka risiko inkonsistensi basis pengetahuan.

### 6. Pembatasan Token & Keadilan Komputasi per Tier (SaaS Token Tiering)

Backend FastAPI **WAJIB** menegakkan batas token konteks berdasarkan `tier_level` pengguna untuk mencegah monopoli komputasi pada GPU terbatas:

| `tier_level` | Batas `num_ctx` per query | `num_predict` maks | Keterangan |
|--------------|---------------------------|--------------------|-----------|
| `free` | **2.048 token** | 512 | Capped keras — mencegah pemborosan GPU |
| `premium_l1` | **8.192 token** | 2.048 | Context window penuh untuk analisis kompleks |
| `premium_l2` | **16.384 token** | 4.096 | Maksimum absolut — forensik multi-UU |

Aturan penegakan:
- **Middleware token-budget** di FastAPI membaca `tier_level` dari `tenant_context` dan mengklamp `num_ctx`/`num_predict` **sebelum** request mencapai LangGraph
- Batas tier adalah **permintaan maksimum** — nilai efektif = `min(tier_cap, hardware_ceiling)` dari tabel VRAM HIRO §4 (contoh: `premium_l2` pada GPU 4 GB tetap diklamp hardware ke batas aman)
- Kelebihan batas → HTTP `429` dengan pesan tier upgrade, bukan error fatal
- Semua keputusan klamp dicatat di `ai_audit_logs.metadata` untuk audit keadilan komputasi

---

## 🌐 PAGAR PENGAMAN: KOMPATIBILITAS LINTAS-PLATFORM (Windows + Linux + macOS)

Seluruh kode, konfigurasi, dan skrip ALA **WAJIB** kompatibel lintas-platform. Tidak ada kode yang boleh dikunci ke satu sistem operasi.

### 1. Resolusi Jaringan Docker & Host

| Sistem Operasi | `host.docker.internal` | Aksi yang Diperlukan |
|----------------|------------------------|---------------------|
| **Windows** (Docker Desktop) | Tersedia secara native | Tidak perlu konfigurasi tambahan |
| **macOS** (Docker Desktop) | Tersedia secara native | Tidak perlu konfigurasi tambahan |
| **Linux** | **TIDAK** tersedia secara default | Wajib: `extra_hosts: ["host.docker.internal:host-gateway"]` |

Konfigurasi di `docker-compose.yml`:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"  # Wajib untuk Linux, aman di semua OS
```

Konfigurasi di `backend/app/config.py`:
```python
# Default ke host.docker.internal, dapat di-override via .env
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
```

### 2. Operasi File Agnostik-OS

**WAJIB** menggunakan `pathlib.Path` atau `os.path.join` untuk semua operasi file. **DILARANG KERAS** hardcode slash.

```python
# ✅ BENAR — portabel di semua OS
from pathlib import Path
tmp_dir = Path("/tmp") / "ala_sandbox"
config_file = Path.home() / ".ala" / "config.json"

# ❌ SALAH — terkunci ke satu OS
tmp_dir = "/tmp/ala_sandbox"          # Hanya Linux
tmp_dir = "C:\\tmp\\ala_sandbox"      # Hanya Windows
```

### 3. Volume Docker & Manajemen Izin

**WAJIB** menggunakan **named volumes** (BUKAN bind-mount host) untuk semua database:

```yaml
volumes:
  postgres_data:     # ✅ Named volume — portabel, aman izin
    name: ala_postgres_data
  chroma_data:
    name: ala_chroma_data
  neo4j_data:
    name: ala_neo4j_data
```

**DILARANG:**
```yaml
volumes:
  - ./data/postgres:/var/lib/postgresql/data  # ❌ Bug EACCES di Windows WSL2
  - ./data/neo4j:/data                         # ❌ Bug Permission Denied di rootless Docker
```

### 4. Skrip Otomasi Lintas-Platform

Jika membuat skrip setup atau pengujian, **WAJIB** sediakan kedua versi:
- `scripts/setup.sh` — untuk Linux / macOS
- `scripts/setup.ps1` — untuk Windows PowerShell

### 5. Deteksi RAM Lintas-Platform (HIRO)

Implementasi di `backend/app/config.py` — fungsi `_detect_ram()`:
- **Linux:** Membaca `/proc/meminfo` via `pathlib.Path`
- **Windows:** Menggunakan `ctypes.windll.kernel32.GlobalMemoryStatusEx`
- **macOS / fallback:** Menggunakan `shutil.disk_usage("/")`

---

## 🚀 LANGKAH EKSEKUSI MEGA-PLAN DEVIN

### [FASE 1: LINGKUNGAN & KERANGKA DASAR]
- [x] Buat semua direktori dan file placeholder.
- [x] Tulis docker-compose.yml yang menghubungkan semua layanan dengan jaringan terisolasi dan volume persisten bernama.
- [x] Tulis requirements.txt dengan semua dependensi Python.
- [x] Bangun dan jalankan lingkungan Docker. Verifikasi semua healthcheck lulus.
- [x] Konfigurasi `extra_hosts: ["host.docker.internal:host-gateway"]` untuk akses Ollama dari Docker.
- [x] Verifikasi Ollama berjalan di host dengan model `qwen2.5:3b-instruct` dan `qwen2.5-coder:3b`.
- [x] Implementasi Hardware Intelligence & Resource Optimizer (HIRO) di `backend/app/config.py`.
- [x] Implementasi model SQLAlchemy multi-tenant (institutions, users, feature_categories, features).
- [x] Implementasi middleware isolasi tenant dan endpoint placeholder Super Admin.
- [x] Penegakan kompatibilitas lintas-platform: deteksi RAM portabel, pathlib, named volumes, skrip setup dual-OS.
- [x] Konfigurasi dual-instance Ollama dengan GPU pinning: `CUDA_VISIBLE_DEVICES=0` + port `11434` untuk `qwen2.5:3b-instruct`, `CUDA_VISIBLE_DEVICES=1` + port `11435` untuk `qwen2.5-coder:3b` (anti-OOM).

### [FASE 2: DATABASE INTI & ANTARMUKA AGEN DATABASE]
- [x] Siapkan koneksi PostgreSQL dengan Audit Log Immutable + migrasi skema multi-tenant (kolom `institution_id` pada `cases`, `ai_audit_logs`, sesi pengguna).
- [x] Aktifkan Row-Level Security (RLS) pada PostgreSQL — HANYA untuk data operasional tenant (cases, investigative logs, custom AI scripts, user sessions).
- [x] Siapkan koleksi ChromaDB `indonesian_laws` sebagai namespace **GLOBAL** bersama (TANPA `institution_id`) untuk seluruh hukum positif hasil ALCD — tidak diduplikasi per institusi.
- [x] Siapkan driver Neo4j: graph `LegalArticle` + `CrimeTrend` **GLOBAL**; node entitas kasus (`Suspect`, `BankAccount`, `IPAddress`, `PhoneNumber`) wajib properti `institution_id`.
- [x] Implementasi middleware token-tiering di FastAPI: `free` = 2.048 ctx tokens, `premium_l1` = 8.192, `premium_l2` = 16.384 — selalu diklamp oleh ceiling hardware HIRO.
- [x] Tambahkan kolom chain-of-custody `evidence_sha256_before` / `evidence_sha256_after` pada `ai_audit_logs`.

### [FASE 3: MESIN AGEN OTONOM (LANGGRAPH)]
- [x] Implementasi curriculum_designer.py — menggunakan `llm_reasoning` (qwen2.5:3b-instruct) via Ollama lokal
- [x] Implementasi internet_crawler.py menggunakan Playwright — menggunakan `llm_reasoning` untuk analisis
- [x] Implementasi evaluator.py untuk evaluasi diri — menggunakan `llm_reasoning` untuk LLM-sebagai-juri
- [x] Implementasi code_generator.py — menggunakan `llm_coder` (qwen2.5-coder:3b) via Ollama lokal
- [x] Implementasi klasterisasi fitur otonom di Evaluator Agent (kategori + saran tier)
- [x] Suntikkan chain-of-custody guardrail di `code_generator.py`: semua skrip yang menyentuh file bukti WAJIB read-only + log SHA-256 sebelum & sesudah pemrosesan
- [x] Semua panggilan LLM melalui `ChatOllama` → reasoning ke Ollama `:11434` (GPU 0), coder ke Ollama `:11435` (GPU 1)

### [FASE 4: SANDBOX & PEMBUATAN KODE]
- [x] Amankan execution_env.py untuk pengujian kode dalam mikro-kontainer.
- [x] Verifikasi chain-of-custody di sandbox: file bukti di-mount `:ro` (read-only); checksum SHA-256 before/after dicatat ke `ai_audit_logs`.

### [FASE 5: INTEGRASI DASHBOARD FRONT-END]
- [x] Bangun UI Next.js dengan tampilan ontologi, log pembelajaran mandiri, dan validasi manusia-dalam-lingkaran.
- [x] Bangun Konsol Super Admin: manajemen institusi, pengguna, fitur, dan tier.
- [x] Implementasi tampilan per-tenant: dashboard khusus per institusi.

---

## 🛡️ PAGAR PENGAMAN INTI
1. **Tanpa Asumsi:** Sistem harus mengambil data secara native dari internet.
2. **Keselamatan Prosedural:** Jangan pernah melewati KUHAP.
3. **Tanpa Penimpaan:** Jangan sentuh framework agen inti secara dinamis di dalam sandbox.
4. **Lokal-Utama:** Semua inferensi LLM berjalan di Ollama lokal. Tidak ada panggilan API cloud untuk LLM. Akses internet HANYA untuk crawling dokumen hukum.
5. **Isolasi Tenant:** Data operasional antar-institusi TIDAK PERNAH bocor tanpa otorisasi eksplisit Super Admin.
6. **Lintas-Platform:** Semua kode, konfigurasi, dan skrip WAJIB berjalan di Windows, Linux, dan macOS tanpa modifikasi. Gunakan `pathlib.Path`, named volumes, dan skrip dual-OS.
7. **Chain of Custody (KUHAP):** Setiap skrip AI yang mem-parse/mengekstrak/menganalisis file bukti WAJIB membukanya read-only dan mencatat checksum SHA-256 sebelum & sesudah pemrosesan.
8. **Pengetahuan Hukum Global:** Koleksi ChromaDB `indonesian_laws` dan graph `LegalArticle` Neo4j adalah namespace GLOBAL bersama — TIDAK PERNAH diduplikasi per institusi.
9. **Keadilan Komputasi (Token Tiering):** Batas konteks per query ditegakkan per `tier_level` — `free` = 2.048 token, `premium_l1` = 8.192, `premium_l2` = 16.384 (diklamp oleh kapabilitas hardware).
10. **GPU Pinning:** `qwen2.5:3b-instruct` terkunci ke GPU 0, `qwen2.5-coder:3b` terkunci ke GPU 1 — dilarang berbagi GPU untuk mencegah OOM.
