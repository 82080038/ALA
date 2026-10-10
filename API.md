# 📡 Dokumentasi API — Autonomous Legal Agent (ALA)

> Dokumen ini menjelaskan seluruh REST API endpoints yang disediakan oleh backend FastAPI ALA.

---

## Base URL

```
http://localhost:8080        # port host (container: 8000)
```

Semua endpoint bisnis berada di bawah prefix **`/api/v1`** (contoh: `POST /api/v1/analyze-trend`).
Endpoint `/health` tidak menggunakan prefix.

> **Status implementasi:** Fase 1 menyediakan `/api/v1/status`, `/api/v1/alcd/status`, dan `/api/v1/admin/*`. Endpoint sisanya adalah spesifikasi target untuk Fase 2+.

---

## Autentikasi

Semua endpoint (kecuali `/health`) memerlukan autentikasi via **Bearer Token** di header:

```
Authorization: Bearer <token>
```

Token diperoleh melalui `POST /api/v1/auth/login` (JWT HS256 lokal — tanpa layanan eksternal). RBAC diterapkan berdasarkan role user: `super_admin`, `admin_instansi`, `penyidik`, `jaksa`, `hakim` (lihat `SECURITY.md` §2.2 untuk permission matrix lengkap).

> **Fallback dev:** middleware juga membaca header `X-Institution-ID`, `X-User-ID`, `X-User-Role`, `X-Tier-Level` **hanya bila `AUTH_DEV_HEADERS=true`** (default aktif untuk standalone lokal; wajib `false` di deployment nyata). Token Bearer selalu diutamakan bila dikirim.

---

### 0. Login — Terbitkan JWT

```
POST /api/v1/auth/login
```

**Body:**
```json
{ "email": "admin@ala.local", "password": "..." }
```

**Response `200`:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in_hours": 24,
  "user": { "id": "…", "name": "Super Admin", "role": "super_admin",
            "tier": "premium_l2", "institution_id": "…" }
}
```

**Error:** `401` email/password salah (pesan generik — tidak membocorkan akun terdaftar). Rate-limited 10/menit/IP.

Akun pertama dibuat via `scripts/seed_admin.py` (idempotent, password acak dicetak sekali atau dari `ALA_ADMIN_PASSWORD`). Pengguna selanjutnya via `POST /api/v1/admin/users` (super_admin).

### 0a. Audit Chain Verification

```
GET /api/v1/audit-logs/verify    (super_admin)
```

**Response:** `{ "valid": true, "entries_checked": 12, "broken_at": null }` — memverifikasi hash-chain `prev_hash`/`entry_hash` di `ai_audit_logs`; `broken_at` menunjuk baris yang dimanipulasi.

---

## Endpoints

### 1. Health Check

```
GET /health
```

**Deskripsi:** Cek status kesehatan API dan koneksi database.

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "postgres": "connected",
  "chromadb": "connected",
  "neo4j": "connected",
  "alcd": {
    "knowledge_ready": true,
    "knowledge_score": 0.87,
    "laws_ingested": 21,
    "last_evaluation": "2026-10-07T02:00:00Z"
  },
  "timestamp": "2026-10-07T14:00:00Z"
}
```

---

### 2. Analisis Tren Kejahatan (async job)

```
POST /api/v1/analyze-trend
```

**Deskripsi:** Mengantrekan pipeline LangGraph **law-first** sebagai job background. Mengembalikan `request_id` seketika — progres tiap agen dipantau via `GET /api/v1/analyze-trend/{request_id}` atau `GET /api/v1/activity`. `X-Institution-ID` wajib dan harus institusi terdaftar (baris audit butuh tenant valid).

**Request Body:**
```json
{
  "query": "modus pencucian uang melalui cryptocurrency",
  "case_id": null,
  "mode": "full"
}
```

| Field | Type | Required | Default | Deskripsi |
|-------|------|----------|---------|-----------|
| `query` | `string` | ✅ | — | Query analisis dalam Bahasa Indonesia (3–4000 char) |
| `case_id` | `string (uuid)` | ❌ | `null` | Kaitkan hasil ke kasus tertentu (divalidasi: 400 UUID rusak, 404 kasus tidak ada/milik tenant lain) |
| `mode` | `string` | ❌ | `"full"` | `full` = 4 agen (crawler + codegen); `legal` = hanya retrieval pasal (cepat) |

