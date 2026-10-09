# 📋 Rencana Pengembangan (Roadmap) — Autonomous Legal Agent (ALA)

> Dokumen ini menjabarkan roadmap pengembangan ALA dari tahap fondasi hingga produksi penuh, termasuk milestone, deliverables, dan kriteria keberhasilan per fase.

---

## Ikhtisar Timeline

```
Bulan 1─2      Bulan 3─4      Bulan 5─6      Bulan 7─8      Bulan 9+
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  FASE 1  │  │  FASE 2  │  │  FASE 3  │  │  FASE 4  │  │  FASE 5  │
│ Fondasi  │→│  Agen AI │→│ Sandbox  │→│ Validasi │→│ Produksi │
│  & Data  │  │  & RAG   │  │ & Graph  │  │ & Pilot  │  │  & Scale │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
```

---

## Fase 1: Fondasi & ALCD Module (Bulan 1–2)

**Tujuan:** Menyiapkan seluruh infrastruktur dasar dan membangun modul Autonomous Legal Curriculum Designer (ALCD) yang mampu membangun basis pengetahuan dari NOL data.

> **PENTING:** Tidak ada direktori `data/` dengan dokumen hukum pra-muat. Semua data ditemukan dan di-ingest secara otonom oleh ALCD.

### Milestone & Deliverables

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 1.1 | Setup Docker Compose | `docker-compose.yml` dengan PostgreSQL, Neo4j, ChromaDB | ✅ Done |
| 1.2 | Setup Python environment | `backend/requirements.txt`, virtual environment | ✅ Done |
| 1.3 | Desain skema PostgreSQL | Tabel `users`, `cases`, `ai_audit_logs`, `knowledge_registry`, `ontology_nodes`, `self_eval_logs` | ✅ Done |
| 1.4 | Script inisialisasi DB | `backend/scripts/init_db.py` — tabel kosong saja, TANPA data | ✅ Done |
| 1.5 | ALCD: Ontology Generator | `backend/app/agents/alcd/ontology_generator.py` — AI merumuskan knowledge tree dari core objective | ✅ Done |
| 1.6 | ALCD: Source Discoverer | `backend/app/agents/alcd/source_discoverer.py` — CSE→DDG→BPK fallback + circuit breaker | ✅ Done |
| 1.7 | ALCD: Document Parser | `backend/app/agents/alcd/document_parser.py` — HTML/PDF/OCR, hierarki Bab→Bagian→Paragraf→Pasal | ✅ Done |
| 1.8 | ALCD: Autonomous Ingestor | `backend/app/agents/alcd/autonomous_ingestor.py` — Chunk 500/50, E5 embed, ChromaDB GLOBAL upsert | ✅ Done |
| 1.9 | ALCD: Graph Builder | `backend/app/agents/alcd/graph_builder.py` — `LegalArticle` + `CROSS_REFERENCES` di Neo4j | ✅ Done |
| 1.10 | ALCD: Self-Evaluator | `backend/app/agents/evaluator.py` — deterministik (registry ∩ kanonik) + `scripts/eval_gold.py` (P@k/MRR gold) | ✅ Done |
| 1.11 | ALCD: Curriculum Agent | `backend/app/agents/curriculum_designer.py` — pipeline: ontologi → doktrin → korpus terverifikasi → crawl celah → evaluasi | ✅ Done |
| 1.12 | Bootstrap Test | Bootstrap dari nol terverifikasi: 2.155 dokumen (incl. 2.000 putusan MA pidana), ~116.800 chunk, skor 0.916 (Okt 2026) | ✅ Done |
| 1.13 | Doctrine Foundation | `alcd/doctrine.py` — 21 konsep ilmu hukum berjenjang, kategori `doktrin` | ✅ Done |
| 1.14 | External Corpus Importer | `alcd/external_corpus.py` — `spkt://` `lexisai://` `aph://` `hf://laws` `hf://putusan`, idempotent | ✅ Done |

### Kriteria Keberhasilan
- ✅ Docker Compose berjalan stabil dengan semua 3 database services
- ✅ ALCD berhasil generate ontology tree minimal 10 node dari core objective
- ✅ ALCD berhasil menemukan dan meng-ingest minimal 5 UU dari internet secara otonom
- ✅ Self-evaluation score rata-rata ≥ 0.7 untuk semua ontology node
- ✅ `knowledge_registry` terisi dengan semua UU yang di-ingest beserta source URL

---

## Fase 2: Agen AI & RAG Pipeline (Bulan 3–4)

**Tujuan:** Membangun sistem multi-agent **ALCD + law-first** dengan LangGraph dan mengintegrasikan RAG pipeline terhadap basis pengetahuan yang dibangun ALCD.

