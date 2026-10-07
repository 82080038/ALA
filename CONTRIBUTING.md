# 🤝 Panduan Kontribusi — Autonomous Legal Agent (ALA)

> Terima kasih atas minat Anda untuk berkontribusi pada proyek ALA. Dokumen ini menjelaskan standar dan prosedur untuk kontribusi kode dan dokumentasi.

---

## 1. Getting Started

### 1.1 Fork & Clone

```bash
git clone <repo-url>
cd ALA
```

### 1.2 Setup Development Environment

```bash
# Buat virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Jalankan infrastruktur
docker compose up -d

# Inisialisasi database (tabel kosong saja — TIDAK ada data pra-muat)
docker compose exec api python scripts/init_db.py
```

> **Catatan:** Tidak ada `ingest_laws.py` atau `seed_graph.py`. Semua data hukum
> ditemukan dan di-ingest secara otonom oleh modul ALCD.

### 1.3 Verifikasi Setup

```bash
# Jalankan tests
pytest tests/ -v

# Jalankan API server
cd backend && uvicorn main:app --reload
```

---

## 2. Branching Strategy

Proyek ini menggunakan **Git Flow** yang disederhanakan:

```
main (production-ready)
  │
  ├── develop (integration branch)
  │     │
  │     ├── feature/crawler-rate-limit
  │     ├── feature/neo4j-cross-ref
  │     ├── bugfix/chromadb-timeout
  │     └── docs/update-api-docs
  │
  └── hotfix/security-patch (urgent fixes)
```

### Naming Convention

| Prefix | Penggunaan |
|--------|-----------|
| `feature/` | Fitur baru |
| `bugfix/` | Perbaikan bug |
| `hotfix/` | Perbaikan urgent (dari `main`) |
| `docs/` | Update dokumentasi |
| `refactor/` | Refactoring tanpa perubahan fungsional |
| `test/` | Penambahan/perbaikan test |

### Contoh

```bash
git checkout develop
git checkout -b feature/add-graph-visualization
```

---

## 3. Coding Standards

### 3.1 Python Style Guide

- **PEP 8** compliance
- **Line length:** Maksimum 100 karakter
- **Formatter:** `black` (konfigurasi default)
- **Linter:** `ruff` atau `flake8`
- **Type hints:** Wajib untuk semua function signatures

```python
# ✅ Benar
def parse_legal_article(
    article_text: str,
    law_name: str,
    max_chunks: int = 10,
) -> list[dict]:
    """Parse artikel hukum menjadi chunks untuk embedding."""
    ...

# ❌ Salah
def parse(t, n, m=10):
    ...
```

### 3.2 Docstrings

Gunakan format **Google style**:

```python
def search_laws(query: str, top_k: int = 5) -> list[dict]:
    """Cari pasal hukum menggunakan semantic search.

    Args:
        query: Query pencarian dalam Bahasa Indonesia.
        top_k: Jumlah hasil teratas yang dikembalikan.

    Returns:
        List dictionary berisi pasal hukum relevan dengan skor.

    Raises:
        ConnectionError: Jika ChromaDB tidak dapat dijangkau.
        ValueError: Jika query kosong.
    """
    ...
```

### 3.3 Naming Conventions

| Elemen | Convention | Contoh |
|--------|-----------|--------|
| **Variables** | `snake_case` | `crime_data`, `legal_articles` |
| **Functions** | `snake_case` | `parse_apk_log()`, `search_laws()` |
| **Classes** | `PascalCase` | `CrawlerAgent`, `LegalAnalyzer` |
| **Constants** | `UPPER_SNAKE_CASE` | `MAX_RESULTS`, `DEFAULT_TIMEOUT` |
| **Files** | `snake_case` | `crawler_agent.py`, `legal_orchestrator.py` |

### 3.4 Imports

Urutan imports (dipisah baris kosong):

```python
# 1. Standard library
import os
import json
from datetime import datetime

# 2. Third-party
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import chromadb

# 3. Local application
from app.agents.internet_crawler import CrawlerAgent
from app.database.postgres import get_db
```

---

## 4. Testing

### 4.1 Test Structure

```
tests/
├── test_agents.py       # Tests untuk agents
├── test_api.py          # Tests untuk API endpoints
├── test_db.py           # Tests untuk database operations
├── test_sandbox.py      # Tests untuk sandbox & guardrails
├── conftest.py          # Shared fixtures
└── fixtures/
    ├── sample_laws.json
    └── sample_queries.json
```

### 4.2 Writing Tests