**Response `202 Accepted`:**
```json
{
  "request_id": "uuid-v4",
  "status": "queued"
}
```

**Error:** `400` jika `X-Institution-ID` kosong / bukan institusi terdaftar; `401` tanpa `X-User-Role`.

### 2a. Status Job Pipeline

```
GET /api/v1/analyze-trend/{request_id}
```

**Response `200` (berjalan):**
```json
{
  "request_id": "uuid-v4",
  "kind": "analyze",
  "query": "modus pencucian uang...",
  "status": "running",
  "stages_completed": ["alcd", "legal_foundation"],
  "pipeline_stages": ["alcd", "legal_foundation", "internet_crawler", "synthesis_developer"],
  "stage_labels": {"alcd": "Agent 0 — ALCD: ...", "...": "..."},
  "started_at": 1759999999.0,
  "finished_at": null,
  "error": null
}
```

**Response `200` (selesai)** — sama, plus `status: "done"` dan field `result`:
```json
{
  "result": {
    "request_id": "uuid-v4",
    "knowledge_ready": true,
    "knowledge_score": 0.97,
    "legal_summary": "...",
    "legal_articles": [{"law_name": "UU TPPU", "article_number": "Pasal 3", "relevance_score": 0.96,
      "elements": {"pelaku": "Setiap Orang", "sikap_batin": [], "ancaman": {"penjara": {"maks": 20.0}}}],
    "cross_references": [{"from_article": "...", "to_article": "...", "relationship": "CROSS_REFERENCES"}],
    "crime_summary": "...",
    "crime_data": [{"title": "...", "url": "...", "snippet": "..."}],
    "synthesis": {"gaps": ["..."], "strategy": "..."},
    "generated_output": {"filename": "utility.py", "code": "...", "flowchart": "...", "syntax_valid": true},
    "errors": [],
    "requires_approval": true
  }
}
```

`status: "failed"` disertai `error`. Job tenant lain → `404` (tidak bisa di-probe). Registry in-memory — hasil job yang hilang saat restart API **dipulihkan dari `ai_audit_logs`** (`recovered_from_audit: true`, tetap RLS-scoped).

Field opsional `legal_articles[]`: `elements` (skema unsur delik — `pelaku`/`perbuatan`/`sikap_batin`/`ancaman`, hanya pasal pidana) dan `kaidah` (ratio/amar terstruktur, hanya seksi putusan MA).

### 2b. Aktivitas Real-Time

```
GET /api/v1/activity
```

**Deskripsi:** Daftar job tenant ini (super_admin: semua tenant) — yang sedang berjalan dulu, lalu riwayat terbaru (maks 20).

---

### 2c. Daftar Institusi (untuk pemilih identitas)

```
GET /api/v1/institutions
```

**Response `200`:**
```json
{"institutions": [{"id": "uuid", "name": "POLRI", "type": "kepolisian"}]}
```

---

### 3. Approval Workflow

```
POST /api/v1/approve-workflow
```

**Deskripsi:** Mencatat keputusan APH (human-in-the-loop). `approved=true` → kode hasil generate di-scan ulang guardrail lalu dieksekusi di sandbox Docker terkunci; `approved=false` → ditolak. Keputusan dicatat dalam audit log hash-chained. **Satu request hanya boleh diputuskan sekali** — approve ganda atau approve-setelah-reject ditolak `409`.

**Request Body:**
```json
{
  "request_id": "uuid-v4",
  "approved": true,
  "approved_by": "APH-2024-001"
}
```

| Field | Type | Required | Deskripsi |
|-------|------|----------|-----------|
| `request_id` | `string (uuid)` | ✅ | ID request dari `/api/v1/analyze-trend` |
| `approved` | `boolean` | ✅ | `true` = eksekusi sandbox; `false` = tolak |
| `approved_by` | `string` | ❌ | Identitas approver (dicatat di metadata audit) |

**Response `200 OK` (approve):**
```json
{
  "request_id": "uuid-v4",
  "status": "executed",
  "exit_code": 0,
  "timed_out": false,
  "guardrail_violations": [],
  "stdout": "...",
  "stderr": ""
}
```