### Milestone & Deliverables

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 2.1 | Setup LangGraph state machine | `backend/app/agents/legal_orchestrator.py` dengan 4 agen (ALCD → Legal → Crawl → Synth) | ✅ Done |
| 2.2 | ALCD readiness check per query | Agent 0 memeriksa `knowledge_score ≥ threshold` sebelum memproses query | ✅ Done |
| 2.3 | Legal Foundation Agent (Agent 1) | `legal_foundation.py` — **hybrid** E5-dense ∪ BM25 → RRF + feedback boost + abstention + audit sitasi 3 sumbu | ✅ Done |
| 2.4 | Internet Crawler Agent (Agent 2) | `backend/app/agents/internet_crawler.py` — Universal crime trend discovery | ✅ Done |
| 2.5 | Synthesis & Developer Agent (Agent 3) | `backend/app/agents/code_generator.py` — Sintesis hukum↔realitas + code generation | ✅ Done |
| 2.6 | Integrasi LLM Provider | Ollama lokal: `qwen2.5:3b-instruct` (GPU 0) + `qwen2.5-coder:3b` (GPU 1) dual-instance | ✅ Done |
| 2.7 | FastAPI basic endpoints | `backend/main.py`, routes `/api/v1/analyze-trend`, `/api/v1/alcd/*` (+`progress` feed) | ✅ Done |
| 2.8 | End-to-end test pipeline | Query → ALCD check → Legal Foundation → Crawl → Synthesize + Generate | ✅ Done |

### Kriteria Keberhasilan
- ✅ Pipeline ALCD + law-first end-to-end berjalan: ALCD check → legal foundation → crawl → synthesis + kode
- ✅ Legal Foundation Agent menguasai pasal dari minimal 5 UU yang di-ingest ALCD per query
- ✅ Internet Crawler berhasil mengambil tren kejahatan dari berbagai kategori (bukan hanya siber)
- ✅ Synthesis & Developer Agent menghasilkan kode Python yang valid dan tervalidasi KUHAP
- ✅ ALCD endpoint `/api/v1/alcd/status` mengembalikan informasi skor pengetahuan yang akurat

---

## Fase 3: Graph DB, Sandbox & Guardrails (Bulan 5–6)

**Tujuan:** Mengimplementasikan Neo4j untuk pemetaan relasi, sandbox eksekusi kode, dan sistem keamanan.

### Milestone & Deliverables

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 3.1 | Desain graph schema Neo4j | Node `LegalArticle` + rel `CROSS_REFERENCES` | ✅ Done |
| 3.2 | Verifikasi graph ALCD | 8.592 node / 3.661 edge rujukan nyata terverifikasi | ✅ Done |
| 3.3 | Integrasi Neo4j ke Legal Agent | Query graph untuk cross-references dalam analisis | ✅ Done |
| 3.4 | Docker Sandbox setup | `sandbox/Dockerfile` (image terkunci), `backend/app/sandbox/execution_env.py` | ✅ Done |
| 3.5 | Guardrail Filter | `backend/app/sandbox/guardrails.py` — malicious pattern scanner | ✅ Done |
| 3.6 | Approval workflow endpoint | `POST /api/v1/approve-workflow` + audit logging | ✅ Done |
| 3.7 | Unit & integration tests | `tests/` — 26 pass, 3 skip | ✅ Done |

### Kriteria Keberhasilan
- ✅ Neo4j graph berisi minimal 50 relasi cross-reference antar pasal
- ✅ Kode berbahaya (test cases) berhasil diblokir oleh Guardrail Filter
- ✅ Sandbox menjalankan kode terisolasi tanpa akses jaringan
- ✅ Approval workflow tercatat dalam audit log PostgreSQL

---

## Fase 4: UI Dashboard & Validasi Manusia (Bulan 7–8)

**Tujuan:** Membangun antarmuka pengguna dan melakukan pilot testing dengan berbagai unit kerja APH.

### Milestone & Deliverables

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 4.1 | Dashboard UI | `frontend/` — Next.js + TypeScript + Tailwind; canvas "otak" live (kamera fokus ke wilayah yang diproses, pulsa data nyata, neural.log) | ✅ Done |
| 4.2 | Visualisasi tren kejahatan | Crime trend cards dengan sumber & waktu deteksi | ✅ Done |
| 4.3 | Tampilan pasal hukum | List pasal relevan dengan highlight & snippet | ✅ Done |
| 4.4 | Visualisasi flowchart | Mermaid.js rendering untuk workflow | ✅ Done |
| 4.5 | Code viewer & download | Syntax-highlighted code + tombol download/execute | ✅ Done |
| 4.6 | Human-in-the-Loop UI | Tombol Approve / Reject dengan konfirmasi | ✅ Done |
| 4.7 | Audit log viewer | Tabel history semua aktivitas AI | ✅ Done |
| 4.8 | Pilot testing | Test dengan 3–5 personel dari berbagai unit APH (Reskrim, Tipikor, Cyber, Narkoba) | ⬜ Pending |

