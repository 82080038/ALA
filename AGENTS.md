# 🤖 Dokumentasi Sistem Multi-Agent — Autonomous Legal Agent (ALA)

> Dokumen ini menjelaskan arsitektur, peran, dan interaksi keempat agen AI yang membentuk inti dari sistem ALA, diorkestrasikan menggunakan LangGraph.

---

## 1. Ikhtisar Arsitektur Agen

ALA menggunakan **LangGraph** sebagai orchestration framework untuk menjalankan **empat agen AI** secara sekuensial dalam sebuah state machine. Agent 0 (ALCD) bootstraps the knowledge base from zero; Agents 1–3 process user queries.

```
┌─────────────────────────────────────────────────────────────────────┐
│                   LangGraph Orchestrator                            │
│        (backend/app/agents/legal_orchestrator.py)                   │
│                                                                     │
│  ┌─────────┐   ┌───────────┐   ┌──────────┐   ┌─────────────┐    │
│  │  ALCD   │──▶│ Legal     │──▶│ Internet │──▶│ Synthesis & │    │
│  │  Agent  │   │ Foundation│   │ Crawler  │   │ Developer   │    │
│  │ (Ag. 0) │   │ (Ag. 1)   │   │ (Ag. 2)  │   │ (Ag. 3)     │    │
│  └────┬────┘   └────┬──────┘   └────┬─────┘   └─────┬───────┘    │
│       │            │            │              │              │
│       ▼            ▼            ▼              ▼              │
│  knowledge_    legal_       crime_data    synthesis +       │
│  ready=true    foundation   (universal)   generated_code    │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              Shared State (ALA_State)                      │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Shared State

Semua agen berbagi satu state object yang diperbarui secara sekuensial:

```python
from typing import TypedDict, Optional

class CrimeSource(TypedDict):
    title: str
    url: str
    snippet: str
    published_date: Optional[str]

class LegalArticle(TypedDict):
    law_name: str
    article_number: str
    title: str
    content: str
    relevance_score: float

class CrossReference(TypedDict):
    from_article: str
    to_article: str
    relationship: str

class GeneratedOutput(TypedDict):
    filename: str
    language: str
    description: str
    code: str
    flowchart: str

class ALA_State(TypedDict):
    # Input
    query: str
    
    # Tenant & quota context (diisi middleware FastAPI)
    institution_id: str          # Tenant pemilik request (isolasi data operasional)
    tier_level: str              # free | premium_l1 | premium_l2
    context_token_budget: int    # num_ctx efektif: min(tier_cap, hardware_ceiling)
    
    # ALCD Agent output (Agent 0 — BOOTSTRAPS KNOWLEDGE)
    knowledge_ready: bool        # True when ALCD readiness ≥ threshold
    knowledge_score: float       # Overall knowledge score (0.0–1.0)
    ontology_coverage: dict      # Coverage per ontology node
    
    # Legal Foundation Agent output (Agent 1)
    legal_articles: list[LegalArticle]
    cross_references: list[CrossReference]
    legal_summary: str
    
    # Internet Crawler Agent output (Agent 2)
    crime_data: list[CrimeSource]
    crime_summary: str
    
    # Synthesis & Developer Agent output (Agent 3)
    synthesis: dict              # Law ↔ reality mapping
    generated_output: GeneratedOutput
    
    # Metadata
    audit_trail: list[dict]
    errors: list[str]
```

---

## 3. Agent 0: ALCD Agent (Autonomous Legal Curriculum Designer)

### Lokasi
`backend/app/agents/curriculum_designer.py` (orkestrator ALCD) dan sub-modul di `backend/app/agents/alcd/`

### Tanggung Jawab
Membangun basis pengetahuan hukum dari **NOL DATA**. Agen ini berjalan sebelum query pengguna manapun diproses. Ia secara otonom merumuskan apa yang perlu dipelajari, mencari dan mengunduh dokumen hukum dari internet, meng-embed dan membangun graph, lalu mengevaluasi dirinya sendiri.

### Input
- `query` dari state (atau core objective saat bootstrap)

### Output
- `knowledge_ready`: boolean flag — `true` jika skor pengetahuan memenuhi threshold
- `knowledge_score`: skor numerik (0.0–1.0) dari hasil self-evaluation
- `ontology_coverage`: breakdown per node ontologi

### Sub-Modul

| File | Tanggung Jawab |
|------|----------------|
| `alcd/ontology_generator.py` | Generate structured knowledge tree menggunakan LLM |
| `alcd/source_discoverer.py` | Cari repositori hukum resmi via Google Search |
| `alcd/document_parser.py` | Unduh, parse HTML/PDF, ekstrak konten terstruktur |
| `alcd/autonomous_ingestor.py` | Chunk teks, generate embedding (model via `settings.embedding_model`), simpan ke ChromaDB |
| `alcd/graph_builder.py` | Identifikasi cross-references, bangun relasi di Neo4j |
| `alcd/doctrine.py` | 21 konsep ilmu hukum berjenjang — fondasi sebelum pasal |
| `alcd/external_corpus.py` | Impor korpus terverifikasi: `spkt://` `lexisai://` `aph://` `hf://laws` `hf://putusan` |
| `bm25.py` | Indeks BM25 lokal (stopword Indonesia) — lapis leksikal hybrid retrieval |
| `evaluator.py` | Generate quiz, query RAG, skor jawaban, identifikasi gap |

> Sub-modul `alcd/*` berada di bawah `backend/app/agents/`; `evaluator.py` sudah ada di `backend/app/agents/evaluator.py`.