**Response `200 OK` (reject):**
```json
{ "request_id": "uuid-v4", "status": "rejected" }
```

**Error:** `400` request_id bukan UUID / tidak ada kode · `404` request tidak ditemukan (termasuk milik tenant lain — RLS) · `409` request sudah diputuskan (`execute`/`reject`)

---

### 4. Daftar Kasus

```
GET /api/v1/cases
```

**Deskripsi:** Mengambil daftar kasus yang terdaftar dalam sistem.

**Query Parameters:**

| Parameter | Type | Default | Deskripsi |
|-----------|------|---------|-----------|
| `status` | `string` | `all` | Filter: `open`, `closed`, `in_progress`, `all` |
| `page` | `integer` | `1` | Halaman paginasi |
| `per_page` | `integer` | `20` | Jumlah item per halaman |

**Response `200 OK`:**
```json
{
  "total": 42,
  "page": 1,
  "per_page": 20,
  "cases": [
    {
      "id": "uuid-v4",
      "title": "Kasus TPPU via Cryptocurrency",
      "description": "Penyelidikan pencucian uang hasil korupsi melalui aset kripto...",
      "status": "in_progress",
      "created_at": "2026-09-01T10:00:00Z",
      "updated_at": "2026-10-05T15:30:00Z"
    }
  ]
}
```

---

### 5. Detail Kasus

```
GET /api/v1/cases/{case_id}
```

**Response `200 OK`:**
```json
{
  "id": "uuid-v4",
  "title": "Kasus TPPU via Cryptocurrency",
  "description": "...",
  "status": "open",
  "case_number": "LP-2024-001",
  "crime_type": "pencucian_uang",
  "priority": "high",
  "assigned_to": {
    "name": "Budi Santoso",
    "badge_number": "APH-2024-001",
    "role": "penyidik"
  },
  "analysis_history": [
    {
      "audit_id": "uuid-v4",
      "request_id": "uuid-v4",
      "query": "metode phishing APK terbaru",
      "timestamp": "2026-10-05T15:30:00Z"
    }
  ],
  "created_at": "2026-09-01T10:00:00Z",
  "updated_at": "2026-10-05T15:30:00Z"
}
```

**Error:** `404` ID bukan UUID / kasus tidak ada / milik tenant lain (RLS — indistinguishable by design).

---

### 6. Audit Logs

```
GET /api/v1/audit-logs
```

**Deskripsi:** Mengambil immutable audit log aktivitas AI milik tenant (super_admin: semua). Terbaru dulu.

**Query Parameters:**

| Parameter | Type | Default | Deskripsi |
|-----------|------|---------|-----------|
| `limit` | `integer` | `50` | Jumlah entri (maks 200) |

**Response `200 OK`:**
```json
{
  "logs": [
    {
      "id": "uuid-v4",
      "timestamp": "2026-10-07T14:05:00Z",
      "action": "analyze",
      "request_id": "uuid-v4",
      "query_input": "modus pencucian uang via crypto",
      "evidence_sha256_before": null,
      "evidence_sha256_after": null,
      "entry_hash": "a736f577…"
    }
  ]
}
```

Lihat juga `GET /api/v1/audit-logs/verify` (super_admin) — verifikasi integritas hash-chain → `{valid, entries_checked, broken_at}`.

---

### 7. Graph Query (Neo4j)

```
POST /api/v1/graph/query
```

**Deskripsi:** Menjalankan Cypher **baca-saja** terhadap graph Neo4j global. Keyword tulis (`CREATE`, `MERGE`, `DELETE`, `SET`, `DROP`, `CALL`, `LOAD`, `REMOVE`, `DETACH`) ditolak `400`; hasil dibatasi 500 record.

**Request Body:**
```json
{
  "cypher": "MATCH (a:LegalArticle)-[r]->(b:LegalArticle) WHERE a.article_number = $pasal RETURN a.law_name, type(r), b.law_name, b.article_number LIMIT 10",
  "parameters": {"pasal": "30"}
}
```

