# 🚀 Panduan Deployment — Autonomous Legal Agent (ALA)

> Dokumen ini menjelaskan langkah-langkah deployment ALA dari development hingga production environment.

---

## 1. Persyaratan Sistem

### 1.1 Hardware (Minimum)

| Komponen | Development | Production |
|----------|-------------|------------|
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8 GB | 16+ GB |
| **Storage** | 50 GB SSD | 200+ GB SSD |
| **Network** | Broadband | Dedicated line |

### 1.2 Software

| Software | Versi Minimum | Deskripsi |
|----------|---------------|-----------|
| **OS** | Ubuntu 22.04 LTS / RHEL 9 | Server operating system |
| **Docker** | 24.0+ | Container runtime |
| **Docker Compose** | 2.20+ | Container orchestration |
| **Python** | 3.11+ | Runtime untuk aplikasi |
| **Git** | 2.40+ | Version control |

---

## 2. Deployment Architecture

### 2.1 Development (Single Machine)

```
┌──────────────────────────────────┐
│         Development Host         │
│                                  │
│  ┌────────────────────────────┐  │
│  │     Docker Compose         │  │
│  │                            │  │
│  │  [FastAPI]  [PostgreSQL]   │  │
│  │  [ChromaDB] [Neo4j]       │  │
│  │  [Sandbox]                 │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

### 2.2 Production (On-Premise)

```
┌──────────────────────────────────────────┐
│              Reverse Proxy               │
│         (Nginx / Traefik + TLS)          │
└─────────┬────────────────────────┘
                  │ HTTPS :443
┌─────────────────▼────────────────────────┐
│            Application Server            │
│                                          │
│  ┌──────────────┐  ┌─────────────────┐   │
│  │  FastAPI     │  │  Next.js        │   │
│  │  (Python)    │  │  (TypeScript)   │   │
│  │  :8000       │  │  :3000          │   │
│  └──────┬───────┘  └─────────────────┘   │
│  ┌──────────────┐                          │
│  │  Sandbox     │  (network_mode: none)   │
│  └──────────────┘                          │
└─────────┼────────────────────────────┘────┘
          │
┌─────────▼────────────────────────────────┐
│            Database Server               │
│                                          │
│  ┌──────────┐ ┌────────┐ ┌───────────┐  │
│  │PostgreSQL│ │ChromaDB│ │   Neo4j   │  │
│  └──────────┘ └────────┘ └───────────┘  │
└──────────────────────────────────────────┘
```

### 2.3 Native systemd (deployment aktual saat ini)

Lingkungan dev/produksi saat ini berjalan sebagai **systemd user units**
(native, tanpa container untuk service data):

| Unit | Port | Data |
|------|------|------|
| `ala-postgres.service` | `5432` | `.pgdata/` |
| `ala-chroma.service` | `8001` | `.chroma/` |
| `ala-neo4j.service` | `7687` | `.neo4j/` |
| `ala-api.service` | `8080` | FastAPI (`main:app`) |
| `ala-frontend.service` | `3000` | Next.js dev server |

```bash
# Unit ada di ~/.config/systemd/user/ — ordering sudah diatur
systemctl --user status ala-api        # status + health
journalctl --user -u ala-api -f        # log live
systemctl --user restart ala-api       # restart
```

Env runtime tidak dibaca dari `.env` — konfigurasi nyata ada di
`backend/.env.runtime` (dimuat oleh unit/script via `set -a; .
.env.runtime`). `Settings` tetap kompatibel `.env` untuk Docker.

---

## 3. Deployment Steps

### 3.1 Persiapan Server

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Verify
docker --version
docker compose version
```

### 3.2 Clone & Configure

```bash
# Clone repository
git clone <repo-url> /opt/ala
cd /opt/ala

# Setup environment
cp .env.example .env
nano .env  # Edit semua secrets
```

### 3.3 Environment Variables

Buat file `.env` dengan konfigurasi berikut:

```bash
# === Database ===
# ala_user  = superuser bawaan image postgres — HANYA untuk init/migrasi
# ala_app   = role aplikasi non-superuser; RLS tenant hanya berlaku pada
#             role ini (superuser selalu bypass RLS!)
POSTGRES_PASSWORD=<GENERATE_STRONG_PASSWORD>
APP_DB_PASSWORD=<GENERATE_STRONG_PASSWORD>   # password role ala_app

# === Neo4j ===
NEO4J_PASSWORD=<GENERATE_STRONG_PASSWORD>

# === LLM Provider (Ollama Lokal — dual-instance GPU pinning) ===
# TIDAK ada API key cloud — semua inferensi berjalan lokal.
# Instance #1 (:11434, GPU 0) → penalaran; Instance #2 (:11435, GPU 1) → coder
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_REASONING_URL=http://host.docker.internal:11434
OLLAMA_CODER_URL=http://host.docker.internal:11435
OLLAMA_MODEL_REASONING=qwen2.5:3b-instruct
OLLAMA_MODEL_CODER=qwen2.5-coder:3b
OLLAMA_TEMPERATURE_REASONING=0.2
OLLAMA_TEMPERATURE_CODER=0.1

# === Google Custom Search (opsional — discovery dokumen publik ALCD) ===
GOOGLE_CSE_ID=<custom-search-engine-id>
GOOGLE_CSE_API_KEY=<your-key>

# === Security ===
JWT_SECRET=<GENERATE_STRONG_SECRET>
JWT_EXPIRY_HOURS=24
# Fallback header auth (X-User-Role dsb.) untuk dev standalone —
# WAJIB false di deployment nyata, atau siapa pun bisa mengaku super_admin
AUTH_DEV_HEADERS=false
# Password super_admin pertama (dipakai scripts/seed_admin.py; bila kosong
# password acak dicetak sekali ke stdout)
ALA_ADMIN_PASSWORD=<password-admin-pertama>

# === Application ===
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=info
DEBUG=false

# === ALCD (Autonomous Legal Curriculum Designer) ===
ALCD_ENABLED=true
ALCD_MIN_READINESS_SCORE=0.8
ALCD_SELF_EVAL_THRESHOLD=0.7
ALCD_SCHEDULE_INTERVAL=168h
ALCD_MAX_CONCURRENT_CRAWLS=3
ALCD_TRUSTED_DOMAINS=jdih.kemenkumham.go.id,peraturan.bpk.go.id,putusan3.mahkamahagung.go.id
ALCD_CRAWL_RATE_LIMIT=1

# === Embedding retrieval (opsional — default multilingual-e5-small) ===
# Jalur upgrade: LazarusNLP/all-indo-e5-small-v4 (384-dim, khusus
# Bahasa Indonesia — drop-in) lalu BGE-M3-ind. GANTI MODEL WAJIB
# kosongkan koleksi `indonesian_laws` dan re-embed ulang seluruh
# korpus (bootstrap ALCD) — mencampur vektor beda model merusak
# retrieval diam-diam.
EMBEDDING_MODEL=intfloat/multilingual-e5-small

# === Korpus HuggingFace (opsional) ===
# Cache parquet + batas impor bertahap.
HF_CORPUS_DIR=backend/data/hf
HF_IMPORT_MAX_LAWS=0        # 0 = semua 1.924 UU JDIH BPK
HF_PUTUSAN_MAX=2000         # ≤0 = nonaktifkan impor putusan MA

# === Reranker & indeks leksikal (lokal, zero-cost) ===
# Cross-encoder CPU-viable (~118MB, diunduh sekali dari HF). Upgrade ke
# BAAI/bge-reranker-v2-m3 bila torch CUDA tersedia. Skor hanya mengatur
# urutan kandidat — relevance_score tetap cosine dense.
RERANKER_ENABLED=true
RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RERANKER_TOP=48
# Snapshot BM25 — cold-start memuat disk, bukan rebuild korpus penuh.
BM25_INDEX_PATH=/home/<user>/.chroma/bm25_index.pkl
```

### 3.4 Dual-GPU Ollama (Host)

Platform menjalankan **2 instance Ollama** agar kedua model tidak berebut
VRAM pada GPU 4 GB yang sama (anti-OOM):

| Instance | Port | GPU | Model | Konsumen |
|----------|------|-----|-------|----------|
| `ollama.service` | `11434` | GPU 0 (`CUDA_VISIBLE_DEVICES=0`) | `qwen2.5:3b-instruct` | Agen 0–2 (penalaran) |
| `ollama-coder.service` | `11435` | GPU 1 (`CUDA_VISIBLE_DEVICES=1`) | `qwen2.5-coder:3b` | Agen 3 (generate kode) |

```bash
# Setup otomatis (membuat override + unit kedua, daemon-reload, start)
sudo ./scripts/setup_dual_ollama.sh

# Verifikasi kedua endpoint
curl http://127.0.0.1:11434/api/tags   # GPU 0 — qwen2.5:3b-instruct
curl http://127.0.0.1:11435/api/tags   # GPU 1 — qwen2.5-coder:3b

# Pastikan model coder tersedia di instance :11435
# (pull di instance utama saja — dir model dibagikan)
ollama pull qwen2.5-coder:3b
```

> **Catatan:** kedua instance berbagi `OLLAMA_MODELS=/usr/share/ollama/.ollama/models`
> (blobs read-only). Lakukan `ollama pull` hanya via instance utama `:11434`.
> `OLLAMA_MAX_LOADED_MODELS=1` + `OLLAMA_NUM_PARALLEL=1` di kedua unit
> mencegah lebih dari satu model termuat per GPU 4 GB.

