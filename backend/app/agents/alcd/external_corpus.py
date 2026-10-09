"""
External Corpus Importer — sumber pengetahuan yang SUDAH terverifikasi.

Menyerap korpus yang telah di-OCR, diparse, dan diaudit oleh proyek lain:

- **SPKT** (`database/spkt.db`, SQLite): 7.600+ pasal lintas ~49 UU
  "berlaku" (KUHP 1/2023, KUHAP 20/2025, ITE, Tipikor, TPPU, Narkotika,
  TPPO, KDRT, TPKS, Anak, Terorisme, dst.), 11.000+ rujukan antar-pasal
  yang sudah ter-resolve, dan putusan MK. Struktur Bersih:
  uu(nomor/tahun/judul/status) + pasal(nomor/judul/bunyi).
- **LexisAI** (`chroma_db/`, koleksi `lexisai_legal`): 14.600 chunk
  per-pasal dengan metadata nomor_uu/tahun_uu/tentang — termasuk
  dokumen yang tidak ada di SPKT (UU 8/1981 KUHAP lama, amandemen
  ITE 19/2016 & 1/2024, Tipikor 20/2001, KPK 19/2019, dst.). Isinya
  di-embed ULANG dengan E5 (model embedding mereka beda ruang vektor).

Kedua sumber diperlakukan sebagai saluran akuisisi terverifikasi
(sudah melewati kurasi proyek asal) — bukan "seed": setiap dokumen
tetap masuk lewat pipeline ingest → registry → graph yang sama,
- **APH** (`/home/petrick/projects/APH/*.md`): 30 dokumen riset domain
  yang dikurasi manusia — alur SPP per lembaga, nomenklatur kanonik
  (LP/SPDP/P-16..P-48), state machine perkara, pustaka pasal berversi,
  matriks pertanyaan uji, changelog regulasi. Pengetahuan aplikatif
  (bukan teks primer) — kategori `doktrin`, provenance `aph://`.
- **HuggingFace `ipfs_indonesia_laws`** (`hf://laws`): 1.924 UU /
  105.645 pasal dari JDIH BPK (parquet terstruktur, URL BPK kanonik,
  flag `law_status` current/non-current). Ini saluran primer massal —
  coverage nasional jauh melampaui hasil crawling.
- **HuggingFace `ID_Supreme_Court_Parquet`** (`hf://putusan`): 22.630
  putusan Mahkamah Agung pidana (khusus+umum) yang sudah terstruktur
  per seksi (kepala_putusan, dakwaan, fakta, amar_putusan, dst.) —
  mengisi node yurisprudensi yang selama ini tipis.

Semua sumber diperlakukan sebagai saluran akuisisi terverifikasi
(sudah melewati kurasi proyek asal) — bukan "seed": setiap dokumen
tetap masuk lewat pipeline ingest → registry → graph yang sama,
dengan provenance `spkt://` / `lexisai://` / `aph://` / `hf://` yang
dapat diaudit. Dokumen berstatus `dicabut`/`eksternal` di SPKT dilewati
(temporalitas); UU HF tetap masuk walau non-current — flag status
disimpan untuk audit temporal.
"""
import glob
import logging
import os
import re
import sqlite3

logger = logging.getLogger("ala.alcd.external")

_SPKT_DB = os.environ.get(
    "SPKT_DB_PATH", "/home/petrick/projects/spkt/database/spkt.db")
_LEXISAI_DB = os.environ.get(
    "LEXISAI_CHROMA_PATH", "/home/petrick/projects/LexisAI/chroma_db")
_LEXISAI_COL = "lexisai_legal"
_APH_DOCS = os.environ.get(
    "APH_DOCS_PATH", "/home/petrick/projects/APH")