**Response `200 OK`:**
```json
{
  "records": [
    {
      "a.law_name": "UU ITE",
      "type(r)": "CROSS_REFERENCES",
      "b.law_name": "KUHP",
      "b.article_number": "310"
    }
  ]
}
```

---

### 8. ALCD — Knowledge Status

```
GET /api/v1/alcd/status
```

**Deskripsi:** Mengambil status terkini basis pengetahuan yang dibangun secara otonom oleh modul ALCD.

**Auth:** `super_admin`, `admin_instansi`, `penyidik`, `jaksa`, `hakim`

**Response `200 OK`:**
```json
{
  "knowledge_ready": true,
  "knowledge_score": 0.87,
  "total_laws_ingested": 21,
  "total_chunks": 4523,
  "total_graph_nodes": 892,
  "total_cross_references": 1567,
  "ontology_coverage": {
    "hukum_pidana_materiil": {"score": 0.92, "laws": 5, "status": "completed"},
    "hukum_pidana_formil": {"score": 0.88, "laws": 1, "status": "completed"},
    "regulasi_teknis": {"score": 0.79, "laws": 3, "status": "completed"},
    "yurisprudensi": {"score": 0.82, "laws": 12, "status": "completed"}
  },
  "last_bootstrap": "2026-10-01T00:00:00Z",
  "last_self_eval": "2026-10-07T02:00:00Z",
  "next_scheduled_eval": "2026-10-14T02:00:00Z",
  "pending_gaps": 2
}
```

---

### 9. ALCD — Trigger Learning (async job)

```
POST /api/v1/alcd/trigger
```

**Deskripsi:** Mengantrekan siklus pembelajaran ALCD (ontology → acquisition → self-evaluation) sebagai job background — proses bisa bermenit-menit. Pantau via `GET /api/v1/analyze-trend/{request_id}` atau `GET /api/v1/activity`.

**Auth:** role apapun yang terautentikasi (bukan anonymous)

**Request Body:** tidak ada

**Response `202 Accepted`:**
```json
{
  "request_id": "uuid-v4",
  "status": "queued"
}
```

**Error:** `409` jika bootstrap lain sedang berjalan (anti double-run).

---

### 9a. ALCD — Progress Live & Feed Pengetahuan

```
GET /api/v1/alcd/progress
```

**Deskripsi:** Progres real-time bootstrap ALCD — tahap yang sedang
dikerjakan beserta hitungan nyata, plus feed pengetahuan untuk panel
"ISI OTAK" frontend. Semua nilai berasal dari pipeline backend; tidak
ada data rekaan.

**Auth:** publik (namespace GLOBAL)

**Response `200 OK`:**
```json
{
  "stage": "import",
  "topic": "Korpus JDIH BPK (HF)",
  "detail": "20/2025 · 809 pasal",
  "running": true,
  "done": 3,
  "total": 47,
  "elapsed_s": 55,
  "eta_s": 810,
  "recent": [
    {"name": "UU Nomor 1 Tahun 2026 tentang KUHP", "articles": 85,
     "chunks": 246, "cat": "materiil", "ts": "2026-10-10T01:58:00Z"}
  ],
  "queue": [
    {"topic": "Doktrin & Asas Hukum", "status": "gap_detected",
     "score": 0.0}
  ]
}
```

| Field | Deskripsi |
|-------|-----------|
| `stage` | Tahap pipeline: `ontology`, `doktrin`, `acquire`, `scan`, `fetch`, `parse`, `ingest`, `graph`, `import`, `evaluate`, `done` |
| `topic` | Topik/wilayah ontologi atau korpus yang sedang diproses |
| `detail` | Detail kerja (nama file, dokumen, jumlah pasal) |
| `running` | `true` saat bootstrap aktif |
| `done`/`total` | Kemajuan bernilai — `null` bila belum bisa dihitung |
| `elapsed_s` | Detik berjalan pada tahap ini |
| `eta_s` | Estimasi sisa detik — `null` bila belum bisa diestimasi |
| `recent` | 5 dokumen terakhir yang berhasil ditanam (BARU DIPELAJARI) |
| `queue` | Node ontologi berikutnya (RENCANA BERIKUTNYA) |

---

### 10. ALCD — Ontology Tree

```
GET /api/v1/alcd/ontology
```

