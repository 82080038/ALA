# 🔒 Kebijakan Keamanan — Autonomous Legal Agent (ALA)

> Dokumen ini menjelaskan seluruh aspek keamanan sistem ALA, termasuk guardrails AI, isolasi sandbox, kontrol akses, dan kepatuhan hukum.

---

## 1. Prinsip Keamanan

ALA menerapkan pendekatan **Defense in Depth** dengan beberapa lapisan keamanan:

```
┌───────────────────────────────────────────────┐
│  Layer 1: Authentication & Authorization      │
│  (JWT Token + RBAC)                           │
├───────────────────────────────────────────────┤
│  Layer 2: Input Validation                    │
│  (Pydantic schema + sanitization)             │
├───────────────────────────────────────────────┤
│  Layer 3: AI Guardrails                       │
│  (Code scanning + pattern blacklist)          │
├───────────────────────────────────────────────┤
│  Layer 4: Sandbox Isolation                   │
│  (Docker container, no network, read-only)    │
├───────────────────────────────────────────────┤
│  Layer 5: Human-in-the-Loop                   │
│  (Mandatory approval sebelum eksekusi)        │
├───────────────────────────────────────────────┤
│  Layer 6: Immutable Audit Log                 │
│  (Append-only PostgreSQL + timestamp)         │
└───────────────────────────────────────────────┘
```

---

## 2. Authentication & Authorization

### 2.1 Autentikasi

- **Metode:** JWT (JSON Web Token) Bearer Token
- **Algoritma:** HS256
- **Expiry:** 24 jam (configurable)
- **Refresh Token:** 7 hari

### 2.2 Role-Based Access Control (RBAC)

Sistem menerapkan model **multi-tenant lintas-institusi** (lihat `backend/app/models/tenant.py`):

| Role | Deskripsi | Hak Akses |
|------|-----------|-----------|
| `super_admin` | Otoritas global platform | Full access: kelola institusi, users lintas-institusi, tier fitur, semua data |
| `admin_instansi` | Admin per institusi | CRUD users & cases dalam institusi sendiri, konfigurasi institusi |
| `penyidik` | Penyidik / Investigator APH | Analyze trends, approve workflows, manage cases |
| `jaksa` | Jaksa penuntut | Analyze trends, view cases, approve workflows dalam institusi |
| `hakim` | Hakim | Analyze trends (read-only), view cases & audit logs |

Selain role, setiap user memiliki **tier akses** (`free`, `premium_l1`, `premium_l2`) yang mengatur fitur AI mana yang dapat digunakan.

### 2.3 Permission Matrix

| Endpoint | `super_admin` | `admin_instansi` | `penyidik` | `jaksa` | `hakim` |
|----------|---------------|------------------|------------|---------|---------|
| `POST /api/analyze-trend` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `POST /api/approve-workflow` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `GET /api/cases` | ✅ (semua) | ✅ (institusi) | ✅ | ✅ | ✅ (read-only) |
| `POST /api/cases` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `GET /api/audit-logs` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `POST /api/graph/query` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `GET /api/alcd/status` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `POST /api/alcd/trigger` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `GET /api/alcd/ontology` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `GET /api/alcd/gaps` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `GET /api/v1/admin/*` | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## 3. AI Guardrails

### 3.1 Code Safety Scanner (`sandbox/guardrails.py`)

Sebelum kode yang digenerate AI dieksekusi, kode harus melewati pemindaian keamanan:

#### Blacklisted Patterns

```python
BLACKLISTED_PATTERNS = [
    # Shell execution
    r"os\.system\s*\(",
    r"os\.popen\s*\(",
    r"subprocess\.\w+\s*\(",
    r"commands\.\w+\s*\(",
    
    # Destructive operations
    r"shutil\.rmtree\s*\(",
    r"os\.remove\s*\(",
    r"os\.unlink\s*\(",
    r"rm\s+-rf",
    
    # Network access
    r"socket\.\w+\s*\(",
    r"urllib\.\w+",
    r"requests\.\w+\s*\(",
    r"http\.client",
    r"ftplib",
    
    # Code injection
    r"eval\s*\(",
    r"exec\s*\(",
    r"compile\s*\(",
    r"__import__\s*\(",
    
    # Sensitive file access
    r"open\s*\(\s*['\"]\/etc",
    r"open\s*\(\s*['\"]\/proc",
    r"open\s*\(\s*['\"]\/sys",
    r"open\s*\(\s*['\"]\/root",
    
    # Environment variable exfiltration
    r"os\.environ",
    r"os\.getenv\s*\(",
]
```