### Kriteria Keberhasilan
- ✅ Dashboard responsif dan dapat diakses dari browser desktop
- ✅ Seluruh alur kerja (query → review → approve → execute) berjalan melalui UI
- ✅ Feedback positif dari minimal 3 personel APH pada pilot testing
- ✅ Tidak ada bug kritis (P0/P1) ditemukan selama pilot

---

## Fase 5: Produksi & Skalabilitas (Bulan 9+)

**Tujuan:** Hardening keamanan, optimasi performa, dan persiapan deployment produksi.

### Milestone & Deliverables

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 5.1 | Security audit | Penetration testing, vulnerability assessment | ⬜ Pending |
| 5.2 | Performance optimization | Query caching, connection pooling, async processing | ⬜ Pending |
| 5.3 | Monitoring & alerting | Logging terstruktur, health checks, uptime monitoring | ⬜ Pending |
| 5.4 | Dokumentasi operasional | Runbook, SOP, user manual | ⬜ Pending |
| 5.5 | Backup & disaster recovery | Automated backup PostgreSQL, Neo4j, ChromaDB | ⬜ Pending |
| 5.6 | Training APH users | Workshop penggunaan sistem untuk personel APH | ⬜ Pending |
| 5.7 | Go-live deployment | Production deployment on-premise | ⬜ Pending |

### Kriteria Keberhasilan
- ✅ Zero critical security vulnerabilities
- ✅ Response time API < 5 detik untuk query standar
- ✅ Backup otomatis berjalan harian
- ✅ Minimal 10 personel APH terlatih menggunakan sistem

---

## Manajemen Risiko

| Risiko | Dampak | Mitigasi |
|--------|--------|----------|
| Data hukum tidak lengkap/terbaru | Analisis tidak akurat | ALCD autonomous discovery + self-evaluation loop + continuous learning terjadwal |
| LLM hallucination | Rekomendasi pasal salah | RAG grounding + human review wajib |
| Kode AI berbahaya | Security breach | Guardrail filter + sandbox + approval wajib |
| Gangguan Ollama/host GPU | Inferensi LLM gagal | HIRO auto-fallback ke CPU, retry dengan backoff, health-check endpoint |
| Resistensi pengguna APH | Adopsi rendah | UI intuitif, training bertahap, pilot project |
| Data sensitif bocor | Pelanggaran privasi | On-premise deployment, enkripsi, access control |

---

## Dependensi Antar Fase

```
Fase 1 (Infra + ALCD Module)
  └──→ Fase 2 (Agents + RAG) — membutuhkan ALCD bootstrapped knowledge base
        └──→ Fase 3 (Graph + Sandbox) — membutuhkan agents berjalan
              └──→ Fase 4 (UI + Pilot) — membutuhkan backend lengkap
                    └──→ Fase 5 (Production) — membutuhkan pilot sukses
```

---

## Catatan

- Timeline bersifat estimasi dan dapat disesuaikan berdasarkan ketersediaan sumber daya
- Setiap fase diakhiri dengan **review meeting** sebelum lanjut ke fase berikutnya
- Dokumentasi diupdate secara inkremental sepanjang pengembangan

### Adopsi eksternal (riset GitHub/HuggingFace — Okt 2026)

Diimplementasikan pada Fase 1–2 di luar rencana awal, menutup gap yang
terukur. Detail lengkap di AGENTS.md §10:

- **Korpus HuggingFace** — `endomorphosis/ipfs_indonesia_laws` (1.924
  UU / 105K pasal JDIH BPK) dan `Azzindani/ID_Supreme_Court_Parquet`
  (22.630 putusan MA pidana terstruktur) menjadi saluran impor
  `hf://` di `external_corpus.py`. Dedupe identitas; `law_status`
  → `source_status` untuk audit temporal.
- **Gold benchmark** — `backend/scripts/eval_gold.py` mengukur
  HitRate@k/MRR terhadap `tests/gold/*.jsonl` (15 pasangan curated +
  400 QA `horelulus/ID_REG_QA_Small`). Menggantikan self-eval
  LLM-menilai-dirinya-sendiri dengan metrik pasal-gold deterministik.
- **Grounding di kode** — `_audit_citations` 3 sumbu (eksistensi,
  fidelity, temporal-anakronisme) + abstention saat bukti lemah atau
  sitasi ungrounded (pola `legal-agent`/`regulated-rag`/`policyproof`).
- **Hierarki pasal** — parser melacak BAB/Bagian/Paragraf dan
  meng-anchor path ke tiap chunk (pola `pengurai-regulasi` +
  `ID_REG_MD_RAG`).
- **Embedding configurable** — `settings.embedding_model`; jalur
  upgrade terdokumentasi ke e5-indo / BGE-M3-ind (wajib re-embed).