**Deskripsi:** Mengambil peta pengetahuan (knowledge tree) yang dihasilkan AI secara otonom.

**Auth:** `super_admin`, `admin_instansi`, `penyidik`, `jaksa`, `hakim`

**Response `200 OK`:**
```json
{
  "total_nodes": 14,
  "tree": [
    {
      "id": "uuid",
      "category": "Hukum Pidana Materiil",
      "priority": 1,
      "status": "completed",
      "knowledge_score": 0.92,
      "children": [
        {"id": "uuid", "subcategory": "KUHP", "status": "completed", "laws_ingested": 1},
        {"id": "uuid", "subcategory": "UU Tipikor", "status": "completed", "laws_ingested": 1},
        {"id": "uuid", "subcategory": "UU Narkotika", "status": "completed", "laws_ingested": 1}
      ]
    }
  ]
}
```

---

### 11. ALCD — Knowledge Gaps

```
GET /api/v1/alcd/gaps
```

**Deskripsi:** Mengambil daftar gap pengetahuan yang teridentifikasi oleh self-evaluation loop.

**Auth:** `super_admin`, `admin_instansi`, `penyidik`

**Query Parameters:**

| Parameter | Type | Default | Deskripsi |
|-----------|------|---------|----------|
| `resolved` | `boolean` | `false` | Filter: hanya gap yang belum/sudah resolved |
| `min_severity` | `float` | `0.0` | Gap severity minimum (0.0–1.0, where 1.0 = worst) |

**Response `200 OK`:**
```json
{
  "total_gaps": 2,
  "gaps": [
    {
      "id": "uuid",
      "ontology_node": "Regulasi Teknis / SOP Penyidikan",
      "question": "Apa prosedur hukum penyitaan aset digital menurut hukum Indonesia?",
      "answer_quality": 0.45,
      "gap_description": "Sistem belum memiliki pengetahuan tentang SOP penyitaan aset digital",
      "remediation_action": "Searching for SOP penyitaan aset digital on JDIH",
      "resolved": false,
      "detected_at": "2026-10-07T02:15:00Z"
    }
  ]
}
```

---

## Error Responses

Semua endpoint menggunakan format error standar:

| HTTP Status | Deskripsi |
|-------------|-----------|
| `400` | Bad Request — parameter tidak valid |
| `401` | Unauthorized — token tidak ada atau expired |
| `403` | Forbidden — role tidak memiliki akses |
| `404` | Not Found — resource tidak ditemukan |
| `422` | Validation Error — body request tidak sesuai schema |
| `500` | Internal Server Error — kesalahan server |

**Format Error Response:**
```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or expired authentication token",
    "timestamp": "2026-10-07T14:05:00Z"
  }
}
```

---

## Rate Limiting

Diterapkan di `app/middleware/ratelimit.py` — sliding window in-memory per (IP, method+endpoint). Hanya request `POST` yang dibatasi — `GET /analyze-trend/{id}` adalah poller status dan tidak menghabiskan kuota. Respons `429` + header `Retry-After`.

| Endpoint | Limit |
|----------|-------|
| `POST /api/v1/auth/login` | 10 / menit / IP (anti brute-force) |
| `POST /api/v1/analyze-trend` | 10 / menit / IP |
| `POST /api/v1/approve-workflow` | 20 / menit / IP |
| `POST /api/v1/alcd/trigger` | 3 / 5 menit / IP |

Endpoint lain saat ini tidak dibatasi (lokal standalone). Tambahkan aturan di `_RULES` bila dibutuhkan. Penyimpanan state: SQLite bersama (`RATELIMIT_DB`, default `~/.chroma/ratelimit.db`, mode WAL + `BEGIN IMMEDIATE`) — kuota dihitung benar di semua worker uvicorn pada host yang sama dan bertahan melintasi restart; bila DB gagal, fallback otomatis ke deque in-memory per-proses. Untuk multi-node (beda host) ganti penyimpanan ke Redis.

---

## OpenAPI / Swagger

Dokumentasi interaktif tersedia di:
- **Swagger UI:** `http://localhost:8080/docs`
- **ReDoc:** `http://localhost:8080/redoc`
- **OpenAPI JSON:** `http://localhost:8080/openapi.json`