### Alur Kerja

```
1. Cek apakah knowledge_registry sudah terisi dan skor ≥ threshold
   → Jika YA: set knowledge_ready=true, lanjut ke Agent 1
   → Jika TIDAK: lanjut ke langkah 2
2. FASE ONTOLOGI:
   a. Kirim core objective ke LLM
   b. LLM menghasilkan structured ontology tree (kategori, sub-kategori, prioritas)
   c. Simpan setiap node di tabel ontology_nodes
3. FASE FONDASI — belajar ilmu hukum dulu sebelum membaca pasal:
   a. seed_doctrine (alcd/doctrine.py): 21 konsep berjenjang —
      pengantar ilmu hukum → sistem & sumber hukum → kodifikasi →
      perundang-undangan → pidana materiil → hukum acara → delik
      khusus → analisis perkara. LLM menulis gloss terstruktur;
      dicatat kategori 'doktrin', verified=False (bukan sumber primer)
   b. import_external_corpus (alcd/external_corpus.py): serap korpus
      yang SUDAH di-OCR/diaudit — SPKT spkt.db (~49 UU 'berlaku' +
      rujukan resolved + putusan MK), LexisAI chroma_db (amandemen
      ITE/Tipikor/KPK, KUHAP 8/1981), riset domain APH (30 dokumen
      markdown terkurasi — kategori doktrin, provenance aph://),
      HuggingFace ipfs_indonesia_laws (1.924 UU / 105K pasal JDIH
      BPK, flag law_status → source_status), dan HuggingFace
      ID_Supreme_Court_Parquet (22.630 putusan MA pidana terstruktur
      — dibatasi env HF_PUTUSAN_MAX). Idempotent via identitas
      (nomor, tahun) atau source_url; provenance
      spkt:// / lexisai:// / aph:// / hf://
4. FASE AKUISISI CRAWL (untuk setiap node ontologi — hanya celah
   yang tersisa setelah Fase 3):
   a. Formulasikan search queries untuk Google Search
   b. Prioritaskan domain terpercaya (JDIH, BPK, MA)
   c. Unduh halaman web / dokumen PDF (OCR fallback via ocrmypdf+tesseract 'ind')
   d. Parse konten: nama UU, nomor pasal, bab, subjek (klausa TENTANG), status
   e. Verifikasi: identitas sumber↔isi, subjek↔topik node, status≠dicabut
   f. Chunk teks (500 char, 50 overlap)
   g. Generate embedding (E5: 'passage: '/'query: ') → simpan ke
      ChromaDB koleksi GLOBAL `indonesian_laws` (TANPA institution_id)
   h. Identifikasi cross-references → simpan ke Neo4j graph GLOBAL
      (node LegalArticle — TANPA institution_id)
   i. Catat di knowledge_registry (GLOBAL — satu registri seluruh platform)
5. FASE EVALUASI DIRI:
   a. Skor deterministik per node (_EXPECTED_LAW_IDS) — bukan LLM judge
   b. LLM-as-judge tetap berjalan untuk self_eval_logs/deteksi gap,
      tapi TIDAK menentukan skor readiness
   c. Node < 0.7: status gap_detected
   d. Ulangi sampai skor keseluruhan ≥ 0.8
6. Set knowledge_ready=true, update state
```

### Konfigurasi

| Parameter | Default | Deskripsi |
|-----------|---------|-----------|
| `ALCD_ENABLED` | `true` | Aktifkan/nonaktifkan ALCD |
| `ALCD_MIN_READINESS_SCORE` | `0.8` | Skor minimum sebelum menerima query |
| `ALCD_SELF_EVAL_THRESHOLD` | `0.7` | Skor minimum per topik |
| `ALCD_SCHEDULE_INTERVAL` | `168h` | Interval continuous learning (default: mingguan) |
| `ALCD_MAX_CONCURRENT_CRAWLS` | `3` | Maks crawl paralel |
| `ALCD_TRUSTED_DOMAINS` | `jdih.kemenkumham.go.id,...` | Domain sumber prioritas |
| `ALCD_CRAWL_RATE_LIMIT` | `1` | Maks request/detik per domain |

### Contoh Output

```python
{
    "knowledge_ready": True,
    "knowledge_score": 0.87,
    "ontology_coverage": {
        "hukum_pidana_materiil": {"score": 0.92, "laws_ingested": 5},
        "hukum_pidana_formil": {"score": 0.88, "laws_ingested": 1},
        "regulasi_teknis": {"score": 0.79, "laws_ingested": 3},
        "yurisprudensi": {"score": 0.82, "laws_ingested": 12}
    }
}
```

### Kapan ALCD Berjalan
- **Saat startup** — bootstrap penuh jika database kosong
- **Terjadwal** — continuous learning (default: mingguan)
- **On-demand** — via `POST /api/alcd/trigger`
- **Pre-query** — readiness check sebelum setiap user query

### Batasan & Guardrails
- Rate limiting ketat: maks 1 request/detik per domain
- Hanya crawl domain publik dan resmi
- Verifikasi konten terhadap minimal 2 sumber berbeda
- Semua aktivitas dicatat di `self_eval_logs` dan `knowledge_registry`
- **Pengetahuan GLOBAL:** ALCD selalu menulis ke namespace global (ChromaDB `indonesian_laws`, Neo4j `LegalArticle`) — DILARANG membuat duplikat basis hukum per institusi

---

## 4. Agent 1: Legal Foundation Agent