```python
import pytest
from app.agents.legal_foundation import LegalFoundationAgent

class TestLegalFoundation:
    """Tests untuk Legal Foundation Agent."""

    def test_search_returns_relevant_articles(self):
        """Pastikan search mengembalikan pasal relevan."""
        agent = LegalFoundationAgent()
        results = agent.search("akses ilegal komputer")
        
        assert len(results) > 0
        assert any("UU ITE" in r["law_name"] for r in results)

    def test_relevance_score_threshold(self):
        """Pastikan semua hasil di atas threshold minimum."""
        agent = LegalFoundationAgent()
        results = agent.search("pencurian data pribadi")
        
        for result in results:
            assert result["relevance_score"] >= 0.5

    def test_empty_query_raises_error(self):
        """Pastikan query kosong menimbulkan error."""
        agent = LegalFoundationAgent()
        with pytest.raises(ValueError):
            agent.search("")
```

### 4.3 Menjalankan Tests

```bash
# Semua tests
pytest tests/ -v

# Specific file
pytest tests/test_agents.py -v

# Dengan coverage
pytest tests/ --cov=. --cov-report=html

# Hanya tests tertentu
pytest tests/ -k "test_search"
```

### 4.4 Coverage Target

- **Minimum:** 70% overall coverage
- **Target:** 85% untuk code di `agents/` dan `sandbox/`

---

## 5. Commit Messages

Gunakan format **Conventional Commits**:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | Deskripsi |
|------|-----------|
| `feat` | Fitur baru |
| `fix` | Perbaikan bug |
| `docs` | Update dokumentasi |
| `style` | Formatting, tanpa perubahan logic |
| `refactor` | Refactoring kode |
| `test` | Penambahan/perbaikan test |
| `chore` | Maintenance, tooling |
| `perf` | Peningkatan performa |
| `security` | Perbaikan keamanan |

### Contoh

```
feat(crawler): add rate limiting for Google Search API

Implement 1 request/second rate limiting to avoid
hitting Google API quotas.

Closes #42
```

```
fix(guardrails): block nested eval() patterns

Added detection for nested eval/exec calls in
generated code that could bypass simple pattern matching.
```

```
docs(api): update analyze-trend endpoint documentation

Added missing query parameters and updated response
schema to match current implementation.
```

---

## 6. Pull Request Process

### 6.1 Sebelum Submit

- [ ] Kode mengikuti coding standards (PEP 8, type hints)
- [ ] Tests baru ditambahkan untuk fitur/bugfix
- [ ] Semua tests lulus (`pytest tests/ -v`)
- [ ] Dokumentasi diupdate (jika perlu)
- [ ] Commit messages mengikuti Conventional Commits
- [ ] Branch di-rebase ke `develop` terbaru

### 6.2 PR Template

```markdown
## Deskripsi
[Jelaskan perubahan yang dilakukan]

## Tipe Perubahan
- [ ] Fitur baru
- [ ] Perbaikan bug
- [ ] Update dokumentasi
- [ ] Refactoring
- [ ] Security fix

## Testing
- [ ] Unit tests ditambahkan/diupdate
- [ ] Tests lulus secara lokal
- [ ] Manual testing dilakukan

## Checklist
- [ ] Kode mengikuti style guide
- [ ] Self-review dilakukan
- [ ] Tidak ada hardcoded secrets
- [ ] Tidak ada breaking changes
```

### 6.3 Review Process

1. Minimal **1 reviewer** harus approve sebelum merge
2. **Security-related** PR memerlukan 2 reviewer
3. Reviewer fokus pada: correctness, security, readability, test coverage
4. Gunakan **Squash merge** ke `develop`

---

## 7. Struktur Kode

### 7.1 Menambah Agent Baru

Jika perlu menambah agent baru ke pipeline:

1. Buat file di `backend/app/agents/new_agent.py`
2. Implementasi function yang menerima dan mengembalikan `ALA_State`
3. Tambahkan node baru di `backend/app/agents/legal_orchestrator.py`
4. Update `ALA_State` TypedDict jika perlu field baru
5. Tambahkan tests di `tests/test_agents.py`
6. Update `AGENTS.md`

### 7.2 Menambah API Endpoint

1. Buat route di `backend/app/api/v1/` (atau router baru di bawahnya)
2. Definisikan Pydantic models di `backend/app/models/`
3. Register route di `backend/app/api/v1/router.py`
4. Tambahkan tests di `tests/test_api.py`
5. Update `API.md`

### 7.3 Menambah Database Table

1. Update schema di `backend/scripts/init_db.py` (DDL) atau model ORM di `backend/app/models/`
2. Update `DATABASE_SCHEMA.md`
3. Tambahkan migration script (Alembic) jika diperlukan

---

## 8. Pelaporan Bug

Gunakan template berikut:

```markdown
## Bug Description
[Deskripsi singkat bug]

## Steps to Reproduce
1. ...
2. ...
3. ...

## Expected Behavior
[Apa yang seharusnya terjadi]

## Actual Behavior
[Apa yang terjadi]

## Environment
- OS: 
- Python version: 
- Docker version: 
- Branch: 

## Logs / Screenshots
[Lampirkan log error atau screenshot]
```

---

## 9. Kontak

Untuk pertanyaan tentang kontribusi, hubungi tim pengembang ALA melalui jalur komunikasi internal.