_HF_DIR = os.environ.get(
    "HF_CORPUS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "..", "data", "hf"))
_HF_LAWS_DS = "endomorphosis/ipfs_indonesia_laws"
_HF_PUTUSAN_DS = "Azzindani/ID_Supreme_Court_Parquet"
# 0 = semua; set env untuk membatasi impor bertahap.
_HF_MAX_LAWS = int(os.environ.get("HF_IMPORT_MAX_LAWS", "0"))
_HF_MAX_PUTUSAN = int(os.environ.get("HF_PUTUSAN_MAX", "2000"))

# Urutan prioritas — UU kanonik APH dulu agar wilayah otak terisi cepat;
# sisanya mengikuti.
_SPKT_PRIORITY = [
    "KUHP2023", "KUHAP2025", "ITE", "TIPIKOR", "TPPU", "NARKOTIKA",
    "TPPO", "KDRT", "TPKS", "ANAK", "TERORISME", "PPPT", "POLRI",
    "KEJAKSAAN", "KPK", "MILITER", "HAM", "PDP", "OJK", "PASARMODAL",
]


def _law_category(kode: str) -> str:
    if "KUHAP" in kode or kode == "MILITER":
        return "formil"
    if kode.startswith("PUTUSAN"):
        return "yurisprudensi"
    if kode in {"POLRI", "KEJAKSAAN", "KPK", "HPP", "PEMILU", "LAMBANG"}:
        return "regulasi"
    return "materiil"


def _spkt_documents():
    """Generator dokumen terparse dari spkt.db — yield dict siap
    `ingest_parsed_document`. Hanya UU status 'berlaku'."""
    if not os.path.exists(_SPKT_DB):
        logger.info("spkt.db tidak ditemukan di %s — dilewati", _SPKT_DB)
        return
    db = sqlite3.connect(_SPKT_DB)
    try:
        uus = db.execute(
            "SELECT id, kode, judul, nomor, tahun FROM uu "
            "WHERE status = 'berlaku'").fetchall()
        rank = {k: i for i, k in enumerate(_SPKT_PRIORITY)}
        uus.sort(key=lambda r: (rank.get(r[1], 999), r[1]))
        for uid, kode, judul, nomor, tahun in uus:
            rows = db.execute(
                "SELECT nomor, judul, bunyi FROM pasal WHERE uu_id = ? "
                "ORDER BY id", (uid,)).fetchall()
            articles = [
                {"article_number": f"Pasal {n}",
                 "title": j or "",
                 "content": (b or "").strip()}
                for n, j, b in rows if (b or "").strip()
            ]
            if len(articles) < 3:
                continue
            yield {
                "law_name": f"UU Nomor {nomor} Tahun {tahun} "
                            f"tentang {judul}",
                "law_number": str(nomor),
                "law_year": str(tahun),
                "law_subject": judul,
                "articles": articles,
                "chapter_count": 0,
                "source_url": f"spkt://database/spkt.db#{kode}",
                "source_status": "berlaku",
                "_kode": kode,
            }
    finally:
        db.close()


def _lexisai_documents(known_ids: set[tuple[str, str]]):
    """Generator dokumen dari chroma_db LexisAI untuk identitas UU yang
    BELUM ada di registry (dedupe berbasis (nomor, tahun))."""
    if not os.path.exists(_LEXISAI_DB):
        logger.info("chroma_db LexisAI tidak ditemukan — dilewati")
        return
    try:
        import chromadb
        client = chromadb.PersistentClient(_LEXISAI_DB)
        col = client.get_collection(_LEXISAI_COL)
        got = col.get(include=["metadatas", "documents"])
    except Exception as exc:
        logger.warning("LexisAI chroma tak terbaca: %s", exc)
        return
    groups: dict[tuple[str, str], dict] = {}
    for meta, doc in zip(got["metadatas"], got["documents"]):
        if not meta or not doc:
            continue
        num, year = str(meta.get("nomor_uu") or ""), str(meta.get("tahun_uu") or "")
        if not num or not year or (num.lstrip("0"), year) in known_ids:
            continue
        g = groups.setdefault(
            (num, year),
            {"tentang": meta.get("tentang") or "", "articles": {}})
        pno = str(meta.get("pasal") or "0")
        g["articles"][pno] = doc
    for (num, year), g in groups.items():
        def _key(p):
            try:
                return (0, int("".join(c for c in p if c.isdigit())), p)
            except ValueError:
                return (1, 0, p)
        articles = [
            {"article_number": f"Pasal {p}", "title": "", "content": t}
            for p, t in sorted(g["articles"].items(), key=lambda kv: _key(kv[0]))
        ]
        if len(articles) < 3:
            continue
        subject = g["tentang"].replace("-", " ").replace("_", " ")
        yield {
            "law_name": f"UU Nomor {num} Tahun {year} tentang {subject}",
            "law_number": num.lstrip("0") or num,
            "law_year": year,
            "law_subject": subject,
            "articles": articles,
            "chapter_count": 0,
            "source_url": f"lexisai://chroma_db#uu-{num}-{year}",
            "source_status": "berlaku",
            "_kode": f"LEX-{num}-{year}",
        }


def _import_spkt_rujukan(law_map: dict[int, str]) -> int:
    """Bangun edge CROSS_REFERENCES di Neo4j dari tabel `rujukan` SPKT
    (sudah ter-resolve target_pasal_id-nya) — jauh lebih akurat daripada
    regex ulang atas teks."""
    if not os.path.exists(_SPKT_DB):
        return 0
    from app.database.neo4j import get_neo4j_driver

    db = sqlite3.connect(_SPKT_DB)
    try:
        rows = db.execute(
            "SELECT s.uu_id AS suid, s.nomor AS snomor, "
            "       t.uu_id AS tuid, t.nomor AS tnomor, r.alasan "
            "FROM rujukan r "
            "JOIN pasal s ON s.id = r.pasal_id "
            "JOIN pasal t ON t.id = r.target_pasal_id "
            "WHERE r.target_pasal_id IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        db.close()
        return 0
    db.close()
    refs = [
        {"fl": law_map[suid], "fa": f"Pasal {sn}",
         "tl": law_map[tuid], "ta": f"Pasal {tn}"}
        for suid, sn, tuid, tn, _ in rows
        if suid in law_map and tuid in law_map
        and f"Pasal {sn}" != f"Pasal {tn}"
    ]
    # dedupe
    seen, uniq = set(), []
    for r in refs:
        k = (r["fl"], r["fa"], r["tl"], r["ta"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    if not uniq:
        return 0
    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j tidak tersedia untuk rujukan SPKT: %s", exc)
        return 0
    query = """
    UNWIND $refs AS r
    MATCH (a:LegalArticle {law_name: r.fl, article_number: r.fa})
    MERGE (b:LegalArticle {law_name: r.tl, article_number: r.ta})
    ON CREATE SET b.scope = 'GLOBAL', b.content = '', b.title = ''
    MERGE (a)-[:CROSS_REFERENCES]->(b)
    RETURN count(*) AS n
    """
    total = 0
    try:
        with driver.session() as session:
            for i in range(0, len(uniq), 2000):
                total += session.run(
                    query, refs=uniq[i:i + 2000]).single()["n"]
    finally:
        driver.close()
    return total


def _aph_documents():
    """Generator dokumen riset domain APH (markdown terkurasi manusia).
    Tiap heading ##/### menjadi satu 'pasal' semu; provenance aph://."""
    if not os.path.isdir(_APH_DOCS):
        logger.info("Direktori riset APH tidak ditemukan — dilewati")
        return
    for path in sorted(glob.glob(os.path.join(_APH_DOCS, "*.md"))):
        fname = os.path.basename(path)
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"(?m)^#\s+(.+)", text)
        title = m.group(1).strip() if m else fname
        heads = re.findall(r"(?m)^#{2,3}\s+(.+)", text)
        parts = re.split(r"(?m)^#{2,3}\s+.+", text)
        articles = [
            {"article_number": f"Bagian {i + 1}",
             "title": h.strip()[:80],
             "content": body.strip()[:8000]}
            for i, (h, body) in enumerate(zip(heads, parts[1:]))
            if len(body.strip()) >= 60
        ]
        if not articles:
            continue
        yield {
            "law_name": f"RISET APH — {title}",
            "law_number": None,
            "law_year": None,
            "law_subject": title,
            "articles": articles,
            "chapter_count": 0,
            "source_url": f"aph://docs/{fname}",
            "source_status": "riset-terkurasi",
        }


# ── HuggingFace corpora ──────────────────────────────────────────────

def _hf_fetch(repo: str, filename: str) -> str | None:
    """Unduh file dataset HF ke cache lokal `_HF_DIR` (sekali saja)."""
    path = os.path.join(_HF_DIR, repo.replace("/", "__"), filename)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    url = f"https://huggingface.co/datasets/{repo}/resolve/main/{filename}"
    try:
        import httpx
        with httpx.stream("GET", url, follow_redirects=True,
                          timeout=600) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        logger.info("HF %s/%s → %s (%.1f MB)", repo, filename, path,
                    os.path.getsize(path) / 1048576)
        return path
    except Exception as exc:
        logger.warning("Unduh HF %s/%s gagal: %s", repo, filename, exc)
        try:
            os.unlink(path)
        except OSError:
            pass
        return None


# UU yang paling relevan tugas APH diutamakan; sisanya menyusul.
_HF_APH_PRIORITY = re.compile(
    r"pidana|acara|kuhap|korupsi|narkotika|narkoba|teroris|pencucian|"
    r"peradilan|kejaksaan|kepolisian|kepastian|komisi pemberantasan|"
    r"perdagangan orang|kekerasan|senjata|imigrasi|bea|cukai|"
    r"informasi|transaksi elektronik|perlindungan anak|desersi|"
    r"intelijen|penyidik", re.IGNORECASE)


# Ekstraksi relasi amandemen/pencabutan dari teks UU — konservatif:
# hanya pola eksplisit "mencabut/dicabut/tidak berlaku" (REVOKES) dan
# "mengubah/diubah" (AMENDS) dalam radius dekat identitas UU lain.
_LAW_REF_RE = re.compile(
    r"(?:Undang[-\s]Undang|Peraturan\s+(?:Pemerintah|Presiden|Menteri)"
    r"|Peraturan\s+Daerah|UU)\s+(?:Nomor\s+|No\.?\s*)?(\d{1,3})\s+"
    r"Tahun\s+(\d{4})", re.IGNORECASE)
_REVOKE_PRE = re.compile(r"(mencabut|dicabut)[^.]{0,80}$", re.IGNORECASE)
_REVOKE_POST = re.compile(
    r"^[^.]{0,80}?(dicabut|dinyatakan\s+tidak\s+berlaku|tidak\s+berlaku)",
    re.IGNORECASE)
_AMEND_PRE = re.compile(r"(mengubah|diubah|perubahan\s+atas)[^.]{0,60}$",
                        re.IGNORECASE)
# "UU X diubah dengan undang-undang ini" → dokumen ini AMENDS X
_AMEND_SELF_POST = re.compile(
    r"^[^.]{0,60}?diubah\s+(?:terakhir\s+)?(?:dengan|oleh)\s+"
    r"(?:undang[-\s]undang|uu)\s+ini", re.IGNORECASE)


def _extract_law_relations(text: str, own_num: str | None,
                           own_year: str | None) -> dict:
    """Kembalikan {'revokes','amends','amended_by'} — relasi tingkat-UU.

    Tingkat kalimat, bukan window bebas: kata kerja harus berada dalam
    kalimat yang sama dengan identitas UU target — menghindari false
    positive dari klausa tetangga. `amended_by` menangkap pola
    "diubah dengan UU X" (arah relasi terbalik)."""
    revokes, amends, amended_by = set(), set(), set()
    for m in _LAW_REF_RE.finditer(text or ""):
        num, year = m.group(1).lstrip("0") or m.group(1), m.group(2)
        if (num, year) == (own_num, own_year):
            continue  # referensi diri
        target = f"UU Nomor {num} Tahun {year}"
        prefix = text[max(0, m.start() - 90):m.start()]
        suffix = text[m.end():m.end() + 90]
        if _REVOKE_PRE.search(prefix) or _REVOKE_POST.match(suffix):
            revokes.add(target)
        elif re.search(r"diubah\s+(?:terakhir\s+)?(?:dengan|oleh)[^.]{0,60}$",
                       prefix, re.IGNORECASE):
            amended_by.add(target)
        elif _AMEND_PRE.search(prefix) or _AMEND_SELF_POST.match(suffix):
            amends.add(target)
    return {"revokes": sorted(revokes), "amends": sorted(amends),
            "amended_by": sorted(amended_by)}


def _hf_category(law_name: str) -> str:
    if re.search(r"acara|hukum acara|peradilan", law_name, re.IGNORECASE):
        return "formil"
    if _HF_APH_PRIORITY.search(law_name):
        return "materiil"
    return "regulasi"


def _hf_laws_documents():
    """Generator UU dari `ipfs_indonesia_laws` — pasal sudah ter-split
    per baris parquet; metadata law_status → source_status."""
    laws_path = _hf_fetch(_HF_LAWS_DS, "data/laws.parquet")
    arts_path = _hf_fetch(_HF_LAWS_DS, "data/articles.parquet")
    if not laws_path or not arts_path:
        return
    try:
        import pyarrow.parquet as pq
        laws = pq.read_table(laws_path).to_pylist()
        arts = pq.read_table(arts_path).to_pylist()
    except ImportError:
        logger.warning("pyarrow belum terinstall — impor HF dilewati")
        return
    meta = {}
    for row in laws:
        ident = row.get("official_identifier") or row.get(
            "identifier") or ""
        m = re.search(r"No\.?\s*(\d+)\s+Tahun\s+(\d{4})", ident)
        # Judul kadang bercampur sisa markup HTML ("…\" />" dst.).
        title = re.sub(r'["<][^>]{0,30}$', "",
                       (row.get("title") or ident)).strip()
        rels = _extract_law_relations(
            row.get("text") or "",
            m.group(1).lstrip("0") if m else None,
            m.group(2) if m else None)
        meta[row["id"]] = {
            "num": m.group(1) if m else None,
            "year": m.group(2) if m else None,
            "title": title,
            "status": ("berlaku" if row.get("law_status") == "current"
                       else str(row.get("law_status") or "unknown")),
            "url": row.get("source_url") or "",
            "amends": rels["amends"],
            "revokes": rels["revokes"],
            "amended_by": rels["amended_by"],
        }
    grouped: dict[str, dict] = {}
    for a in arts:
        text = (a.get("text") or "").strip()
        if len(text) < 30:
            continue
        key = str(a.get("article_number") or a.get("title") or "")
        g = grouped.setdefault(a["law_id"], {})
        if key in g:
            continue  # baris pasal duplikat di parquet (versi/amandemen)
        g[key] = {"article_number": key,
                  "title": str(a.get("title") or ""),
                  "content": text[:8000]}
    # Urutkan: prioritas APH dulu, lalu tahun terbaru.
    def _rank(law_id: str) -> tuple:
        m = meta.get(law_id) or {}
        pri = 0 if _HF_APH_PRIORITY.search(m.get("title", "")) else 1
        try:
            yr = -int(m.get("year") or 0)
        except (TypeError, ValueError):
            yr = 0
        return (pri, yr, law_id)

    emitted = 0
    for law_id in sorted(grouped, key=_rank):
        if _HF_MAX_LAWS and emitted >= _HF_MAX_LAWS:
            break
        m = meta.get(law_id)
        articles = list(grouped[law_id].values())
        if not m or not m["num"] or len(articles) < 2:
            continue
        emitted += 1
        yield {
            "law_name": m["title"].strip() or (
                f"UU Nomor {m['num']} Tahun {m['year']}"),
            "law_number": m["num"].lstrip("0") or m["num"],
            "law_year": m["year"],
            "law_subject": m["title"],
            "articles": articles,
            "chapter_count": 0,
            "source_url": m["url"] or f"hf://laws/{law_id}",
            "source_status": m["status"],
            "amends": m["amends"],
            "revokes": m["revokes"],
            "amended_by": m["amended_by"],
            "_hf_category": _hf_category(m["title"]),
        }


# Seksi putusan yang paling informatif untuk analisis perkara.
_PUTUSAN_KEEP = {
    "kepala_putusan", "riwayat_dakwaan", "riwayat_tuntutan",
    "fakta", "pertimbangan_hukum", "amar_putusan"}


def _hf_putusan_documents():
    """Generator putusan MA — seksi bernilai jadi 'pasal' semu,
    provenance hf://putusan/<id>."""
    if _HF_MAX_PUTUSAN <= 0:
        return  # HF_PUTUSAN_MAX ≤ 0 → impor putusan dinonaktifkan
    path = _hf_fetch(_HF_PUTUSAN_DS, "supreme_court.parquet")
    if not path:
        return
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(path)
    except ImportError:
        logger.warning("pyarrow belum terinstall — impor putusan "
                       "dilewati")
        return
    rows = table.to_pylist()
    emitted = 0
    for row in rows:
        if emitted >= _HF_MAX_PUTUSAN:
            break
        paras = row.get("paragraphs") or {}
        tags, values = paras.get("tag") or [], paras.get("value") or []
        sections = []
        kepala = ""
        for tag, val in zip(tags, values):
            text = (val or "").strip()
            if tag == "kepala_putusan":
                kepala = " ".join(text.split())[:200]
            if tag in _PUTUSAN_KEEP and len(text) >= 60:
                sections.append({
                    "article_number": tag.replace("_", " ").title(),
                    "title": tag,
                    "content": text[:8000]})
        if not sections:
            continue
        emitted += 1
        yield {
            "law_name": f"Putusan MA {kepala[:80] or row['id'][:12]}",
            "law_number": None,
            "law_year": None,
            "law_subject": f"putusan {row.get('klasifikasi')}",
            "articles": sections,
            "chapter_count": 0,
            "source_url": f"hf://putusan/{row['id']}",
            "source_status": "putusan-terverifikasi",
            "_hf_category": "yurisprudensi",
        }


def import_external_corpus(db, report=None) -> dict:
    """Serap korpus SPKT + LexisAI ke Chroma/Neo4j/registry ALA.

    Idempotent: identitas (nomor, tahun) yang sudah teregistrasi
    dilewati. `report(stage, topic, detail)` opsional untuk progres live.
    """
    from app.agents.alcd.autonomous_ingestor import (
        ingest_parsed_document, register_knowledge)
    from app.agents.alcd.graph_builder import (
        build_graph_for_document, link_law_relations)
    from app.models.operational import KnowledgeRegistry
    from sqlalchemy import select

    def _rep(stage, topic, detail, done=None, total=None):
        if report:
            report(stage, topic, detail, done, total)

    def _known_ids() -> set[tuple[str, str]]:
        ids = set()
        rows = db.scalars(select(KnowledgeRegistry).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))).all()
        import re as _re
        for r in rows:
            num = (r.law_number or "").lstrip("0")
            yr = (r.metadata_ or {}).get("law_year") if r.metadata_ else None
            if num and yr:
                ids.add((num, str(yr)))
                continue
            m = _re.search(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})",
                           r.law_name or "")
            if m:
                ids.add((m.group(1).lstrip("0"), m.group(2)))
        return ids

    stats = {"laws": 0, "chunks": 0, "articles": 0, "edges": 0,
             "skipped": []}
    spkt_law_map: dict[int, str] = {}
    known = _known_ids()

    # SPKT — pasal bersih + rujukan terverifikasi
    if os.path.exists(_SPKT_DB):
        sdb = sqlite3.connect(_SPKT_DB)
        id2kode = {r[0]: r[1] for r in sdb.execute(
            "SELECT id, kode FROM uu")}
        putusan = sdb.execute(
            "SELECT nomor_putusan, tahun, pasal, amar, ringkasan, "
            "       (SELECT judul FROM uu WHERE id = putusan_mk.uu_id) "
            "FROM putusan_mk").fetchall()
        sdb.close()
        spkt_total = len(id2kode) + len(putusan)
        for si, parsed in enumerate(_spkt_documents()):
            key = (parsed["law_number"].lstrip("0"), parsed["law_year"])
            if key in known:
                stats["skipped"].append(parsed["law_name"])
                continue
            _rep("import", "Korpus SPKT",
                 f"{parsed['law_number']}/{parsed['law_year']} · "
                 f"{len(parsed['articles'])} pasal",
                 si + 1, spkt_total)
            try:
                cat = _law_category(parsed.pop("_kode", ""))
                res = ingest_parsed_document(parsed, cat, verified=True)
                register_knowledge(db, parsed, res, cat, True)
                build_graph_for_document(res["law_name"],
                                         parsed["articles"])
                known.add(key)
                stats["laws"] += 1
                stats["chunks"] += res["chunks"]
                stats["articles"] += res["articles"]
                _rep("import", "Korpus SPKT",
                     f"tertanam {res['law_name'][:55]}",
                     si + 1, spkt_total)
            except Exception as exc:
                db.rollback()
                logger.warning("Impor SPKT %s gagal: %s",
                               parsed["law_name"], exc)

        # Putusan MK — yurisprudensi pengujian UU (amar + ringkasan).
        existing_src = set(db.scalars(
            select(KnowledgeRegistry.source_url).where(
                KnowledgeRegistry.source_url.like(
                    "spkt://database/spkt.db#mk-%"))))
        for pi, (nomor_put, tahun, pasal, amar, ringkasan,
                 judul_uu) in enumerate(putusan):
            if f"spkt://database/spkt.db#mk-{nomor_put}" in existing_src:
                continue  # idempotent — putusan tak punya nomor/tahun
            _rep("import", "Korpus SPKT",
                 f"putusan MK {nomor_put}",
                 len(id2kode) + pi + 1, spkt_total)
            content = (f"Amar putusan {nomor_put} atas {judul_uu or ''} "
                       f"Pasal {pasal}:\n{amar or ''}\n\n"
                       f"Ringkasan: {ringkasan or ''}").strip()
            parsed = {
                "law_name": f"Putusan MK {nomor_put}",
                "law_number": None,
                "law_year": str(tahun or ""),
                "law_subject": f"Pengujian {judul_uu or 'UU'} Pasal {pasal}",
                "articles": [{"article_number": f"Pasal {pasal}",
                              "title": str(nomor_put), "content": content}],
                "chapter_count": 0,
                "source_url": f"spkt://database/spkt.db#mk-{nomor_put}",
                "source_status": "berlaku",
            }
            try:
                res = ingest_parsed_document(
                    parsed, "yurisprudensi", verified=True)
                register_knowledge(db, parsed, res, "yurisprudensi", True)
                build_graph_for_document(res["law_name"], parsed["articles"])
                stats["laws"] += 1
                stats["chunks"] += res["chunks"]
                stats["articles"] += res["articles"]
            except Exception as exc:
                db.rollback()
                logger.warning("Impor putusan %s gagal: %s", nomor_put, exc)
        # Peta uu_id → law_name untuk edge rujukan
        for uid, kode in id2kode.items():
            row = db.scalar(select(KnowledgeRegistry.law_name).where(
                KnowledgeRegistry.source_url ==
                f"spkt://database/spkt.db#{kode}"))
            if row:
                spkt_law_map[uid] = row
        edges = _import_spkt_rujukan(spkt_law_map)
        stats["edges"] = edges
        if edges:
            _rep("import", "Korpus SPKT",
                 f"{edges} rujukan antar-pasal tertaut")

    # LexisAI — hanya identitas UU yang belum ada
    try:
        lex_docs = list(_lexisai_documents(known))
        for li, parsed in enumerate(lex_docs):
            _rep("import", "Korpus LexisAI",
                 f"{parsed['law_number']}/{parsed['law_year']} · "
                 f"{len(parsed['articles'])} pasal",
                 li + 1, len(lex_docs))
            try:
                cat = _law_category(parsed.pop("_kode", ""))
                res = ingest_parsed_document(parsed, cat, verified=True)
                register_knowledge(db, parsed, res, cat, True)
                build_graph_for_document(res["law_name"],
                                         parsed["articles"])
                known.add((parsed["law_number"].lstrip("0"),
                           parsed["law_year"]))
                stats["laws"] += 1
                stats["chunks"] += res["chunks"]
                stats["articles"] += res["articles"]
            except Exception as exc:
                db.rollback()
                logger.warning("Impor LexisAI %s gagal: %s",
                               parsed["law_name"], exc)
    except Exception as exc:
        logger.warning("Impor LexisAI gagal total: %s", exc)

    # Riset domain APH — dokumen markdown terkurasi (alur SPP,
    # nomenklatur, state machine, pustaka pasal). Kategori 'doktrin':
    # pengetahuan analitik aplikatif, BUKAN teks primer peraturan.
    try:
        aph_docs = list(_aph_documents())
        for ai, parsed in enumerate(aph_docs):
            exists = db.scalar(select(KnowledgeRegistry.id).where(
                KnowledgeRegistry.source_url == parsed["source_url"],
                KnowledgeRegistry.ingestion_status.in_(
                    ["completed", "verified"])))
            if exists:
                continue
            _rep("import", "Riset APH", parsed["law_subject"][:55],
                 ai + 1, len(aph_docs))
            try:
                res = ingest_parsed_document(parsed, "doktrin", True)
                register_knowledge(db, parsed, res, "doktrin", True)
                stats["laws"] += 1
                stats["chunks"] += res["chunks"]
                stats["articles"] += res["articles"]
            except Exception as exc:
                db.rollback()
                logger.warning("Impor riset %s gagal: %s",
                               parsed["law_name"], exc)
    except Exception as exc:
        logger.warning("Impor riset APH gagal total: %s", exc)

    # HuggingFace ipfs_indonesia_laws — 1.924 UU / 105K pasal dari JDIH
    # BPK. Dedupe identitas (nomor,tahun) — UU yang sudah ada dari
    # crawl/SPKT/LexisAI tidak diimpor ulang. source_status membawa
    # law_status ('berlaku' vs non-current) untuk audit temporal.
    try:
        hf_docs = list(_hf_laws_documents())
        for hi, parsed in enumerate(hf_docs):
            key = (parsed["law_number"].lstrip("0"), parsed["law_year"])
            if key in known:
                continue
            _rep("import", "Korpus JDIH BPK (HF)",
                 f"{parsed['law_number']}/{parsed['law_year']} · "
                 f"{len(parsed['articles'])} pasal",
                 hi + 1, len(hf_docs))
            try:
                cat = parsed.pop("_hf_category", "regulasi")
                res = ingest_parsed_document(parsed, cat, verified=True)
                register_knowledge(db, parsed, res, cat, True)
                build_graph_for_document(res["law_name"],
                                         parsed["articles"])
                if parsed.get("amends") or parsed.get("revokes") \
                        or parsed.get("amended_by"):
                    link_law_relations(
                        res["law_name"],
                        parsed.get("revokes") or [],
                        parsed.get("amends") or [],
                        parsed.get("amended_by") or [])
                known.add(key)
                stats["laws"] += 1
                stats["chunks"] += res["chunks"]
                stats["articles"] += res["articles"]
            except Exception as exc:
                db.rollback()
                logger.warning("Impor HF %s gagal: %s",
                               parsed["law_name"], exc)
    except Exception as exc:
        logger.warning("Impor HF laws gagal total: %s", exc)

    # Putusan MA — yurisprudensi pidana terstruktur (22.630 perkara,
    # dibatasi HF_PUTUSAN_MAX). Dedupe per source_url (id putusan).
    try:
        put_docs = list(_hf_putusan_documents())
        existing = set(db.scalars(select(KnowledgeRegistry.source_url)
                       .where(KnowledgeRegistry.source_url.like(
                           "hf://putusan/%"))))
        for pi, parsed in enumerate(put_docs):
            if parsed["source_url"] in existing:
                continue
            _rep("import", "Putusan MA",
                 (parsed["law_name"] or "")[:55],
                 pi + 1, len(put_docs))
            try:
                cat = parsed.pop("_hf_category", "yurisprudensi")
                res = ingest_parsed_document(parsed, cat, verified=True)
                register_knowledge(db, parsed, res, cat, True)
                stats["laws"] += 1
                stats["chunks"] += res["chunks"]
                stats["articles"] += res["articles"]
            except Exception as exc:
                db.rollback()
                logger.warning("Impor putusan HF %s gagal: %s",
                               parsed["source_url"], exc)
    except Exception as exc:
        logger.warning("Impor putusan HF gagal total: %s", exc)

    logger.info("Impor korpus eksternal: %d UU, %d pasal, %d chunk, "
                "%d edge rujukan; %d dilewati (sudah ada)",
                stats["laws"], stats["articles"], stats["chunks"],
                stats["edges"], len(stats["skipped"]))
    return stats