### Lokasi
`backend/app/agents/legal_foundation.py`

### Tanggung Jawab
Membangun landasan hukum komprehensif yang relevan dengan query pengguna. Agen ini menguasai seluruh instrumen hukum positif Indonesia **SEBELUM** crawling internet dilakukan.

### Input
- `query` dari state (contoh: "modus pencucian uang melalui cryptocurrency")

### Output
- `legal_articles`: Pasal-pasal hukum relevan dari **seluruh UU** dengan skor relevansi
- `cross_references`: Relasi antar pasal lintas UU dari Neo4j
- `legal_summary`: Ringkasan landasan hukum dalam Bahasa Indonesia

### Teknologi
- **ChromaDB** untuk semantic search (RAG) terhadap **seluruh hukum positif** — koleksi GLOBAL `indonesian_laws` (dibagikan semua institusi, tanpa filter `institution_id`)
- **Neo4j** untuk cross-reference lookup **lintas UU** — graph GLOBAL `LegalArticle`
- **LLM lokal** — Ollama `qwen2.5:3b-instruct` via `ChatOllama` untuk analisis & sintesis hukum (instance Ollama `:11434`, terkunci ke **GPU 0**)

### Alur Kerja

```
1. Terima query dari state
2. Jalankan retrieval HIBRID (legal_foundation._rag_retrieve):
   a. Dense E5 semantic search → cosine similarity langsung
   b. BM25 leksikal (bm25.py, stopword Indonesia) — tangkap istilah
      literal yang dense-miss
   c. Reciprocal Rank Fusion + boost ≤0.008 untuk pasal yang
      historis tersitasi-terverifikasi (tabel retrieval_feedback)
   d. Boost deterministik _mention_boosts: identitas UU/Pasal yang
      disebut eksplisit di query (regex + alias KUHAP/KUHP/dsb.)
   e. Reranker cross-encoder lokal (CrossEncoder mMARCO-MiniLM,
      env RERANKER_MODEL) mengurutkan top-48 kandidat — MRR@10
      terukur 0.244→0.400; skor hanya mengatur urutan, bukan
      relevance_score (skala abstention tetap cosine dense)
   e2. Pin sitasi eksplisit: UU+Pasal yang disebut query disuntik
      ke kandidat walau absen dari dense+lex dan di-pin di atas
      reranker; primat peraturan — chunk yurisprudensi di belakang
      UU/doktrin pada query generik (UU primer, putusan persuasif)
   f. Indeks BM25 tersnapshot ke disk (BM25_INDEX_PATH) — cold-start
      tak rebuild >100K chunk; invalidate pasca-ingest; fetch
      dua-tahap (ids per-halaman → batch 4K) untuk koleksi >32K
3. Query Neo4j untuk cross-references LINTAS UU
4. ABSTENTION (pola regulated-rag/policyproof): tolak menjawab jika
   bukti lemah — nol pasal, skor teratas <0.55, atau SEMUA sitasi di
   luar set retrieval (ungrounded)
5. Generate legal_summary menggunakan LLM
6. Audit sitasi TIGA SUMBU deterministik (_audit_citations):
   a. EKSISTENSI — setiap Pasal N tersitasi harus ada di set retrieval
   b. FIDELITY — kalimat berisi sitasi harus berbagi kata-isi dengan
      bunyi pasalnya (coverage ≥34%)
   c. TEMPORAL — pasal dari UU yang berlaku SETELAH tahun peristiwa
      di query ditandai anakronisme
7. Update state
```

### Konfigurasi

| Parameter | Default | Deskripsi |
|-----------|---------|-----------|
| `top_k_results` | 15 | Jumlah chunk teratas dari ChromaDB |
| `min_relevance_score` | 0.5 | Skor minimum untuk dimasukkan |
| `cross_ref_depth` | 3 | Kedalaman cross-reference di Neo4j |
| `collection_name` | `indonesian_laws` | Nama koleksi ChromaDB |
| `include_kuhap_validation` | `true` | Validasi terhadap hukum acara |

### Contoh Output

```python
{
    "legal_articles": [
        {
            "law_name": "UU TPPU",
            "article_number": "Pasal 3",
            "title": "Pencucian Uang",
            "content": "Setiap Orang yang menempatkan, mentransfer... harta kekayaan yang diketahuinya atau patut diduganya merupakan hasil tindak pidana...",
            "relevance_score": 0.96
        },
        {
            "law_name": "UU ITE",
            "article_number": "Pasal 30",
            "title": "Akses Ilegal",
            "content": "Setiap Orang dengan sengaja dan tanpa hak...",
            "relevance_score": 0.88
        },
        {
            "law_name": "KUHP",
            "article_number": "Pasal 55",
            "title": "Penyertaan (Deelneming)",
            "content": "...",
            "relevance_score": 0.81
        },
        {
            "law_name": "KUHAP",
            "article_number": "Pasal 184",
            "title": "Alat Bukti yang Sah",
            "content": "...",
            "relevance_score": 0.75
        }
    ],
    "cross_references": [
        {
            "from_article": "UU TPPU Pasal 3",
            "to_article": "KUHP Pasal 55",
            "relationship": "CROSS_REFERENCES"
        },
        {
            "from_article": "UU TPPU Pasal 3",
            "to_article": "UU ITE Pasal 30",
            "relationship": "CROSS_REFERENCES"
        },
        {
            "from_article": "UU TPPU Pasal 3",
            "to_article": "KUHAP Pasal 184",
            "relationship": "PROCEDURAL_BASIS"
        }
    ],
    "legal_summary": "Berdasarkan analisis, modus pencucian uang via cryptocurrency dapat dijerat dengan: (1) Pasal 3 UU TPPU tentang pencucian uang; (2) Pasal 30 UU ITE tentang akses ilegal; (3) Pasal 55 KUHP tentang penyertaan. Prosedur penanganan harus mengikuti KUHAP Pasal 184 tentang alat bukti yang sah, termasuk bukti elektronik."
}
```

