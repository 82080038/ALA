"""
Legal Foundation Agent — Agent 1 (Law-First).

Pencarian pertama SELALU di basis pengetahuan hukum GLOBAL: ChromaDB
`indonesian_laws` untuk RAG pasal + Neo4j `LegalArticle` untuk
referensi silang. Query pengguna tidak pernah langsung masuk ke web
scraper atau code generator.
"""
import logging
import pickle
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("ala.agents.legal_foundation")

_XREF_QUERY = """
MATCH (a:LegalArticle)
WHERE a.law_name CONTAINS $q OR a.content CONTAINS $q
OPTIONAL MATCH (a)-[r:CROSS_REFERENCES]->(b:LegalArticle)
RETURN a.law_name AS law, a.article_number AS article,
       collect(DISTINCT {law: b.law_name, article: b.article_number})[0..5] AS refs
LIMIT $limit
"""


# Skor minimum cosine — skala E5 memberi ~0.75+ untuk teks bertopik
# sama; di bawah ini lebih sering menyesatkan daripada membantu.
# Kandidat BM25-only diterima hingga 0.72 (leksikal menangkap istilah
# literal yang dense-miss, mis. "pencurian pemberatan" → "mengambil
# barang"); reranker kata-kunci adalah filter kedua.
_MIN_SCORE = 0.72


def _cosine(a, b) -> float:
    import numpy as np

    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


# ── Hybrid retrieval: dense E5 + BM25 leksikal → Reciprocal Rank Fusion ──

_lex_cache: dict = {"count": -1, "index": None, "ids": [], "metas": [],
                    "docs": []}
_lex_lock = threading.Lock()
_BM25_SNAPSHOT_VERSION = 1


def _bm25_path() -> Path:
    from app.config import settings

    return Path(settings.bm25_index_path)


def _load_bm25_snapshot(count: int) -> dict | None:
    """Muat snapshot BM25 dari disk bila cocok dengan count koleksi."""
    try:
        p = _bm25_path()
        if not p.exists():
            return None
        snap = pickle.loads(p.read_bytes())
        if (snap.get("version") != _BM25_SNAPSHOT_VERSION
                or snap.get("count") != count):
            return None
        return snap
    except Exception as exc:
        logger.warning("Snapshot BM25 tak bisa dimuat: %s", exc)
        return None


