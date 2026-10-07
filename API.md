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

Token diperoleh melalui endpoint login. Role-Based Access Control (RBAC) diterapkan berdasarkan role user: `super_admin`, `admin_instansi`, `penyidik`, `jaksa`, `hakim` (lihat `SECURITY.md` §2.2 untuk permission matrix lengkap).

> **Catatan Fase 1:** JWT belum diimplementasi. Middleware tenant (`backend/app/middleware/tenant.py`) sementara membaca konteks dari header `X-Institution-ID`, `X-User-ID`, `X-User-Role`, `X-Tier-Level` untuk pengujian.

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

### 2. Analisis Tren Kejahatan

```
POST /api/v1/analyze-trend
```

**Deskripsi:** Memicu pipeline LangGraph **law-first** untuk menganalisis tren kejahatan berdasarkan query pengguna. Pipeline dimulai dengan penguasaan hukum, lalu crawling internet untuk tren kejahatan universal, dan terakhir sintesis + generasi kode.

**Request Body:**
```json
{
  "query": "modus pencucian uang melalui cryptocurrency",
  "max_sources": 10,
  "include_code_generation": true
}
```

| Field | Type | Required | Default | Deskripsi |
|-------|------|----------|---------|-----------|
| `query` | `string` | ✅ | — | Query analisis dalam Bahasa Indonesia |
| `max_sources` | `integer` | ❌ | `10` | Jumlah maksimal sumber internet yang dicrawl |
| `include_code_generation` | `boolean` | ❌ | `true` | Apakah Developer Agent generate kode utilitas |

**Response `200 OK`:**
```json
{
  "request_id": "uuid-v4",
  "legal_foundation": {
    "articles": [
      {
        "law_name": "UU TPPU",
        "article_number": "Pasal 3",
        "title": "Pencucian Uang",
        "content": "Setiap Orang yang menempatkan, mentransfer...",
        "relevance_score": 0.96
      },
      {
        "law_name": "KUHP",
        "article_number": "Pasal 55",
        "title": "Penyertaan",
        "content": "...",
        "relevance_score": 0.81
      }
    ],
    "cross_references": [
      {
        "from": "UU TPPU Pasal 3",
        "to": "KUHP Pasal 55",
        "relationship": "CROSS_REFERENCES"
      }
    ],
    "legal_summary": "Modus pencucian uang via cryptocurrency dapat dijerat UU TPPU Pasal 3..."
  },
  "crime_trend": {
    "name": "Pencucian Uang via Cryptocurrency",
    "description": "Skema pencucian uang hasil korupsi menggunakan aset kripto lintas negara...",
    "sources": [
      {
        "title": "KPK Ungkap Modus Baru Pencucian Uang via Aset Kripto",
        "url": "https://example.com/article",
        "published_date": "2026-09-15",
        "snippet": "..."
      }
    ]
  },
  "synthesis": {
    "law_reality_mapping": "UU TPPU Pasal 3 dapat diterapkan pada skema crypto laundering...",
    "regulatory_gaps": "Belum ada regulasi spesifik untuk DeFi mixing services...",
    "enforcement_strategy": "Gunakan pendekatan follow-the-money dengan PPATK..."
  },
  "generated_code": {
    "filename": "crypto_transaction_analyzer.py",
    "language": "python",
    "description": "Script untuk analisis transaksi cryptocurrency mencurigakan",
    "code": "import re\nimport json\n...",
    "requires_approval": true
  },
  "flowchart": "graph TD\n  A[Identifikasi Wallet] --> B[Trace Transaksi]\n  B --> C[Analisis Pattern]\n  ...",
  "audit_id": "uuid-v4"
}
```

**Response `422 Validation Error`:**
```json
{
  "detail": [
    {
      "loc": ["body", "query"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

### 3. Approval Workflow

```
POST /api/v1/approve-workflow
```

**Deskripsi:** Mencatat persetujuan APH untuk mengeksekusi kode yang digenerate AI. Approval dicatat dalam audit log immutable.

**Request Body:**
```json
{
  "request_id": "uuid-v4",
  "action": "approve",
  "approver_badge_number": "APH-2024-001",
  "notes": "Kode telah direview, aman untuk dieksekusi"
}
```

| Field | Type | Required | Deskripsi |
|-------|------|----------|-----------|
| `request_id` | `string (uuid)` | ✅ | ID request dari `/api/analyze-trend` |
| `action` | `string` | ✅ | `approve` atau `reject` |
| `approver_badge_number` | `string` | ✅ | Nomor badge APH yang memberikan approval |
| `notes` | `string` | ❌ | Catatan tambahan dari approver |

**Response `200 OK` (approve):**
```json
{
  "status": "approved",
  "audit_id": "uuid-v4",
  "execution_result": {
    "status": "success",
    "output": "Analyzed 1,247 transactions. Found 23 suspicious patterns.",
    "execution_time_ms": 1250
  }
}
```

**Response `200 OK` (reject):**
```json
{
  "status": "rejected",
  "audit_id": "uuid-v4",
  "message": "Workflow rejected by approver"
}
```

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
  "status": "in_progress",
  "assigned_to": {
    "name": "Budi Santoso",
    "badge_number": "APH-2024-001",
    "role": "penyidik"
  },
  "analysis_history": [
    {
      "audit_id": "uuid-v4",
      "query": "metode phishing APK terbaru",
      "timestamp": "2026-10-05T15:30:00Z",
      "status": "approved"
    }
  ],
  "created_at": "2026-09-01T10:00:00Z",
  "updated_at": "2026-10-05T15:30:00Z"
}
```