### Batasan & Guardrails
- Hanya menggunakan sumber hukum yang telah di-ingest ke ChromaDB (koleksi GLOBAL `indonesian_laws`)
- Cross-references harus terverifikasi di Neo4j graph
- Validasi KUHAP wajib untuk setiap analisis
- Query pengetahuan hukum **TIDAK** difilter `institution_id` (global); filter tenant hanya berlaku saat mengakses data operasional (cases, entity graph nodes)

---

## 5. Agent 2: Internet Crawler Agent

### Lokasi
`backend/app/agents/internet_crawler.py`

### Tanggung Jawab
Mencari dan mengekstrak informasi tren kejahatan **dari segala kategori** berdasarkan konteks hukum yang telah dibangun oleh Legal Foundation Agent.

### Input
- `query` dari state
- `legal_articles` dan `legal_summary` dari Legal Foundation Agent (untuk kontekstualisasi)

### Output
- `crime_data`: List sumber web yang ditemukan (universal, bukan hanya siber)
- `crime_summary`: Ringkasan tren kejahatan dalam Bahasa Indonesia

### Teknologi
- **Google Search API** / Google Custom Search
- **Playwright** (Python) untuk headless browser crawling (handles JS-heavy sites)
- **BeautifulSoup4** untuk HTML parsing (post-render extraction)

### Cakupan Kejahatan (Universal)

| Kategori | Contoh |
|----------|--------|
| **Pidana Umum** | Pembunuhan, pencurian, penipuan, penganiayaan |
| **Korupsi** | Suap, gratifikasi, penyalahgunaan wewenang |
| **Narkotika** | Peredaran gelap, sindikat internasional, new psychoactive substances |
| **TPPU** | Pencucian uang via crypto, shell company, smurfing |
| **Kejahatan Siber** | Phishing, ransomware, identity theft, carding |
| **Kejahatan Transnasional** | Human trafficking, arms dealing, terorisme |
| **Kejahatan Finansial** | Investasi bodong, skema Ponzi, market manipulation |

### Alur Kerja

```
1. Terima query + legal_context dari state
2. Formulasikan search queries (query asli + variasi berdasarkan legal context)
3. Jalankan Google Search untuk setiap query
4. Untuk setiap hasil:
   a. Fetch halaman web menggunakan Playwright headless browser
   b. Parse rendered HTML dengan BeautifulSoup
   c. Ekstrak judul, konten, tanggal publikasi
   d. Filter berdasarkan relevansi
5. Compile hasil ke crime_data
6. Generate crime_summary menggunakan LLM
7. Update state
```

### Konfigurasi

| Parameter | Default | Deskripsi |
|-----------|---------|-----------|
| `max_search_results` | 10 | Maks hasil Google Search per query |
| `max_pages_to_crawl` | 5 | Maks halaman web yang di-crawl |
| `search_language` | `id` | Bahasa pencarian (Indonesia) |
| `search_country` | `countryID` | Filter negara |
| `timeout_seconds` | 10 | Timeout per HTTP request |
| `include_judicial_sources` | `true` | Sertakan situs JDIH, Putusan MA, berita hukum |

### Contoh Output

```python
{
    "crime_data": [
        {
            "title": "KPK Ungkap Modus Baru Pencucian Uang via Aset Kripto",
            "url": "https://example.com/article-1",
            "snippet": "Komisi Pemberantasan Korupsi mengungkap skema pencucian uang hasil korupsi yang menggunakan aset kripto lintas negara...",
            "published_date": "2026-09-20"
        },
        {
            "title": "BNN: Sindikat Narkotika Internasional Manfaatkan Darknet",
            "url": "https://example.com/article-2",
            "snippet": "Badan Narkotika Nasional berhasil membongkar jaringan peredaran narkotika yang memanfaatkan darknet dan pembayaran cryptocurrency...",
            "published_date": "2026-09-18"
        },
        {
            "title": "Putusan MA: Bukti Elektronik Sah dalam Kasus Penipuan Online",
            "url": "https://example.com/article-3",
            "snippet": "Mahkamah Agung memperkuat putusan pengadilan tinggi yang menerima bukti elektronik...",
            "published_date": "2026-09-15"
        }
    ],
    "crime_summary": "Tren terbaru menunjukkan konvergensi berbagai jenis kejahatan: pencucian uang hasil korupsi via cryptocurrency, sindikat narkotika internasional yang memanfaatkan teknologi darknet, dan penguatan yurisprudensi MA terkait bukti elektronik dalam kasus pidana."
}
```

### Batasan & Guardrails
- Hanya crawl domain publik (tidak ada dark web)
- Rate limiting: maksimal 1 request per detik
- Timeout keras 10 detik per halaman
- Tidak menyimpan cookies atau session data
- Prioritaskan sumber resmi: JDIH, situs pemerintah, media berita terpercaya

---

## 6. Agent 3: Synthesis & Developer Agent

### Lokasi
`backend/app/agents/code_generator.py`