#### Whitelisted Imports

Hanya library berikut yang diperbolehkan dalam kode yang digenerate:

```python
WHITELISTED_IMPORTS = [
    "re",           # Regex
    "json",         # JSON parsing
    "csv",          # CSV processing
    "datetime",     # Date/time utilities
    "collections",  # Data structures
    "itertools",    # Iteration utilities
    "math",         # Math operations
    "statistics",   # Statistical functions
    "hashlib",      # Hashing
    "base64",       # Encoding
    "ipaddress",    # IP address parsing
    "textwrap",     # Text formatting
    "pathlib",      # Path operations (read-only)
    "typing",       # Type hints
]
```

### 3.2 Proses Scanning

```
[Generated Code]
    │
    ├──▶ Step 1: Syntax Validation (ast.parse)
    │    Gagal? → Reject + log error
    │
    ├──▶ Step 2: Blacklist Pattern Scan
    │    Ditemukan? → Reject + log pattern
    │
    ├──▶ Step 3: Import Whitelist Check
    │    Non-whitelisted? → Reject + log import
    │
    ├──▶ Step 4: AST Node Analysis
    │    Suspicious nodes? → Reject + log node
    │
    └──▶ ✅ PASS → Kode aman untuk review manusia
```

---

## 4. Sandbox Isolation

### 4.1 Docker Container Configuration

```dockerfile
FROM python:3.11-slim

# Minimal dependencies
RUN pip install --no-cache-dir regex

# Non-root user
RUN useradd -m -s /bin/bash sandbox_user
USER sandbox_user

# Working directory
WORKDIR /sandbox
```

### 4.2 Runtime Constraints

| Constraint | Nilai | Alasan |
|-----------|-------|--------|
| **Network** | `none` (disabled) | Mencegah data exfiltration |
| **Filesystem** | `read_only: true` | Mencegah persistence malware |
| **tmpfs** | `/tmp` (256MB) | Temporary workspace |
| **Memory** | 256MB limit | Mencegah memory bomb |
| **CPU** | 0.5 cores | Mencegah resource exhaustion |
| **Timeout** | 30 detik | Mencegah infinite loops |
| **User** | non-root | Principle of least privilege |
| **Capabilities** | `drop: ALL` | Tidak ada kernel capabilities |

### 4.3 Execution Flow

```python
import subprocess
import tempfile
import os

def execute_in_sandbox(code: str, timeout: int = 30) -> dict:
    """Eksekusi kode dalam Docker sandbox."""
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        temp_path = f.name
    
    try:
        result = subprocess.run(
            [
                "docker", "run",
                "--rm",                          # Auto-remove container
                "--network=none",                # No network
                "--read-only",                   # Read-only filesystem
                "--tmpfs=/tmp:size=256m",         # Writable temp
                "--memory=256m",                 # Memory limit
                "--cpus=0.5",                    # CPU limit
                "--user=sandbox_user",           # Non-root
                "-v", f"{temp_path}:/sandbox/script.py:ro",
                "ala-sandbox:latest",
                "python", "/sandbox/script.py"
            ],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"Execution exceeded {timeout}s limit"}
    finally:
        os.unlink(temp_path)
```

---

## 5. Human-in-the-Loop

### 5.1 Prinsip

**Tidak ada kode AI yang dieksekusi tanpa persetujuan eksplisit dari personel APH.**

### 5.2 Alur Approval

```
[AI Generate Code]
    │
    ├──▶ Guardrail Scan (otomatis)
    │
    ├──▶ Tampilkan ke APH user:
    │    - Kode yang digenerate
    │    - Deskripsi fungsi
    │    - Flowchart workflow
    │    - Warning (jika ada)
    │
    ├──▶ APH memilih:
    │    ├── [APPROVE] → Eksekusi di sandbox + log audit
    │    └── [REJECT]  → Tidak dieksekusi + log audit
    │
    └──▶ Audit Log (immutable):
         - Siapa yang approve/reject (badge number)
         - Kapan (timestamp)
         - Kode apa yang di-approve/reject
         - Alasan (notes)
```

### 5.3 Aturan

1. Approval hanya dari role `super_admin`, `admin_instansi`, `penyidik`, atau `jaksa`
2. Approval tidak dapat dibatalkan setelah eksekusi
3. Rejection tetap tercatat dalam audit log
4. Kode yang sama harus di-approve ulang jika dijalankan lagi