### 3.5 Build & Start

```bash
# Build semua images
docker compose build

# Build image sandbox eksekusi (WAJIB — dipakai /approve-workflow;
# sudah berisi pandas/openpyxl/bs4/pdfplumber dll sesuai whitelist
# guardrails; tetap jalan tanpa jaringan + read-only + non-root)
docker build -t ala-sandbox:latest ./sandbox

# Start semua services
docker compose up -d

# Cek status
docker compose ps

# View logs
docker compose logs -f
```

### 3.6 Inisialisasi Database

```bash
# Jalankan di dalam container api (working dir /app = ./backend)
# Hanya membuat tabel kosong — TIDAK ada data yang di-load.
# Memakai DATABASE_ADMIN_URL (ala_user) untuk DDL + membuat role
# aplikasi `ala_app` (non-superuser) beserta GRANT + RLS + REVOKE.
docker compose exec api python scripts/init_db.py

# Akun super_admin pertama (bila tabel users kosong). Password dari
# ALA_ADMIN_PASSWORD, atau acak dicetak sekali ke stdout.
docker compose exec api python scripts/seed_admin.py
```

> **PENTING — RLS & append-only audit:** aplikasi runtime terhubung via
> `DATABASE_URL` → role `ala_app` (non-superuser). Role inilah yang
> tunduk pada `tenant_isolation` RLS di `cases`/`ai_audit_logs` dan
> tidak bisa UPDATE/DELETE `ai_audit_logs`. Jangan pernah mengubah
> `DATABASE_URL` layanan api ke `ala_user` — superuser selalu melewati
> RLS dan audit-immutability.

> **NOTE:** Tidak ada script `ingest_laws.py` atau `seed_graph.py`. Semua data hukum ditemukan dan di-ingest secara **otonom** oleh modul ALCD saat sistem pertama kali dijalankan. ChromaDB dan Neo4j dimulai kosong dan dipopulasi otomatis.

### 3.6b Setup di Mesin Lain (Reproducible Dev)

Agar development di komputer lain menghasilkan aplikasi yang identik:

```bash
# 1. Clone
git clone git@github.com:82080038/ALA.git && cd ALA

# 2. Environment — .env TIDAK ikut repo (rahasia); buat dari template
cp .env.example .env   # isi password sesuai mesin itu

# 3. Dual-Ollama + model (host, perlu sudo)
sudo ./scripts/setup_dual_ollama.sh
ollama pull qwen2.5:3b-instruct && ollama pull qwen2.5-coder:3b

# 4. Build & jalankan (lockfile menjamin versi identik)
docker compose build
docker build -t ala-sandbox:latest ./sandbox
docker compose up -d
docker compose exec api python scripts/init_db.py
docker compose exec api python scripts/seed_admin.py
```

Determinisme versi: `frontend/package-lock.json` (`npm ci`) +
`backend/requirements.lock` (pip freeze dari image terverifikasi —
`pip install -r requirements.lock` untuk pin penuh).

**Membawa data yang sama persis** (opsional — ALCD dapat bootstrap ulang
sendiri ±7 menit pada query pertama):

```bash
# Mesin lama
./scripts/backup_volumes.sh              # → ala-data-backup-*.tar.gz
# Salin file ke mesin baru (scp/usb)
# Mesin baru — sebelum `docker compose up` pertama
./scripts/restore_volumes.sh ala-data-backup-*.tar.gz
docker compose up -d
```

Isi backup: skema+data Postgres (ontologi, `knowledge_registry`,
kasus, audit), koleksi ChromaDB `indonesian_laws`, graph Neo4j
`LegalArticle`/`CROSS_REFERENCES`.

### 3.7 Verifikasi

```bash
# Health check (port host 8080 → container 8000)
curl http://localhost:8080/health

# Expected response (ringkas):
# {"status":"healthy","service":"ala-api","version":"0.3.0",
#  "llm_provider":"ollama (lokal)","ollama_status":"connected",
#  "ollama_models":["qwen2.5:3b-instruct","qwen2.5-coder:3b"],"hardware":{...}}
```

---

## 4. Docker Compose (Production)

```yaml
services:
  # === Application ===
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "${APP_PORT:-8080}:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      chromadb:
        condition: service_started
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # === PostgreSQL ===
  postgres:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # === Neo4j ===
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    environment:
      NEO4J_AUTH: ${NEO4J_USER}/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_memory_heap_max__size: "1G"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5

  # === ChromaDB ===
  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma
    restart: unless-stopped

  # === Sandbox (On-Demand) ===
  # Sandbox containers dibuat secara dinamis oleh executor.py
  # Lihat SECURITY.md untuk konfigurasi isolasi

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  chroma_data:
```