### Tanggung Jawab
Menghubungkan landasan hukum dengan tren kejahatan riil, mengidentifikasi celah regulasi atau strategi penindakan, lalu menghasilkan kode Python utilitas dan flowchart visual. Semua output **divalidasi terhadap KUHAP** agar tidak melanggar prosedur hukum acara.

### Input
- `legal_articles`, `cross_references`, `legal_summary` dari Legal Foundation Agent
- `crime_data`, `crime_summary` dari Internet Crawler Agent

### Output
- `generated_output`: Objek berisi kode, nama file, deskripsi, dan flowchart

### Teknologi
- **LLM lokal** — Ollama `qwen2.5-coder:3b` via `ChatOllama` untuk code generation (instance Ollama `:11435`, terkunci ke **GPU 1**)
- **Mermaid.js** format untuk flowcharts

### Alur Kerja

```
1. Terima seluruh konteks dari state (hukum + tren kejahatan)
2. Fase Sintesis:
   a. Hubungkan pasal hukum dengan modus operandi baru
   b. Identifikasi celah regulasi (loophole) jika ada
   c. Rumuskan strategi penindakan berbasis hukum
   d. Validasi strategi terhadap KUHAP (hukum acara)
3. Fase Generasi Kode:
   a. Tentukan use case (parser, extractor, analyzer, report generator)
   b. Generate code menggunakan LLM
   c. Suntikkan Chain-of-Custody scaffold (WAJIB jika kode menyentuh file bukti):
      - File bukti dibuka READ-ONLY (mode "rb" — dilarang "w"/"a"/"r+"/"w+")
      - Hitung & log SHA-256 file target SEBELUM pemrosesan
      - Hitung & log SHA-256 file target SESUDAH pemrosesan
      - Kedua hash harus identik → cetak custody record ke stdout + audit log
   d. Jalankan syntax check (ast.parse)
   e. Generate docstring dan comments
4. Fase Generasi Flowchart:
   a. Identifikasi langkah-langkah workflow
   b. Generate diagram dalam format Mermaid
5. Update state dengan synthesis + generated_output
```

### Tipe Kode yang Digenerate

| Tipe | Deskripsi | Contoh Use Case |
|------|-----------|----------------|
| **Log Parser** | Parsing file log untuk ekstraksi data | Parse access logs, phone records, bank statements |
| **Regex Extractor** | Ekstraksi pola dari teks | Ekstrak IP, URL, email, NPWP, nomor rekening |
| **Data Analyzer** | Analisis statistik sederhana | Hitung frekuensi transaksi mencurigakan, pattern detection |
| **Report Generator** | Generate laporan terstruktur | Format temuan investigasi ke PDF-ready text |
| **Network Mapper** | Visualisasi koneksi | Map money trail, communication networks, entity relationships |
| **Pasal Matcher** | Pencocokan otomatis pasal | Cocokkan modus operandi dengan pasal hukum yang tepat |
| **Timeline Builder** | Rekonstruksi kronologi | Bangun timeline kejadian dari berbagai sumber data |

### Contoh Output

```python
{
    "generated_output": {
        "filename": "apk_log_parser.py",
        "language": "python",
        "description": "Script untuk parsing log instalasi APK dari device forensics. Mengekstrak nama package, timestamp, source URL, dan permissions yang diminta.",
        "code": '''import re
import json
import hashlib
from datetime import datetime

def sha256_file(path: str) -> str:
    """Hitung checksum SHA-256 file bukti (chain of custody KUHAP)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:               # READ-ONLY — bukti tidak pernah ditulis
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def parse_apk_install_log(log_file_path: str) -> list[dict]:
    """
    Parse log instalasi APK dan ekstrak informasi relevan.
    
    Args:
        log_file_path: Path ke file log (dibuka READ-ONLY)
        
    Returns:
        List dictionary berisi info instalasi APK
    """
    pattern = r"(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}).*?Installing APK: (\\S+).*?from: (\\S+)"
    
    results = []
    with open(log_file_path, "rb") as f:      # READ-ONLY — integritas bukti dijaga
        for raw in f:
            line = raw.decode("utf-8", errors="replace")
            match = re.search(pattern, line)
            if match:
                results.append({
                    "timestamp": match.group(1),
                    "package_name": match.group(2),
                    "source_url": match.group(3),
                    "suspicious": is_suspicious(match.group(2))
                })
    return results

def is_suspicious(package_name: str) -> bool:
    """Cek apakah nama package mencurigakan."""
    suspicious_patterns = [
        r".*\\.apk$",
        r"com\\.bank\\..*fake",
        r".*undangan.*",
        r".*tagihan.*"
    ]
    return any(re.match(p, package_name) for p in suspicious_patterns)

if __name__ == "__main__":
    import sys
    evidence_path = sys.argv[1]

    # --- Chain of Custody (WAJIB — kepatuhan KUHAP) ---
    sha256_before = sha256_file(evidence_path)
    results = parse_apk_install_log(evidence_path)
    sha256_after = sha256_file(evidence_path)

    print(json.dumps({
        "custody": {
            "evidence_file": evidence_path,
            "sha256_before": sha256_before,
            "sha256_after": sha256_after,
            "integrity": "VERIFIED" if sha256_before == sha256_after else "VIOLATED"
        },
        "results": results
    }, indent=2))
''',
        "flowchart": """graph TD
    A[Input: Device Log File] --> B[Read Log Line by Line]
    B --> C{Match APK Install Pattern?}
    C -->|Yes| D[Extract Timestamp, Package, Source]
    C -->|No| B
    D --> E{Is Package Suspicious?}
    E -->|Yes| F[Flag as Suspicious]
    E -->|No| G[Mark as Normal]
    F --> H[Add to Results]
    G --> H
    H --> I{More Lines?}
    I -->|Yes| B
    I -->|No| J[Output JSON Report]
"""
    }
}
```