---

### 6. Audit Logs

```
GET /api/v1/audit-logs
```

**Deskripsi:** Mengambil immutable audit log seluruh aktivitas AI dalam sistem.

**Query Parameters:**

| Parameter | Type | Default | Deskripsi |
|-----------|------|---------|-----------|
| `start_date` | `string (ISO 8601)` | — | Filter tanggal mulai |
| `end_date` | `string (ISO 8601)` | — | Filter tanggal akhir |
| `action` | `string` | `all` | Filter: `analyze`, `approve`, `reject`, `execute` |
| `page` | `integer` | `1` | Halaman paginasi |
| `per_page` | `integer` | `50` | Jumlah item per halaman |

**Response `200 OK`:**
```json
{
  "total": 156,
  "page": 1,
  "per_page": 50,
  "logs": [
    {
      "id": "uuid-v4",
      "timestamp": "2026-10-07T14:05:00Z",
      "action": "approve",
      "user_badge": "APH-2024-001",
      "request_id": "uuid-v4",
      "rationale": "Kode telah direview, aman untuk dieksekusi",
      "code_generated": "import re\n...",
      "execution_result": "success"
    }
  ]
}
```

---

### 7. Graph Query (Neo4j)

```
POST /api/v1/graph/query
```

**Deskripsi:** Menjalankan query terhadap graph database untuk melihat relasi antar entitas.

**Request Body:**
```json
{
  "entity_type": "LegalArticle",
  "entity_id": "UU_ITE_Pasal_30",
  "relationship_types": ["CROSS_REFERENCES", "CONTRADICTS"],
  "depth": 2
}
```

**Response `200 OK`:**
```json
{
  "center_node": {
    "label": "LegalArticle",
    "properties": {
      "law_name": "UU ITE",
      "article_number": "Pasal 30",
      "title": "Akses Ilegal"
    }
  },
  "relationships": [
    {
      "type": "CROSS_REFERENCES",
      "target": {
        "label": "LegalArticle",
        "properties": {
          "law_name": "UU ITE",
          "article_number": "Pasal 32"
        }
      }
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

### 9. ALCD — Trigger Learning

```
POST /api/v1/alcd/trigger
```

**Deskripsi:** Memicu ALCD untuk menjalankan siklus pembelajaran (ontology → acquisition → self-evaluation) secara on-demand.

**Auth:** `super_admin` only

**Request Body:**
```json
{
  "mode": "full",
  "focus_categories": []
}
```

| Field | Type | Deskripsi |
|-------|------|-----------|
| `mode` | `string` | `full` (bootstrap penuh), `incremental` (hanya gap), `evaluate_only` (hanya evaluasi) |
| `focus_categories` | `string[]` | Opsional. Fokus pada kategori tertentu, misal `["yurisprudensi"]` |

**Response `202 Accepted`:**
```json
{
  "task_id": "uuid-v4",
  "status": "started",
  "mode": "full",
  "message": "ALCD learning cycle initiated. Monitor progress via GET /api/v1/alcd/status."
}
```

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

| Endpoint | Limit |
|----------|-------|
| `/api/analyze-trend` | 10 requests / menit / user |
| `/api/approve-workflow` | 30 requests / menit / user |
| `/api/cases` | 60 requests / menit / user |
| `/api/audit-logs` | 60 requests / menit / user |
| `/api/graph/query` | 30 requests / menit / user |
| `/api/alcd/status` | 60 requests / menit / user |
| `/api/alcd/trigger` | 1 request / jam / user |
| `/api/alcd/ontology` | 30 requests / menit / user |
| `/api/alcd/gaps` | 30 requests / menit / user |

---

## OpenAPI / Swagger

Dokumentasi interaktif tersedia di:
- **Swagger UI:** `http://localhost:8080/docs`
- **ReDoc:** `http://localhost:8080/redoc`
- **OpenAPI JSON:** `http://localhost:8080/openapi.json`