---

## 5. Reverse Proxy (Nginx)

Untuk production, gunakan Nginx sebagai reverse proxy dengan TLS:

```nginx
server {
    listen 443 ssl http2;
    server_name ala.internal.domain;

    ssl_certificate     /etc/nginx/ssl/ala.crt;
    ssl_certificate_key /etc/nginx/ssl/ala.key;
    ssl_protocols       TLSv1.3;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (jika diperlukan)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://localhost:8080;
    }
}

server {
    listen 80;
    server_name ala.internal.domain;
    return 301 https://$host$request_uri;
}
```

---

## 6. Backup & Recovery

### 6.1 PostgreSQL Backup

```bash
# Manual backup
docker compose exec postgres pg_dump -U ala_user ala_db > backup_$(date +%Y%m%d).sql

# Automated daily backup (cron)
# 0 2 * * * /opt/ala/scripts/backup_postgres.sh
```

### 6.2 Neo4j Backup

```bash
# Stop Neo4j, backup data volume
docker compose stop neo4j
tar -czf neo4j_backup_$(date +%Y%m%d).tar.gz /var/lib/docker/volumes/ala_neo4j_data
docker compose start neo4j
```

### 6.3 ChromaDB Backup

```bash
# Backup ChromaDB data volume
tar -czf chroma_backup_$(date +%Y%m%d).tar.gz /var/lib/docker/volumes/ala_chroma_data
```

### 6.4 Recovery

```bash
# Restore PostgreSQL
cat backup_20261007.sql | docker compose exec -T postgres psql -U ala_user ala_db

# Restore Neo4j
docker compose stop neo4j
tar -xzf neo4j_backup_20261007.tar.gz -C /
docker compose start neo4j
```

---

## 7. Monitoring

### 7.1 Health Checks

Semua services memiliki health check di Docker Compose. Status dapat dicek dengan:

```bash
docker compose ps
```

### 7.2 Logs

```bash
# Semua logs
docker compose logs -f

# Log spesifik service
docker compose logs -f api
docker compose logs -f postgres
docker compose logs -f neo4j

# Log dengan filter waktu
docker compose logs --since "2026-10-07T14:00:00" api
```

### 7.3 Metrics (Opsional)

Untuk monitoring lebih lanjut, pertimbangkan integrasi:
- **Prometheus** — Metrics collection
- **Grafana** — Dashboard visualization
- **Loki** — Log aggregation

---

## 8. Scaling

### 8.1 Horizontal Scaling (API)

Untuk meningkatkan throughput API, jalankan Uvicorn dengan beberapa worker:

```bash
# Ubah CMD di backend/Dockerfile (tanpa --reload) atau override via compose:
docker compose up -d api \
  --scale api=1  # ganti CMD: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 8
```

### 8.2 Database Scaling

| Database | Strategy |
|----------|----------|
| **PostgreSQL** | Read replicas untuk query-heavy workloads |
| **ChromaDB** | Increase memory allocation, SSD storage |
| **Neo4j** | Increase heap memory, add indexes |

---

## 9. Troubleshooting

| Masalah | Solusi |
|---------|--------|
| Container tidak start | `docker compose logs <service>` untuk melihat error |
| PostgreSQL connection refused | Cek `POSTGRES_PASSWORD` di `.env`, pastikan port tidak konflik |
| Neo4j authentication failed | Reset password: hapus volume, recreate |
| ChromaDB out of memory | Tingkatkan memory limit di `docker-compose.yml` |
| API timeout pada analyze-trend | Cek koneksi LLM provider, timeout settings |
| ALCD bootstrap terlalu lama | Kurangi `ALCD_MIN_READINESS_SCORE`, cek rate limiting, pastikan Google Search API key valid |
| Knowledge score tidak naik | Cek `self_eval_logs` untuk gap details, pastikan ALCD trusted domains accessible |
| Sandbox execution failed | Cek Docker socket permissions, image build status |

---

## 10. Checklist Deployment

### Development
- [ ] Docker & Docker Compose terinstall
- [ ] `.env` file dikonfigurasi
- [ ] `docker compose up -d` berhasil
- [ ] Health check endpoint merespon OK
- [ ] Database initialization scripts berjalan

### Production
- [ ] Server memenuhi spesifikasi minimum
- [ ] TLS certificate terpasang
- [ ] Nginx reverse proxy dikonfigurasi
- [ ] Firewall hanya membuka port 443
- [ ] Strong passwords di semua services
- [ ] Backup automation terkonfigurasi
- [ ] Monitoring aktif
- [ ] `.env` tidak dalam repository
- [ ] Health checks berjalan untuk semua services
- [ ] Smoke test end-to-end berhasil