### Guardrails Kode

Sebelum output dikembalikan, Developer Agent menjalankan pemeriksaan:

1. **Syntax Check** — `ast.parse()` untuk memastikan kode valid
2. **Blacklist Pattern Scan** — Cek pola berbahaya (lihat SECURITY.md)
3. **Import Whitelist** — Hanya library yang di-whitelist diperbolehkan (`hashlib` WAJIB tersedia untuk checksum)
4. **No Network Calls** — Kode tidak boleh melakukan HTTP requests
5. **No File System Writes** — Kode hanya boleh membaca, tidak menulis ke path sensitif
6. **Evidence Read-Only (KUHAP)** — Setiap skrip yang mem-parse/mengekstrak/menganalisis file bukti **WAJIB** membukanya read-only (`"rb"`); mode tulis pada path bukti ditolak
7. **Chain-of-Custody SHA-256** — Kode WAJIB menghitung dan mencetak checksum SHA-256 file target **sebelum** dan **sesudah** pemrosesan; hasil dicatat ke `ai_audit_logs.evidence_sha256_before/after`. Kode tanpa scaffold checksum pada file bukti ditolak guardrail
8. **Tenant Storage** — Skrip kustom yang dihasilkan disimpan sebagai data operasional tenant (`institution_id` wajib); tidak terlihat lintas institusi

---

## 7. Orkestrasi LangGraph

### Graph Definition

```python
from langgraph.graph import StateGraph, END

def build_ala_graph():
    workflow = StateGraph(ALA_State)
    
    # Add nodes (ALCD + LAW-FIRST order)
    workflow.add_node("alcd", alcd_agent)
    workflow.add_node("legal_foundation", legal_foundation_agent)
    workflow.add_node("crawler", crawler_agent)
    workflow.add_node("synthesis_developer", synthesis_developer_agent)
    
    # Define edges — ALCD bootstraps first, then law-first pipeline
    workflow.set_entry_point("alcd")
    workflow.add_edge("alcd", "legal_foundation")
    workflow.add_edge("legal_foundation", "crawler")
    workflow.add_edge("crawler", "synthesis_developer")
    workflow.add_edge("synthesis_developer", END)
    
    return workflow.compile()
```

### Execution

```python
graph = build_ala_graph()

result = graph.invoke({
    "query": "modus pencucian uang melalui cryptocurrency",
    "institution_id": "uuid-institusi",      # dari tenant_context middleware
    "tier_level": "premium_l1",
    "context_token_budget": 8192,            # min(tier_cap, hardware_ceiling)
    "knowledge_ready": False,
    "knowledge_score": 0.0,
    "ontology_coverage": {},
    "legal_articles": [],
    "cross_references": [],
    "legal_summary": "",
    "crime_data": [],
    "crime_summary": "",
    "synthesis": {},
    "generated_output": {},
    "audit_trail": [],
    "errors": []
})
```

### Error Handling

Setiap agen memiliki try-except wrapper:

```python
def crawler_agent(state: ALA_State) -> ALA_State:
    try:
        # ... agent logic ...
        state["audit_trail"].append({
            "agent": "crawler",
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        state["errors"].append(f"Crawler Agent error: {str(e)}")
        state["audit_trail"].append({
            "agent": "crawler",
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    return state
```

---

## 8. Konfigurasi LLM Provider

### Provider: Ollama Lokal (akselerasi GPU CUDA di host — dual-instance)

Semua inferensi LLM berjalan **lokal** via Ollama — tidak ada panggilan API cloud. Dua instance Ollama berjalan di host dengan **GPU pinning eksklusif**: instance `:11434` terkunci ke GPU 0 (`CUDA_VISIBLE_DEVICES=0`) melayani `qwen2.5:3b-instruct`, instance `:11435` terkunci ke GPU 1 (`CUDA_VISIBLE_DEVICES=1`) melayani `qwen2.5-coder:3b`. Implementasi di `backend/app/config.py`:

```python
from langchain_ollama import ChatOllama

# Model penalaran hukum (Agen 0–2: ALCD, Fondasi Hukum, Penjelajah Internet)
# Instance Ollama #1 — TERKUNCI ke GPU 0
llm_reasoning = ChatOllama(
    model="qwen2.5:3b-instruct",
    base_url=hw.ollama_reasoning_url,  # http://host.docker.internal:11434 (GPU 0)
    temperature=0.2,
    num_ctx=min(tier_ctx_cap, hw.ollama_num_ctx),   # token tiering + ceiling VRAM
    num_predict=min(tier_predict_cap, hw.ollama_num_predict),
)

# Model pembuatan kode (Agen 3: Sintesis & Pengembang)
# Instance Ollama #2 — TERKUNCI ke GPU 1
llm_coder = ChatOllama(
    model="qwen2.5-coder:3b",
    base_url=hw.ollama_coder_url,      # http://host.docker.internal:11435 (GPU 1)
    temperature=0.1,
    num_ctx=min(tier_ctx_cap, hw.ollama_num_ctx),
    num_predict=min(tier_predict_cap, hw.ollama_num_predict),
)
```

### Strategy