---

## 6. Data Protection

### 6.1 Data Classification

| Klasifikasi | Contoh Data | Perlakuan |
|-------------|-------------|-----------|
| **Rahasia** | Data kasus, identitas tersangka, intelijen kejahatan | Enkripsi at-rest, akses terbatas |
| **Internal** | Audit logs, hasil analisis, sintesis hukum-realitas, self-eval logs | Akses sesuai RBAC |
| **Publik** | Teks undang-undang (autonomously acquired by ALCD from public sources) | Bebas akses |

### 6.2 Enkripsi

| Layer | Metode |
|-------|--------|
| **At Rest** | PostgreSQL: `pgcrypto` extension, AES-256 |
| **In Transit** | HTTPS/TLS 1.3 untuk API |
| **Passwords** | bcrypt (cost factor 12) |
| **API Keys** | Environment variables, never in code |

### 6.3 Data Retention

| Data | Retensi | Alasan |
|------|---------|--------|
| Audit logs | Permanen (immutable) | Kepatuhan hukum |
| Hasil crawling | 90 hari | Storage optimization |
| ALCD ontology & eval logs | Permanen | Knowledge base audit trail |
| Knowledge registry | Permanen | Track all autonomously discovered laws |
| Generated code | 365 hari | Referensi investigasi |
| User sessions | 24 jam | Keamanan |

---

## 7. Deployment Security

### 7.1 Environment Variables

**JANGAN PERNAH** hardcode secrets dalam kode. Gunakan `.env`:

```bash
# .env (JANGAN commit ke repository)
POSTGRES_PASSWORD=<strong-random-password>
NEO4J_PASSWORD=<strong-random-password>
JWT_SECRET=<strong-random-secret>
# LLM lokal via Ollama — TIDAK ada API key cloud
OLLAMA_BASE_URL=http://host.docker.internal:11434
# Opsional — hanya untuk discovery dokumen publik (bukan inferensi)
GOOGLE_CSE_ID=<custom-search-engine-id>
GOOGLE_CSE_API_KEY=<key>
```

### 7.2 Network Security

```
┌─────────────────────────────────────┐
│         Internal Network            │
│                                     │
│  [FastAPI] ◄──── HTTPS ────► [User] │
│     │                               │
│     ├── PostgreSQL (5432) - internal │
│     ├── Neo4j (7687) - internal     │
│     ├── ChromaDB (8000) - internal  │
│     └── Sandbox (no network)        │
│                                     │
│  Firewall: Only port 443 exposed    │
└─────────────────────────────────────┘
```

### 7.3 Checklist Keamanan Deployment

- [ ] Semua passwords menggunakan strong random values
- [ ] `.env` tidak ada dalam repository (ada di `.gitignore`)
- [ ] HTTPS enabled untuk semua external traffic
- [ ] Database ports tidak exposed ke publik
- [ ] Docker images menggunakan non-root users
- [ ] Sandbox container tanpa network access
- [ ] Rate limiting aktif untuk semua API endpoints
- [ ] Audit logging aktif dan immutable
- [ ] Backup encrypted dan disimpan terpisah
- [ ] Dependency vulnerabilities di-scan secara berkala
- [ ] ALCD crawl rate limiting configured (maks 1 req/s per domain)
- [ ] ALCD trusted domains verified and accessible
- [ ] ALCD trigger endpoint restricted to super_admin role only

---

## 8. Incident Response

### 8.1 Severity Levels

| Level | Deskripsi | Response Time |
|-------|-----------|---------------|
| **P0 - Critical** | Data breach, system compromise | Immediate (< 1 jam) |
| **P1 - High** | AI generates harmful code yang lolos guardrail | < 4 jam |
| **P2 - Medium** | Unauthorized access attempt | < 24 jam |
| **P3 - Low** | Configuration issue, non-security bug | < 72 jam |

### 8.2 Response Procedure

1. **Detect** — Monitoring dan alerting
2. **Contain** — Isolasi sistem terdampak
3. **Investigate** — Analisis audit logs
4. **Remediate** — Perbaiki vulnerability
5. **Report** — Dokumentasikan insiden
6. **Review** — Post-mortem dan update kebijakan

---

## 9. Reporting Security Issues

Jika menemukan kerentanan keamanan, laporkan ke tim pengembang ALA melalui jalur internal yang telah ditentukan. **Jangan** mengungkapkan kerentanan secara publik sebelum diperbaiki.