def _save_bm25_snapshot() -> None:
    """Tulis snapshot atomik (tmp+rename) — aman dari kill di tengah."""
    try:
        p = _bm25_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps({
            "version": _BM25_SNAPSHOT_VERSION,
            "count": _lex_cache["count"],
            "index": _lex_cache["index"],
            "ids": _lex_cache["ids"],
            "metas": _lex_cache["metas"],
            "docs": _lex_cache["docs"],
        }, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(p)
        logger.info("Snapshot BM25 tersimpan (%d chunk) → %s",
                    _lex_cache["count"], p)
    except Exception as exc:
        logger.warning("Snapshot BM25 gagal disimpan: %s", exc)


_BM25_ID_PAGE = 10_000
_BM25_GET_BATCH = 4_000  # < batas variabel sqlite Chroma (~32K)

# Query yang memang meminta case law — putusan TIDAK diturunkan.
_CASE_LAW_RE = re.compile(
    r"putusan|yurisprudensi|preseden|preceden|jurisprudensi|"
    r"fatwa|penetapan|doktrin\s+putusan", re.IGNORECASE)


def invalidate_lexical_index() -> None:
    """Dipanggil ingestor setelah upsert — chunk baru/terubah memaksa
    rebuild pada query berikutnya (snapshot lama dihapus)."""
    with _lex_lock:
        _lex_cache["count"] = -1
    try:
        _bm25_path().unlink(missing_ok=True)
    except OSError:
        pass


def _lexical_index(collection):
    """Bangun/cache indeks BM25 atas seluruh chunk Chroma. Urutan:
    cache memori → snapshot disk → rebuild penuh (lalu disimpan).
    Di-invalidate saat koleksi berubah count atau pasca-ingest."""
    n = collection.count()
    if _lex_cache["index"] is not None and _lex_cache["count"] == n:
        return _lex_cache
    with _lex_lock:
        if _lex_cache["index"] is not None and _lex_cache["count"] == n:
            return _lex_cache
        snap = _load_bm25_snapshot(n)
        if snap is not None:
            _lex_cache.update(
                count=n, index=snap["index"], ids=snap["ids"],
                metas=snap["metas"], docs=snap["docs"])
            logger.info("Indeks BM25 dimuat dari snapshot (%d chunk)", n)
            return _lex_cache
        from app.agents.bm25 import BM25Index

        # Fetch dua tahap: ids dulu (halaman demi halaman — get()
        # tanpa argumen meledak "too many SQL variables" pada
        # sqlite Chroma saat koleksi >~32K baris), lalu dokumen
        # per-batch by id — offset pagination bisa geser saat
        # ingest konkuren, daftar id snapshot tidak.
        all_ids: list[str] = []
        offset = 0
        while True:
            page = collection.get(include=[], limit=_BM25_ID_PAGE,
                                  offset=offset)
            if not page["ids"]:
                break
            all_ids.extend(page["ids"])
            offset += len(page["ids"])
        ids, docs, metas = [], [], []
        for i in range(0, len(all_ids), _BM25_GET_BATCH):
            got = collection.get(
                ids=all_ids[i:i + _BM25_GET_BATCH],
                include=["documents", "metadatas"])
            ids.extend(got["ids"])
            docs.extend(got["documents"])
            metas.extend(got["metadatas"])
        logger.info("Bangun indeks BM25 atas %d chunk", len(docs))
        _lex_cache.update(count=n, index=BM25Index(docs),
                          ids=ids, metas=metas, docs=docs)
        _save_bm25_snapshot()
        return _lex_cache


# ── Reranker cross-encoder lokal (zero-cost, lazy-load, CPU-viable) ──

_reranker: dict = {"model": None, "name": None, "failed": False}


def _get_reranker():
    """Singleton lazy — model diunduh sekali dari HF (gratis, ~118MB)
    pada pemakaian pertama; kegagalan dinonaktifkan agar retrieval
    tetap jalan tanpa rerank."""
    from app.config import settings

    if not settings.reranker_enabled or _reranker["failed"]:
        return None
    if _reranker["model"] is None or _reranker["name"] != settings.reranker_model:
        try:
            from sentence_transformers import CrossEncoder

            _reranker["model"] = CrossEncoder(
                settings.reranker_model, max_length=512)
            _reranker["name"] = settings.reranker_model
            logger.info("Reranker dimuat: %s", settings.reranker_model)
        except Exception as exc:
            logger.warning("Reranker gagal dimuat (%s) — tanpa rerank", exc)
            _reranker["failed"] = True
            return None
    return _reranker["model"]


def _rerank(query: str, fused: list[tuple[str, float]],
            dense_meta: dict, id2doc: dict) -> list[tuple[str, float]]:
    """Skor ulang kandidat teratas dengan cross-encoder. Skor reranker
    hanya menentukan URUTAN — relevance_score yang dilaporkan tetap
    cosine dense (skala abstention tidak berubah). Gagal → urutan RRF."""
    from app.config import settings

    model = _get_reranker()
    if model is None or not fused:
        return fused
    top = fused[:settings.reranker_top]
    ids = [did for did, _ in top]
    docs = [
        (dense_meta[did][0] if did in dense_meta else id2doc.get(did, ""))
        [:1500]
        for did in ids
    ]
    try:
        scores = model.predict(list(zip([query] * len(ids), docs)))
    except Exception as exc:
        logger.warning("Reranker predict gagal: %s — urutan RRF", exc)
        return fused
    reranked = sorted(zip(ids, scores), key=lambda x: -float(x[1]))
    return reranked + fused[len(top):]


def _rrf_fuse(dense_ids: list[str], lex_ids: list[str],
              boosts: dict | None = None) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: skor = Σ 1/(60 + rank). Feedback penggunaan
    masa lalu memberi boost kecil (belajar dari pengalaman retrieval)."""
    fused: dict[str, float] = {}
    for rank, did in enumerate(dense_ids):
        fused[did] = fused.get(did, 0.0) + 1.0 / (60 + rank)
    for rank, did in enumerate(lex_ids):
        fused[did] = fused.get(did, 0.0) + 1.0 / (60 + rank)
    if boosts:
        for did, b in boosts.items():
            if did in fused:
                fused[did] += b
    return sorted(fused.items(), key=lambda x: -x[1])


def _usage_boosts(ids: list[str], metas: list[dict]) -> dict[str, float]:
    """Boost kecil untuk pasal yang historis sering terbukti berguna
    (tersitasi terverifikasi di jawaban sebelumnya). Tabel
    retrieval_feedback hanya menyimpan agregat (law, pasal, cited) —
    TANPA teks query (privasi tenant)."""
    try:
        from app.database.postgres import SessionLocal
        from sqlalchemy import text

        with SessionLocal() as db:
            rows = db.execute(text(
                "SELECT law_name, article_number, count(*) AS n "
                "FROM retrieval_feedback WHERE cited GROUP BY 1,2"
            )).all()
    except Exception:
        return {}
    cited_count = {(r[0], r[1]): r[2] for r in rows}
    boosts = {}
    for did, meta in zip(ids, metas):
        uses = cited_count.get(
            (meta.get("law_name"), meta.get("article_number")), 0)
        if uses:
            boosts[did] = min(0.008, 0.002 * uses)  # ~½ peringkat RRF
    return boosts


# ── Boost deterministik: identitas hukum yang disebut eksplisit di query ──
# Nama lazim → pasangan (nomor, tahun) yang mungkin dimaksud. Ambiguitas
# (mis. KUHP lama vs baru) mem-boost SEMUA kandidat yang cocok — audit
# temporal di hilir yang menyaring anakronisme.
_LAW_ALIASES = {
    "kuhap": [("8", "1981"), ("20", "2025")],
    "kuhp": [("1", "1946"), ("1", "2023")],
    "tipikor": [("31", "1999"), ("20", "2001")],
    "tindak pidana korupsi": [("31", "1999"), ("20", "2001")],
    "korupsi": [("31", "1999"), ("20", "2001")],
    "ite": [("11", "2008"), ("19", "2016"), ("1", "2024")],
    "narkotika": [("35", "2009")],
    "narkoba": [("35", "2009")],
    "tppu": [("8", "2010"), ("25", "2003")],
    "pencucian uang": [("8", "2010"), ("25", "2003")],
    "tppo": [("21", "2007")],
    "perdagangan orang": [("21", "2007")],
    "terorisme": [("5", "2018"), ("15", "2003")],
    "kpk": [("19", "2019"), ("30", "2002")],
    "tpks": [("12", "2022")],
    "kekerasan seksual": [("12", "2022")],
    "kdrt": [("23", "2004")],
    "kepolisian": [("2", "2002")],
    "kejaksaan": [("11", "2021"), ("16", "2004")],
    "peradilan militer": [("31", "1997")],
    "pajak": [("28", "2007"), ("6", "1983")],
}
_LAW_NUM_RE = re.compile(
    r"(?:nomor|no\.?|)\s*(\d{1,3})\s*(?:tahun|/)\s*(\d{4})", re.I)
_LAW_NUM_RE2 = re.compile(r"(\d{1,3})\s*/\s*(19|20)(\d{2})")
_PASAL_RE = re.compile(r"pasal\s+(\d{1,3}[a-zA-Z]?)", re.I)


def _query_law_mentions(query: str) -> set[tuple[str, str]]:
    """Ekstrak identitas UU (nomor, tahun) yang disebut eksplisit/lazim."""
    q = query.lower()
    found = set()
    for m in _LAW_NUM_RE.finditer(q):
        found.add((m.group(1), m.group(2)))
    for m in _LAW_NUM_RE2.finditer(q):
        found.add((m.group(1), m.group(2) + m.group(3)))
    for alias, pairs in _LAW_ALIASES.items():
        if alias in q:
            found.update(pairs)
    return found


def _law_pairs_of(name: str) -> set[tuple[str, str]]:
    """Pasangan (nomor, tahun) yang tercantum pada nama dokumen."""
    name = name.lower()
    out = set()
    for m in _LAW_NUM_RE.finditer(name):
        out.add((m.group(1), m.group(2)))
    for m in _LAW_NUM_RE2.finditer(name):
        out.add((m.group(1), m.group(2) + m.group(3)))
    return out


def _mention_boosts(query: str, ids: list[str],
                    metas: list[dict]) -> dict[str, float]:
    """Boost RRF untuk chunk dari UU/pasal yang DISEBUT eksplisit di query.

    Menangani kelemahan dense-retrieval: pasal target sering kalah dari
    pasal serupa lintas-UU. Magnitudo ~2 peringkat RRF untuk UU cocok,
    ~4 untuk UU+pasal cocok — cukup menarik target ke atas tanpa
    menghapus sinyal semantik."""
    laws = _query_law_mentions(query)
    pasal = {m.group(1).lower() for m in _PASAL_RE.finditer(query)}
    if not laws and not pasal:
        return {}
    boosts = {}
    for did, meta in zip(ids, metas):
        meta = meta or {}
        b = 0.0
        if laws and (law_pairs := _law_pairs_of(meta.get("law_name", ""))):
            if laws & law_pairs:
                b += 0.04
        if pasal:
            art = (meta.get("article_number") or "").lower().replace(
                "pasal", "").strip()
            if art in pasal:
                b += 0.04 if b else 0.01
        if b:
            boosts[did] = b
    return boosts


def _rag_retrieve(query: str, n_results: int = 12) -> list[dict]:
    """Retrieval HIBRID GLOBAL: dense E5 (semantik) ∪ BM25 (leksikal),
    digabung RRF + boost riwayat sitasi terverifikasi.

    Skor dense dihitung sebagai cosine similarity langsung — jarak
    mentah koleksi tidak bermakna. Kandidat BM25-only dinormalkan ke
    ≤0.72 agar tidak menyerupai skor dense."""
    from app.agents.alcd.autonomous_ingestor import embed_query
    from app.database.chroma import get_chroma_client, get_laws_collection

    try:
        collection = get_laws_collection(get_chroma_client())
        qvec = embed_query(query)
        hits = collection.query(
            query_embeddings=[qvec],
            n_results=max(24, n_results * 2),
            include=["documents", "metadatas", "embeddings"],
        )
    except Exception as exc:
        logger.warning("ChromaDB query gagal: %s", exc)
        return []

    dense_ids = hits.get("ids", [[]])[0]
    dense_meta = {
        did: (doc, meta, vec)
        for did, doc, meta, vec in zip(
            dense_ids,
            hits.get("documents", [[]])[0],
            hits.get("metadatas", [[]])[0],
            hits.get("embeddings", [[]])[0],
        )
    }
    sims = {did: _cosine(qvec, v[2]) for did, v in dense_meta.items()}

    # Lapis leksikal — tangkap istilah literal yang dense-miss
    lex_ids: list[str] = []
    try:
        cache = _lexical_index(collection)
        lex_ids = [cache["ids"][i]
                   for i, _s in cache["index"].search(query, top_k=24)]
    except Exception as exc:
        logger.warning("Indeks BM25 gagal: %s — dense-only", exc)

    cache = _lex_cache
    boosts = _usage_boosts(cache["ids"], cache["metas"])
    for did, b in _mention_boosts(query, cache["ids"], cache["metas"]).items():
        boosts[did] = boosts.get(did, 0.0) + b
    fused = _rrf_fuse(list(dense_ids), lex_ids, boosts)

    id2meta = dict(zip(cache["ids"], cache["metas"]))
    id2doc = dict(zip(cache["ids"], cache["docs"]))
    # Cross-encoder rerank atas kandidat teratas — presisi kontekstual
    # pasangan (query, pasal) yang tak tertangkap bi-encoder E5.
    ordered = _rerank(query, fused, dense_meta, id2doc)
    # Primat peraturan PASKA-rerank (reranker akan membatalkan demosi
    # pra-rerank): kecuali query memang meminta case law, chunk
    # yurisprudensi ditempatkan di belakang peraturan/doktrin —
    # undang-undang otoritas primer, putusan persuasif. Banjir
    # putusan (korpus terbesar) tidak boleh menenggelamkan pasal
    # pada query generik; putusan tetap hadir, hanya berikutnya.
    if not _CASE_LAW_RE.search(query):
        ordered.sort(
            key=lambda kv: (id2meta.get(kv[0]) or {}).get(
                "law_category") == "yurisprudensi")
    # Pin deterministik pasca-rerank: bila query menyebut UU+Pasal
    # secara eksplisit, dokumen yang identitasnya cocok PERSIS harus
    # mendahului — reranker semantik tidak boleh menenggelamkan
    # sitasi yang diminta user (mis. putusan lain di atas pasal UU).
    # BM25 hanya mengindeks isi chunk, bukan metadata — pasal yang
    # disebut bisa absen dari KEDUA kandidat; suntikkan langsung.
    mention = _mention_boosts(query, cache["ids"], cache["metas"])
    pinned = {did for did, b in mention.items() if b >= 0.08}
    if pinned:
        have = {did for did, _ in ordered}
        ordered += [(did, 0.0) for did in pinned if did not in have]
        ordered.sort(key=lambda kv: kv[0] not in pinned)
    articles, seen_art = [], set()
    for did, _fs in ordered:
        if len(articles) >= n_results * 2:
            break
        if did in dense_meta:
            doc, meta, _ = dense_meta[did]
            score = sims[did]
            if score < _MIN_SCORE:
                continue  # dense bilang tidak relevan — buang
        else:
            # BM25-only: lolos hanya bila ada bukti kata kunci kuat —
            # kecuali pinned (identitas persis, bukti lebih kuat).
            if did not in pinned and did not in set(lex_ids[:10]):
                continue
            meta = id2meta.get(did)
            doc = id2doc.get(did, "")
            if not meta:
                continue
            score = 0.72
        key = (meta.get("law_name"), meta.get("article_number"))
        if key in seen_art:
            continue
        seen_art.add(key)
        articles.append({
            "law_name": meta.get("law_name", "Unknown"),
            "article_number": meta.get("article_number", ""),
            "content": doc,
            "relevance_score": round(score, 3),
            "source_url": meta.get("source_url", ""),
            "topic": meta.get("topic", ""),
        })
    return articles[:n_results]


def _graph_xrefs(query: str, limit: int = 5) -> list[dict]:
    """Ambil referensi silang dari Neo4j GLOBAL."""
    from app.database.neo4j import get_neo4j_driver

    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j tidak tersedia: %s", exc)
        return []
    try:
        with driver.session() as session:
            rows = session.run(
                _XREF_QUERY,
                q=_extract_law_hint(query), limit=limit,
            ).data()
        return [
            {
                "from_law": r["law"],
                "from_article": r["article"],
                "to": r["refs"],
            }
            for r in rows if r["refs"]
        ]
    except Exception as exc:
        logger.warning("Neo4j xref query gagal: %s", exc)
        return []
    finally:
        driver.close()


def _extract_law_hint(query: str) -> str:
    """Ambil nomor UU/pasal dari query sebagai petunjuk pencarian."""
    m = re.search(r"(UU\s*\d+|Pasal\s*\d+|KUHP|KUHAP|ITE|Tipikor|Narkotika)",
                  query, re.IGNORECASE)
    return m.group(0) if m else query[:60]


def _dedup_articles(articles: list[dict], token_budget: int) -> list[dict]:
    """Dedup (law_name, article_number) lalu pangkas sesuai token budget."""
    seen, unique = set(), []
    for art in articles:
        key = (art["law_name"], art["article_number"])
        if key not in seen:
            seen.add(key)
            unique.append(art)
    # Perkiraan 1 token ≈ 4 karakter; alokasi 50% budget untuk konteks hukum
    char_cap = int(token_budget * 0.5 * 4)
    out, used = [], 0
    for art in unique:
        size = len(art["content"])
        if used + size > char_cap:
            art["content"] = art["content"][: max(0, char_cap - used)]
            out.append(art)
            break
        out.append(art)
        used += size
    return out


_SUMMARY_PROMPT = """Anda adalah profesor hukum Indonesia yang KETAT dan
metodis, memberi analisis singkat kepada penyidik. Jawab HANYA
berdasarkan pasal-pasal yang diberikan di bawah — dilarang menyebut
UU/pasal yang tidak ada dalam daftar, dilarang mengarang.

Struktur jawaban (metode analisis hukum):
1. MASALAH HUKUM — identifikasi unsur perbuatan dalam query.
2. DASAR HUKUM UTAMA — pasal yang ISI TEKSNYA benar-benar mengatur
   perbuatan itu; sebutkan unsur-unsurnya.
3. PASAL PENDUKUNG — pasal yang berkaitan sebab-akibat (alat bukti,
   penyertaan, pidana tambahan, acara) boleh disebut dengan alasan.
4. KESIMPULAN — terapkan unsur pada masalah; nyatakan pula bila ada
   unsur yang tidak terpenuhi atau doktrin yang relevan.
   Pasal yang isinya TIDAK membahas perbuatan dalam query JANGAN
   dinyatakan relevan — abaikan saja.
   Jika TIDAK ADA pasal yang mengatur perbuatan dalam query, jawab:
   "Tidak ditemukan pasal yang relevan dalam basis pengetahuan —
   korpus perlu diperluas." JANGAN memaksakan kesimpulan.

QUERY: {query}

PASAL TERSEDIA:
{articles}

Analisis hukum:"""


def _summarize_legal(query: str, articles: list[dict]) -> str:
    """Ringkas landasan hukum via LLM penalaran (GPU 0)."""
    if not articles:
        return ""
    art_text = "\n".join(
        f"- {a['law_name']} {a['article_number']}: {a['content'][:700]}"
        for a in articles[:8]
    )
    try:
        from app.config import get_llm_reasoning

        llm = get_llm_reasoning()
        resp = llm.invoke(_SUMMARY_PROMPT.format(
            query=query, articles=art_text[:4000]))
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        logger.warning("Ringkasan hukum gagal: %s", exc)
        return f"{len(articles)} pasal relevan ditemukan."


_CITE_RE = re.compile(r"Pasal\s+(\d+[A-Za-z]?)")
_WORD_RE = re.compile(r"[a-zA-Z]{5,}")
_SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+")

_FIDELITY_STOPS = frozenset(
    "pasal ayat undang nomor tahun republik indonesia tentang yang "
    "dalam dengan atas untuk atau pada dari oleh bagi tersebut ini "
    "adalah tidak dapat akan telah sebagaimana dimaksud berdasarkan "
    "masalah hukum dasar utama pendukung kesimpulan".split())


_LAW_YEAR_RE = re.compile(r"Tahun\s+(\d{4})", re.IGNORECASE)
_EVENT_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Identitas peraturan ("UU No 8 Tahun 1981", "UU 19/2016",
# "Peraturan Pemerintah No 71 Tahun 2019") — tahun di sini adalah
# tahun TERBIT aturan, BUKAN tahun peristiwa. Harus dilucuti dari
# query sebelum menambang tahun peristiwa, atau UU yang disebut
# menghasilkan false-positive anakronisme untuk dirinya sendiri.
_LAW_CITE_RE = re.compile(
    r"(?:undang[-\s]undang|uu|peraturan\s+\w+|pp|perppu|perda|permen"
    r"|perpres|perkap|perja|perpol)\s+"
    r"(?:no(?:mor)?\.?\s*)?\d{1,3}\s*(?:tahun|/)\s*\d{4}",
    re.IGNORECASE)


def _event_years_of(query: str) -> list[int]:
    """Tahun peristiwa dari query — setelah referensi peraturan
    dilucuti. Multi-tahun → tahun paling awal (peristiwa pertama)."""
    masked = _LAW_CITE_RE.sub(" ", query or "")
    return sorted({
        int(y) for y in _EVENT_YEAR_RE.findall(masked)
        if 1945 <= int(y) <= 2100})


def _audit_citations(summary: str, articles: list[dict],
                     query: str = "") -> dict:
    """Audit sitasi pasca-generasi (pola reference-audit) — tiga sumbu
    deterministik (adopsi pola legal-agent/regulated-rag):

    1. EKSISTENSI: tiap 'Pasal N' yang disebut jawaban harus ada di
       korpus yang di-retrieve.
    2. FIDELITY: kalimat yang menyitasi pasal harus berbagi kata isi
       dengan bunyi pasal itu — menangkap sitasi yang ada tapi
       dipakai untuk klaim yang tidak didukung teksnya.
    3. TEMPORAL: jika query menyebut tahun peristiwa, pasal dari UU
       yang berlaku SETELAH tahun itu adalah anakronisme — hukum
       dievaluasi pada versi yang berlaku saat peristiwa terjadi.
    """
    art_by_no: dict[str, str] = {}
    law_year_by_no: dict[str, int] = {}
    for a in articles:
        no = str(a.get("article_number", "")).split()[-1].lstrip("0") or "0"
        art_by_no[no] = a.get("content", "")
        ym = _LAW_YEAR_RE.search(str(a.get("law_name", "")))
        if ym:
            law_year_by_no[no] = int(ym.group(1))
    cited = {m.lstrip("0") or "0" for m in _CITE_RE.findall(summary or "")}
    unverified = sorted(cited - set(art_by_no))

    # Fidelity per kalimat yang menyitasi pasal terverifikasi
    weak = []
    for sent in _SENT_SPLIT.split(summary or ""):
        nums = {m.lstrip("0") or "0" for m in _CITE_RE.findall(sent)}
        for n in nums & set(art_by_no):
            claim_words = {
                w for w in _WORD_RE.findall(sent.lower())
                if w not in _FIDELITY_STOPS
            }
            if not claim_words:
                continue
            body = art_by_no[n].lower()
            cov = sum(1 for w in claim_words if w in body) / len(claim_words)
            if cov < 0.34:
                weak.append(f"Pasal {n}")

    # Sumbu temporal — tahun peristiwa dari query vs tahun UU pasal
    # yang tersitasi. Tahun identitas peraturan sudah dilucuti agar
    # menyebut "UU 1/2023" tidak dianggap tahun peristiwa.
    event_years = _event_years_of(query)
    anachronisms: list[str] = []
    if event_years:
        event_year = min(event_years)
        for sent in _SENT_SPLIT.split(summary or ""):
            for n in {m.lstrip("0") or "0" for m in _CITE_RE.findall(sent)}:
                ly = law_year_by_no.get(n)
                if ly and ly > event_year:
                    anachronisms.append(
                        f"Pasal {n} (UU {ly} > peristiwa {event_year})")
    return {
        "cited": len(cited),
        "verified": len(cited) - len(unverified),
        "unverified_articles": [f"Pasal {n}" for n in unverified],
        "low_fidelity": sorted(set(weak)),
        "anachronisms": sorted(set(anachronisms)),
    }


def _log_retrieval(articles: list[dict], cited_nums: set[str]) -> None:
    """Catat agregat penggunaan pasal — umpan balik pembelajaran untuk
    boost retrieval berikutnya. HANYA agregat (law, pasal, cited) —
    teks query tidak disimpan (privasi tenant)."""
    if not articles:
        return
    try:
        from app.database.postgres import SessionLocal
        from sqlalchemy import text

        with SessionLocal() as db:
            # Tabel dibuat init_db oleh role admin — ala_app tak punya
            # CREATE privilege; runtime hanya INSERT/SELECT.
            for a in articles:
                no = str(a.get("article_number", "")).split()[-1] \
                    .lstrip("0") or "0"
                db.execute(text(
                    "INSERT INTO retrieval_feedback "
                    "(law_name, article_number, cited) "
                    "VALUES (:ln, :an, :c)"),
                    {"ln": a["law_name"], "an": a["article_number"],
                     "c": no in cited_nums})
            db.commit()
    except Exception as exc:
        logger.debug("Feedback retrieval tidak tercatat: %s", exc)


def legal_foundation_agent(state) -> dict:
    """Node LangGraph: retrieval hukum dari basis pengetahuan GLOBAL."""
    audit = {
        "agent": "legal_foundation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    updates: dict = {"audit_trail": [audit]}
    query = state.get("query", "")
    budget = state.get("context_token_budget") or 2048

    try:
        articles = _rag_retrieve(query)
        xrefs = _graph_xrefs(query)
        articles = _dedup_articles(articles, budget)
        # Abstention (pola regulated-rag/policyproof): jika bukti lemah
        # — tidak ada pasal, atau skor teratas di bawah ambang, atau
        # SEMUA sitasi tak terverifikasi — sistem menolak menjawab
        # daripada memaksakan analisis tanpa pijakan.
        top_score = max((a.get("relevance_score", 0) for a in articles),
                        default=0.0)
        sufficient = bool(articles) and top_score >= 0.55
        if not articles:
            summary = ("⌀ ABSTAIN — tidak ditemukan pasal relevan dalam "
                       "basis pengetahuan; korpus perlu diperluas "
                       "sebelum analisis dapat dipercaya.")
        elif not sufficient:
            summary = (f"⌀ ABSTAIN — bukti terbaik hanya skor "
                       f"{top_score:.2f} (<0.55); pasal yang di-retrieve "
                       f"kemungkinan tidak menjawab pertanyaan ini.")
            audit["abstained"] = "weak_evidence"
        else:
            summary = _summarize_legal(query, articles)
        # Verifikasi sitasi jawaban terhadap korpus — konversi
        # halusinasi diam menjadi peringatan eksplisit.
        cite = _audit_citations(summary, articles, query)
        audit["citation_audit"] = cite
        if (sufficient and cite["cited"] >= 2
                and cite["verified"] == 0):
            # Grounding-bound (regulated-rag): semua sitasi di luar
            # set retrieval → jawaban tak dapat dipercaya.
            summary = ("⌀ ABSTAIN — semua sitasi yang dihasilkan tidak "
                       "ada dalam pasal yang di-retrieve; jawaban "
                       "ditolak karena tidak ter-grounding.")
            audit["abstained"] = "ungrounded_citations"
        if cite["unverified_articles"] and not audit.get("abstained"):
            summary += (
                "\n\n⚠ Verifikasi sitasi: "
                + ", ".join(cite["unverified_articles"])
                + " tidak ditemukan dalam korpus — perlu verifikasi "
                  "manual sebelum digunakan.")
        if cite.get("low_fidelity"):
            summary += (
                "\n⚠ Fidelity rendah: sitasi "
                + ", ".join(cite["low_fidelity"])
                + " ada di korpus namun bunyi pasalnya tidak jelas "
                  "mendukung klaim — baca teks aslinya.")
        if cite.get("anachronisms"):
            summary += (
                "\n⚠ Anakronisme temporal: "
                + ", ".join(cite["anachronisms"])
                + " — UU ini berlaku SETELAH tahun peristiwa; "
                  "evaluasi harus memakai versi yang berlaku saat itu.")
        cited_nums = {
            m.lstrip("0") or "0" for m in _CITE_RE.findall(summary or "")
        } - {
            u.split()[-1].lstrip("0") for u in cite["unverified_articles"]
        }
        _log_retrieval(articles, cited_nums)
    except Exception as exc:
        logger.exception("Legal Foundation error")
        audit.update(status="error", error=str(exc))
        updates["errors"] = [f"Legal Foundation Agent error: {exc}"]
        updates["legal_articles"] = []
        updates["cross_references"] = []
        updates["legal_summary"] = ""
        return updates

    updates["legal_articles"] = articles
    updates["cross_references"] = xrefs
    updates["legal_summary"] = summary
    audit.update(
        status="success",
        articles_found=len(articles),
        cross_references=len(xrefs),
        token_budget=budget,
    )
    return updates