| Aspek | Konfigurasi |
|-------|-------------|
| **Penalaran** | Ollama `qwen2.5:3b-instruct` (Agen 0–2) — instance `:11434` |
| **Codegen** | Ollama `qwen2.5-coder:3b` (Agen 3) — instance `:11435` |
| **GPU Pinning** | Reasoning → GPU 0 (`CUDA_VISIBLE_DEVICES=0`); Coder → GPU 1 (`CUDA_VISIBLE_DEVICES=1`). `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1` per instance — anti-OOM |
| **Token Tiering** | `num_ctx` per query diklamp `tier_level`: `free`=2.048, `premium_l1`=8.192, `premium_l2`=16.384 — selalu ≤ ceiling hardware HIRO |
| **Fallback** | Mode CPU / instance tunggal jika GPU 1 tidak tersedia (HIRO otomatis) |
| **Temperature** | 0.2 reasoning / 0.1 coder (rendah, untuk konsistensi) |
| **Retry** | 3x dengan exponential backoff |
| **Timeout** | 60 detik per request |
| **Batasan VRAM** | Maks model 3B parameter (Q4) — GPU 2× GTX 1050 Ti 4 GB, satu model per GPU |

---

## 9. Monitoring & Logging

Setiap eksekusi agent pipeline menghasilkan audit trail lengkap:

```json
{
  "pipeline_id": "uuid-v4",
  "started_at": "2026-10-07T14:05:00Z",
  "completed_at": "2026-10-07T14:05:45Z",
  "total_duration_ms": 45000,
  "agents": [
    {
      "name": "alcd",
      "status": "success",
      "duration_ms": 0,
      "knowledge_ready": true,
      "knowledge_score": 0.87,
      "note": "Knowledge base already bootstrapped; readiness check passed"
    },
    {
      "name": "legal_foundation",
      "status": "success",
      "duration_ms": 8000,
      "articles_found": 7,
      "laws_covered": ["UU TPPU", "UU ITE", "KUHP", "KUHAP"]
    },
    {
      "name": "crawler",
      "status": "success",
      "duration_ms": 15000,
      "items_processed": 5,
      "crime_categories": ["TPPU", "Cyber Crime", "Korupsi"]
    },
    {
      "name": "synthesis_developer",
      "status": "success",
      "duration_ms": 22000,
      "code_lines": 65,
      "kuhap_validated": true
    }
  ],
  "errors": []
}
```

---

## Lampiran: Menjalankan ALA secara Native (tanpa Docker)

Jika daemon Docker tidak tersedia, seluruh stack dapat berjalan native:

```bash
# 1. PostgreSQL — cluster milik user (port 5432, socket di /tmp)
/usr/lib/postgresql/16/bin/initdb -D .pgdata -E UTF8 \
    --auth-local=trust --auth-host=scram-sha-256
/usr/lib/postgresql/16/bin/pg_ctl -D .pgdata -l /tmp/ala-pg.log \
    -o "-p 5432 -k /tmp" start
psql -h /tmp -p 5432 -U $USER -d postgres -c \
    "CREATE USER ala_user WITH PASSWORD '<POSTGRES_PASSWORD>' SUPERUSER;
     CREATE DATABASE ala_db OWNER ala_user;"

# 2. Skema DB (membuat role ala_app + RLS)
cd backend && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
APP_DB_PASSWORD=<pass> \
DATABASE_ADMIN_URL=postgresql://ala_user:<pass>@localhost:5432/ala_db \
./.venv/bin/python scripts/init_db.py

# 3. ChromaDB server (port 8001) & Neo4j 5 community tarball (port 7687)
./.venv/bin/chroma run --host 127.0.0.1 --port 8001 --path ../.chroma &
#   Neo4j: unduh dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz → .neo4j/
#   ./bin/neo4j-admin dbms set-initial-password <NEO4J_PASSWORD>
#   ./bin/neo4j start

# 4. Backend FastAPI (port 8080 — sesuai default NEXT_PUBLIC_API_URL FE)
cd backend && PYTHONDONTWRITEBYTECODE=1 \
DATABASE_URL=postgresql://ala_app:<pass>@localhost:5432/ala_db \
CHROMADB_HOST=127.0.0.1 CHROMADB_PORT=8001 \
NEO4J_URI=bolt://localhost:7687 \
OLLAMA_BASE_URL=http://localhost:11434 \
OLLAMA_REASONING_URL=http://localhost:11434 \
OLLAMA_CODER_URL=http://localhost:11434 \
./.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080

# 5. Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Catatan: tanpa Docker, eksekusi sandbox kode AI (`/approve-workflow`)
terdegradasi graceful — mengembalikan `Docker tidak tersedia`, pipeline
lain tetap berfungsi.

# 6. Sandbox — Rootless Docker (tanpa sudo; user tidak perlu grup docker)
# Permanen via systemd --user (sudah terpasang):
dockerd-rootless-setuptool.sh install   # membuat ~/.config/systemd/user/docker.service
systemctl --user enable --now docker
loginctl enable-linger petrick          # auto-start saat boot tanpa login
export DOCKER_HOST=unix:///run/user/1000/docker.sock
docker build -t ala-sandbox:latest sandbox/   # image eksekusi wajib ada
# Backend mendapat DOCKER_HOST dari backend/.env.runtime (chmod 600,
# digenerate dari .env — berisi DATABASE_URL, NEO4J_*, OLLAMA_*, dsb).

# 7. Menjalankan SELURUH stack permanen (systemd --user, auto-start boot)
systemctl --user enable --now ala-postgres ala-chroma ala-neo4j ala-api ala-frontend docker
# Unit ada di ~/.config/systemd/user/ ; dependency ordering sudah diatur
# (api menunggu postgres+chroma+neo4j+docker, frontend menunggu api).
# Status/log:  systemctl --user status ala-api ; journalctl --user -u ala-api -f
# Restart:     systemctl --user restart ala-api
# Nonaktif:    systemctl --user disable --now ala-frontend (dst.)

# 8. Korpus & embedding
# Parser memotong bagian PENJELASAN agar pasal normatif tidak tertimpa.
# Embedding: intfloat/multilingual-e5-small — prefix "query:"/"passage:"
# wajib (spec E5); skor relevansi = cosine, threshold 0.75.
# TIDAK ada skrip seed manual — korpus murni dibangun ALCD (NOL data).
# Catatan: KUHP UU 1/2023 (berlaku 2026) — pencurian di Pasal 476.

# 9. Akuisisi ALCD otonom (dari NOL — sesuai PLAN.md Fase 1)
# Pipeline: ontologi → _plan_laws (LLM menalar NAMA UU per node) →
# find_law (portal BPK memberi identitas nomor/tahun via URL) → parse →
# _verify_law (silang identitas sumber ↔ blok judul dokumen) →
# _subject_match (kata khas node cocok law_subject/klausa TENTANG — isi
# pasal TIDAK dipakai; judul rencana halusinasi tak bisa menarik dokumen
# asing ke node kanonik) → ingest. Dokumen tanpa identitas/subjek cocok
# DITOLAK. Label law_name = identitas+subjek dokumen (bukan judul LLM).
# BPK /Details/<record_id> ≠ /Download/<file_id> — parser memilih link
# unduhan yang identitas filename-nya cocok slug halaman.
# Evaluasi DETERMINISTIK (_EXPECTED_LAW_IDS + registry) menggerakkan
# readiness; LLM-as-judge hanya ke self_eval_logs (pernah rubber-stamp
# 0.977 pada korpus salah). _BOOTSTRAP_LOCK: satu bootstrap per proses,
# dibagi job /alcd/trigger & node alcd di pipeline analyze.
# Batasan diketahui: PDF scan tanpa text-layer di blok judul → identitas
# tak terbaca → ditolak (gap tercatat; butuh OCR untuk menutup).
# Registry dedup by source_url — bootstrap aman diulang (idempotent).

# 10. Adopsi eksternal (riset GitHub/HuggingFace — Okt 2026)

# Sumber korpus baru (external_corpus.py):
#   aph://  — 30 dokumen riset domain APH terkurasi (kategori doktrin;
#             BUKAN pasal primer — jangan disitasi sebagai UU)
#   hf://laws — endomorphosis/ipfs_indonesia_laws: 1.924 UU / 105.645
#             pasal dari JDIH BPK (parquet, butuh pyarrow). Dedupe
#             identitas (nomor,tahun); law_status → source_status
#             ('berlaku' vs non-current) untuk audit temporal.
#             Prioritas: UU pidana/acara/APH dulu (_HF_APH_PRIORITY).
#             Env: HF_CORPUS_DIR (cache parquet), HF_IMPORT_MAX_LAWS.
#   hf://putusan — Azzindani/ID_Supreme_Court_Parquet: 22.630 putusan
#             MA pidana terstruktur (kepala/dakwaan/fakta/amar).
#             Env HF_PUTUSAN_MAX (default 2000; ≤0 = nonaktif).
#             Kategori yurisprudensi — mengisi node yang tadinya tipis.

# Evaluasi gold (scripts/eval_gold.py):
#   .venv/bin/python scripts/eval_gold.py --k 10 [--match curated]
#   Gold set: tests/gold/ala_curated.jsonl (15 pasangan Q→pasal yang
#   dipetakan manual ke UU teregistrasi) + tests/gold/id_reg_qa.jsonl
#   (400 QA dari horelulus/ID_REG_QA_Small). Metrik: coverage,
#   HitRate@k, MRR. Progres terukur (korpus ~160 dok): baseline 0.20 →
#   +mention-boost 0.467 HitRate → +reranker MRR 0.244→0.400.
#   Setelah 2.000 putusan masuk (korpus ~2.155 dok / ~117K chunk):
#   HitRate 0.400, MRR 0.367 — primat peraturan menahan banjir
#   putusan; recall sisanya gap coverage, bukan ranking.

# Grounding & abstention (legal_foundation.py):
#   _audit_citations kini 3 sumbu — eksistensi, fidelity, TEMPORAL
#   (UU lebih muda dari tahun peristiwa di query → anakronisme).
#   Abstention: nol pasal / top_score<0.55 / semua sitasi ungrounded →
#   jawaban diganti pesan ⌀ ABSTAIN (audit['abstained'] mencatat alasan).

# Parser hierarki (document_parser.py):
#   BAB/Bagian/Paragraf dilacak per posisi; setiap pasal membawa
#   'hierarchy' ("BAB II · Bagian Kesatu") yang di-anchor ke awal
#   content chunk — pasal tak terpisah dari konteks strukturnya.

# Embedding via konfigurasi:
#   settings.embedding_model (env EMBEDDING_MODEL). Ganti model →
#   ruang vektor berubah → WAJIB kosongkan koleksi + re-embed ulang.
#   Jalur upgrade terdokumentasi: LazarusNLP/all-indo-e5-small-v4
#   (384-dim drop-in, khusus Indonesia) lalu BGE-M3-ind (dense+sparse).

# Ketergantungan baru: pyarrow (baca parquet HF) — ada di requirements.
