"""
Autonomous Legal Curriculum Designer (ALCD) — Agent 0.

Membangun basis pengetahuan hukum dari NOL DATA sebelum query pengguna
diproses. Pipeline: ontologi → akuisisi (discover → download → parse →
verify) → ingest (chunk → embed → ChromaDB GLOBAL) → graph (Neo4j GLOBAL)
→ evaluasi diri → registrasi.

Seluruh output pengetahuan berada di namespace GLOBAL — dibagikan ke
SEMUA institusi (tanpa institution_id).
"""
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.agents.alcd.document_parser import DocumentParser
from app.agents.alcd.ontology_generator import CORE_OBJECTIVE, generate_ontology
from app.agents.alcd.source_discoverer import SourceDiscoverer
from app.config import get_llm_reasoning, settings

logger = logging.getLogger("ala.agents.alcd")

_MAX_SOURCES_PER_NODE = 3      # batas dokumen per node ontologi
_MAX_BOOTSTRAP_NODES = 10      # batas node per siklus bootstrap


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

def check_readiness(db) -> dict:
    """Hitung skor kesiapan pengetahuan dari ontology_nodes + registry."""
    from app.models.operational import KnowledgeRegistry, OntologyNode

    total_nodes = db.scalar(select(func.count(OntologyNode.id))) or 0
    laws_done = db.scalar(
        select(func.count(KnowledgeRegistry.id)).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
    ) or 0
    avg_score = db.scalar(select(func.avg(OntologyNode.knowledge_score))) or 0.0

    if total_nodes == 0:
        score = 0.0
    else:
        score = min(1.0, (avg_score * 0.6) + (min(laws_done, 8) / 8 * 0.4))

    return {
        "knowledge_ready": score >= settings.alcd_min_readiness_score,
        "knowledge_score": round(score, 3),
        "ontology_nodes": total_nodes,
        "laws_ingested": laws_done,
    }


# ---------------------------------------------------------------------------
# Fase kurikulum: LLM menalar UU spesifik yang harus dipelajari per node
# ---------------------------------------------------------------------------

_PLAN_PROMPT = """Anda adalah kurator hukum Indonesia. Untuk topik "{topic}"
(deskripsi: {desc}), daftar NAMA Undang-Undang yang WAJIB dikuasai sistem
legal-intelligence APH.

Balas HANYA JSON array valid — tanpa teks lain:
["nama UU 1", "nama UU 2"]

Aturan:
- Tulis NAMA hukumnya saja (contoh: "Kitab Undang-Undang Hukum Pidana",
  "Undang-Undang Informasi dan Transaksi Elektronik") — nomor/tahun akan
  diverifikasi sendiri oleh sistem terhadap dokumen resmi, jangan ditebak
- Hanya nama UU/peraturan yang benar-benar ada di Indonesia
- Maksimal 4 nama"""


def _plan_laws(llm, node: dict) -> list[dict]:
    """LLM menalar NAMA UU yang perlu dipelajari untuk satu node ontologi.

    Identitas (nomor/tahun) sengaja TIDAK diminta ke LLM — model kecil
    salah menebaknya. Identitas diturunkan dari dokumen resmi saat
    discovery, lalu diverifikasi silang terhadap isi teks.
    """
    import json
    import re

    topic = node.get("subcategory") or node.get("category", "")
    desc = node.get("description", "")
    out: list[str] = []
    try:
        resp = llm.invoke(_PLAN_PROMPT.format(topic=topic, desc=desc))
        text = resp.content if hasattr(resp, "content") else str(resp)
        m = re.search(r"\[.*\]", text, flags=re.DOTALL)
        items = json.loads(m.group(0)) if m else []
        out = [str(t) for t in items if isinstance(t, str)]
    except Exception as exc:
        logger.warning("Perencanaan kurikulum gagal untuk %s: %s", topic, exc)
    # Subkategori node SELALU dicari — ekspansi akronim ke nama resmi
    # (normalisasi linguistik, bukan preloading dokumen). LLM 3B sering
    # lupa memasukkan UU kanonik node-nya sendiri.
    canonical = _CANONICAL_LAW_NAMES.get(topic.strip().lower())
    primary = canonical or topic
    if primary and primary.lower() not in {t.lower() for t in out}:
        out.insert(0, primary)
    if out:
        logger.info("Kurikulum %s: %s", topic, out)
    return out[:4]


# Akronim → nama resmi UU (normalisasi kata kunci pencarian)
_CANONICAL_LAW_NAMES = {
    "kuhp": "Kitab Undang-Undang Hukum Pidana",
    "kuhap": "Kitab Undang-Undang Hukum Acara Pidana",
    "uu ite": "Undang-Undang Informasi dan Transaksi Elektronik",
    "uu tipikor": "Undang-Undang Pemberantasan Tindak Pidana Korupsi",
    "uu tppu": "Undang-Undang Pencegahan dan Pemberantasan "
               "Tindak Pidana Pencucian Uang",
    "uu narkotika": "Undang-Undang Narkotika",
    "uu tppo": "Undang-Undang Pemberantasan Tindak Pidana "
              "Perdagangan Orang",
    "uu kdrt": "Undang-Undang Penghapusan Kekerasan "
              "dalam Rumah Tangga",
    "uu tpks": "Undang-Undang Tindak Pidana Kekerasan Seksual",
    "uu perlindungan anak": "Undang-Undang Perlindungan Anak",
    "putusan ma": "Putusan Mahkamah Agung",
}


def _verify_law(parsed: dict, number: str | None, year: str | None) -> bool:
    """Verifikasi silang identitas dokumen: identitas dari metadata
    sumber (filename/slug URL) HARUS cocok dengan NOMOR/TAHUN di blok
    judul isi teks. Kandidat tanpa identitas sumber tidak dapat
    diverifikasi → ditolak."""
    if not number or not year:
        return False
    pnum = (parsed.get("law_number") or "").lstrip("0")
    pyr = parsed.get("law_year") or ""
    if not (pnum and pyr):
        return False
    return pnum == number.lstrip("0") and pyr == year


_TITLE_STOPWORDS = {
    "undang", "republik", "indonesia", "nomor", "tahun", "tentang",
    "peraturan", "pemerintah", "negara", "perubahan", "atas", "dalam",
    "tindak",
}


def _topic_keywords(text: str) -> list[str]:
    """Kata khas (≥5 huruf, bukan stopword) dari sebuah topik/judul."""
    return [w for w in re.findall(r"[a-zA-Z]{5,}", text.lower())
            if w not in _TITLE_STOPWORDS]


def _canonical_keywords() -> dict[str, set[str]]:
    return {
        k: set(_topic_keywords(v)) for k, v in _CANONICAL_LAW_NAMES.items()
    }


def _discriminating_words() -> dict[str, set[str]]:
    """Kata pembeda tiap node kanonik — kata yang hanya muncul di SATU
    ekspansi kanonik. Ambang 60% saja bocor: subjek "Pemberantasan
    Tindak Pidana Pendanaan Terorisme" (UU 9/2013 PPPT) dan TPPO
    (UU 21/2007) sama-sama menang 'pemberantasan'+'pidana' sehingga
    dulu tertempel di node TIPIKOR. Kata pembeda ('korupsi',
    'perdagangan', 'pencucian', 'elektronik', …) kini WAJIB ada."""
    kw = _canonical_keywords()
    freq: dict[str, int] = {}
    for words in kw.values():
        for w in words:
            freq[w] = freq.get(w, 0) + 1
    return {
        k: {w for w in words if freq[w] == 1}
        for k, words in kw.items()
    }


_DISCRIMINATORS = _discriminating_words()


def _subject_match(node_topic: str, title: str, parsed: dict) -> bool:
    """Verifikasi topik dokumen terhadap NODE ontologi — bukan judul
    rencana LLM (yang sering halusinasi dan menemukan dokumen tak
    relevan). Kata khas topik harus tampak di SUBJEK dokumen (klausa
    TENTANG hasil parse) — isi pasal boleh menyebut istilah apa pun dan
    mengecoh pencocokan berbasis isi.

    Node kanonik: ketat — ≥60% kata khas node DAN semua kata pembeda
    wajib muncul. Node generik: subjek cocok node ATAU judul rencana
    kurikulumnya sendiri."""
    key = node_topic.strip().lower()
    canonical = _CANONICAL_LAW_NAMES.get(key)
    subject = (parsed.get("law_subject") or "").lower()
    # Fallback: kolom "Subjek" halaman Details BPK (sumber resmi) ikut
    # dipertimbangkan saat klausa TENTANG tidak terbaca (mis. hasil OCR
    # scan yang imperfek).
    probe = (subject or (parsed.get("source_subject") or "").lower()
             or (parsed.get("law_name") or "").lower())

    def _covers(topic_words: list[str]) -> bool:
        if not topic_words:
            return False
        hits = sum(1 for w in topic_words if w in probe)
        need = max(1, math.ceil(len(topic_words) * 0.6))
        return hits >= need

    if canonical:
        node_words = _topic_keywords(canonical)
        disc = _DISCRIMINATORS.get(key, set())
        return _covers(node_words) and all(w in probe for w in disc)
    # '/' pada topik adalah ALTERNATIF ("perkap/perja" cocok untuk
    # dokumen Perkap saja ATAU Perja saja) — tanpa ini sebuah Perkap
    # murni mustahil memenuhi kedua kata sekaligus.
    alt_groups = [_topic_keywords(t) for t in node_topic.split("/")]
    if any(_covers(g) for g in alt_groups if g):
        return True
    # Sinonim bentuk peraturan untuk topik Perkap/Perja — teks resmi
    # menulis "Peraturan Kepolisian Negara RI", bukan singkatan.
    if key == "perkap/perja" and (
            "peraturan kepolisian" in probe or "peraturan polri" in probe):
        return True
    # Node generik: subjek cocok node ATAU judul rencana kurikulum.
    return _covers(_topic_keywords(node_topic)) or _covers(
        _topic_keywords(title))


# ---------------------------------------------------------------------------
# Fase akuisisi per node: kurikulum → temukan → verifikasi → ingest
# ---------------------------------------------------------------------------

def _acquire_node(node: dict, discoverer: SourceDiscoverer,
                  parser: DocumentParser, db, llm=None) -> dict:
    """Untuk setiap UU yang direncanakan LLM: temukan dokumen resminya,
    unduh+parse, VERIFIKASI identitasnya, baru ingest + graph."""
    from app.agents.alcd.autonomous_ingestor import (
        ingest_parsed_document,
        register_knowledge,
    )
    from app.agents.alcd.graph_builder import build_graph_for_document
    from app.models.operational import KnowledgeRegistry

    topic = node.get("subcategory") or node.get("category", "")
    # Node doktrin diisi oleh seed_doctrine (gloss konseptual), bukan
    # crawl UU — LLM akan merencanakan judul tak relevan di sini.
    if _NODE_CATEGORY_HINT.get(topic.strip().lower()) == "doktrin":
        return {"topic": topic, "parsed": [], "chunks": 0,
                "articles": 0, "gaps": []}
    law_category = (
        "formil" if "formil" in (node.get("category") or "").lower()
        else "yurisprudensi" if "yurisprudensi" in (node.get("category") or "").lower()
        else "regulasi" if "regulasi" in (node.get("category") or "").lower()
        else "materiil"
    )
    result = {"topic": topic, "parsed": [], "chunks": 0, "articles": 0,
              "gaps": []}

    planned_titles = _plan_laws(llm, node) if llm else []
    if not planned_titles:
        logger.warning("Tidak ada rencana UU untuk %s", topic)
        result["gaps"].append("kurikulum kosong")
        return result

    # Node kanonik: buang judul rencana yang tak berbagi kata khas dengan
    # node — LLM 3B kerap merencanakan UU asing ("UU Perlindungan Hutan"
    # di bawah node Tipikor) yang lalu menemukan dokumen tak relevan.
    canonical = _CANONICAL_LAW_NAMES.get(topic.strip().lower())
    if canonical:
        node_words = set(_topic_keywords(canonical))
        planned_titles = [
            t for t in planned_titles
            if set(_topic_keywords(t)) & node_words
        ]
        if not planned_titles:
            planned_titles = [canonical]
    _report("plan", topic, " · ".join(planned_titles[:3]))

    seen_laws: set[tuple[str, str]] = set()
    for title in planned_titles:
        if len(result["parsed"]) >= _MAX_SOURCES_PER_NODE:
            break
        for cand in discoverer.find_law(title)[:5]:
            if len(result["parsed"]) >= _MAX_SOURCES_PER_NODE:
                break
            url = cand["url"]
            # Identitas ekspektasi dari metadata sumber (filename/slug)
            exp_num = cand.get("law_number")
            exp_year = cand.get("law_year")
            if exp_num and (exp_num, exp_year) in seen_laws:
                continue
            _report("fetch", topic,
                    url.split("?")[0].rsplit("/", 1)[-1][:60],
                    len(result["parsed"]), _MAX_SOURCES_PER_NODE)
            parsed = parser.parse(url)
            if not parsed or len(parsed["articles"]) < 5:
                # <5 pasal → kemungkinan scan tanpa text-layer / bukan UU
                _report("reject", topic, "bukan dokumen UU utuh",
                        len(result["parsed"]), _MAX_SOURCES_PER_NODE)
                continue
            _report("parse", topic,
                    f"{len(parsed['articles'])} pasal terdeteksi",
                    len(result["parsed"]), _MAX_SOURCES_PER_NODE)
            if not _verify_law(parsed, exp_num, exp_year):
                logger.info(
                    "Tolak %s — identitas dokumen (UU %s/%s) tidak cocok "
                    "dengan sumber (UU %s/%s)", url,
                    parsed.get("law_number"), parsed.get("law_year"),
                    exp_num, exp_year)
                _report("reject", topic,
                        f"identitas {parsed.get('law_number')}/"
                        f"{parsed.get('law_year')} ≠ {exp_num}/{exp_year}")
                continue
            if not _subject_match(topic, title, parsed):
                logger.info(
                    "Tolak %s — subjek dokumen '%s' tidak cocok topik "
                    "node '%s'", url,
                    parsed.get("law_subject") or parsed.get("law_name"),
                    topic)
                _report("reject", topic,
                        f"subjek '{(parsed.get('law_subject') or '?')[:40]}' "
                        "≠ topik")
                continue
            # Temporalitas: status resmi "Dicabut / Tidak Berlaku" dari
            # halaman Details BPK → dokumen usang tidak masuk korpus.
            src_status = (parsed.get("source_status") or "").lower()
            if "dicabut" in src_status or "tidak berlaku" in src_status:
                logger.info("Tolak %s — status '%s' (usang)",
                            url, parsed.get("source_status"))
                _report("reject", topic,
                        f"status: {parsed.get('source_status')}")
                continue
            key = (parsed.get("law_number") or "", parsed.get("law_year") or "")
            if key in seen_laws:
                continue
            # Dedupe lintas-kanal: identitas yang sudah masuk korpus via
            # impor eksternal (SPKT/LexisAI) tidak perlu diunduh ulang.
            if key in _registry_law_ids(db):
                result["parsed"].append(
                    f"{parsed['law_name']} (sudah ada)")
                continue
            seen_laws.add(key)
            # Label dari SUBJEK dokumen (klausa TENTANG) — jujur apa isi
            # UU; judul rencana LLM tidak ditampelkan karena sering
            # halusinasi ("UU 35/2010" yang tidak ada).
            if parsed.get("law_number") and parsed.get("law_year"):
                subj = parsed.get("law_subject") or title
                parsed["law_name"] = (
                    f"UU Nomor {parsed['law_number']} Tahun "
                    f"{parsed['law_year']} tentang {subj}")
            parsed["trusted"] = cand.get("trusted", False)
            # Lewati jika dokumen ini sudah teregistrasi (antar-siklus)
            already = db.scalar(
                select(KnowledgeRegistry.id).where(
                    KnowledgeRegistry.source_url == parsed["source_url"],
                    KnowledgeRegistry.ingestion_status.in_(
                        ["completed", "verified"]),
                )
            )
            if already:
                result["parsed"].append(f"{parsed['law_name']} (sudah ada)")
                continue
            try:
                res = ingest_parsed_document(parsed, law_category, True)
                register_knowledge(db, parsed, res, law_category, True)
                _report("ingest", topic, res["law_name"][:60],
                        len(result["parsed"]) + 1, _MAX_SOURCES_PER_NODE)
                build_graph_for_document(res["law_name"], parsed["articles"])
                _report("graph", topic, res["law_name"][:60],
                        len(result["parsed"]) + 1, _MAX_SOURCES_PER_NODE)
                result["chunks"] += res["chunks"]
                result["articles"] += res["articles"]
                result["parsed"].append(res["law_name"])
            except Exception as exc:
                logger.warning("Ingest gagal %s: %s", url, exc)
    if not result["parsed"]:
        result["gaps"].append(
            f"tidak ada dokumen terverifikasi untuk {planned_titles}")
    return result


# ---------------------------------------------------------------------------
# Bootstrap penuh
# ---------------------------------------------------------------------------

# Guard global: satu bootstrap aktif per proses — dipakai BERSAMA oleh job
# /alcd/trigger dan node alcd di pipeline analyze (sebelumnya query
# pengguna memicu bootstrap kedua yang berjalan konkuren).
_BOOTSTRAP_LOCK = threading.Lock()

# Progres live — dibaca endpoint /alcd/progress agar UI menyorot wilayah
# yang SEDANG diproses (kamera & neural.log mengikuti kerja nyata).
# done/total memberi persentase nyata; stage_started menopang ETA.
_PROGRESS: dict = {"stage": None, "topic": None, "detail": "", "ts": 0.0,
                   "done": None, "total": None, "stage_started": 0.0}


def _report(stage: str, topic: str | None = None, detail: str = "",
            done: int | None = None, total: int | None = None) -> None:
    now = time.time()
    if stage != _PROGRESS.get("stage"):
        _PROGRESS["stage_started"] = now
    _PROGRESS.update(stage=stage, topic=topic, detail=detail, ts=now,
                     done=done, total=total)


def current_progress() -> dict:
    p = {**_PROGRESS, "running": _BOOTSTRAP_LOCK.locked()}
    started = p.get("stage_started") or p.get("ts") or time.time()
    elapsed = max(0.0, time.time() - started)
    p["elapsed_s"] = round(elapsed)
    done, total = p.get("done"), p.get("total")
    # ETA hanya saat ada kemajuan nyata — bukan tebakan
    p["eta_s"] = (
        round(elapsed / done * (total - done))
        if done and total and done < total else None
    )
    return p

# Identitas UU kanonik yang DIHARAPKAN per node — kunci jawaban rubrik
# evaluasi deterministik (bukan data korpus; akuisisi tetap otonom).
# Node tanpa entri dinilai dari ketersediaan dokumen terverifikasi saja.
_EXPECTED_LAW_IDS: dict[str, set[tuple[str, str]]] = {
    "kuhp": {("1", "2023")},
    "kuhap": {("8", "1981"), ("20", "2025")},
    "uu ite": {("11", "2008"), ("19", "2016"), ("1", "2024")},
    "uu tipikor": {("31", "1999"), ("20", "2001"), ("30", "2002"),
                    ("19", "2019")},
    "uu tppu": {("8", "2010")},
    "uu narkotika": {("35", "2009")},
    "uu tppo": {("21", "2007")},
    "uu kdrt": {("23", "2004")},
    "uu tpks": {("12", "2022")},
    "uu perlindungan anak": {("23", "2002"), ("35", "2014"),
                              ("17", "2016")},
    # UU organik kelembagaan APH — dasar hierarkis seluruh Perkap/Perja.
    "uu kelembagaan aph": {("2", "2002"), ("16", "2004"),
                            ("11", "2021"), ("30", "2002"),
                            ("48", "2009")},
}


def _registry_law_ids(db) -> set[tuple[str, str]]:
    """Identitas (nomor, tahun) semua dokumen teregistrasi — dari kolom
    law_number/law_year registry, fallback parse law_name."""
    from app.models.operational import KnowledgeRegistry

    ids: set[tuple[str, str]] = set()
    rows = db.scalars(
        select(KnowledgeRegistry).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
    ).all()
    for r in rows:
        num = (r.law_number or "").lstrip("0")
        year = (r.metadata_ or {}).get("law_year") if r.metadata_ else None
        if num and year:
            ids.add((num, str(year)))
            continue
        m = re.search(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})", r.law_name or "")
        if m:
            ids.add((m.group(1).lstrip("0"), m.group(2)))
    return ids


# Kategori registry yang "milik" node non-UU — subjek doktrin/putusan
# adalah nama konsep/nomor perkara, bukan frasa topik, sehingga
# _subject_match tak menangkapnya.
_NODE_CATEGORY_HINT = {
    "doktrin & asas hukum": "doktrin",
    "putusan ma": "yurisprudensi",
}


def _node_doc_count(topic: str, db) -> int:
    """Jumlah dokumen registry yang topiknya cocok node ini — pakai
    rubric yang sama dengan verifikasi ingest (_subject_match), plus
    hint kategori registry untuk node non-UU (doktrin, putusan)."""
    from app.models.operational import KnowledgeRegistry

    rows = db.scalars(
        select(KnowledgeRegistry).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
    ).all()
    hint = _NODE_CATEGORY_HINT.get(topic.strip().lower())
    n = 0
    for r in rows:
        if hint and r.law_category == hint:
            n += 1
            continue
        parsed = {
            "law_subject": (r.metadata_ or {}).get("law_subject", "")
            if r.metadata_ else "",
            "law_name": r.law_name or "",
        }
        if _subject_match(topic, "", parsed):
            n += 1
    return n


def _deterministic_node_score(topic: str, db) -> float:
    """Skor deterministik per node — menggantikan LLM-as-judge sebagai
    driver skor (judge 3B memberi 0.977 pada korpus yang jelas salah).

    Node kanonik: 1.0 bila UU identitas yang diharapkan teregistrasi,
    0.3 bila ada dokumen node tapi bukan yang kanonik, 0.0 bila kosong.
    Node generik: 0.8 bila ada dokumen COCOK TOPIK node ini, 0.0 bila
    kosong — bukan sekadar "ada UU di korpus global" (bug sebelumnya:
    node kosong ikut skor 0.8 begitu satu UU masuk)."""
    key = topic.strip().lower()
    ids = _registry_law_ids(db)
    expected = _EXPECTED_LAW_IDS.get(key)
    if expected is not None:
        if ids & expected:
            return 1.0
        return 0.3 if _node_doc_count(topic, db) else 0.0
    return 0.8 if _node_doc_count(topic, db) else 0.0


def run_bootstrap(db, progress_cb=None) -> dict:
    """Guard global: tolak siklus kedua bila bootstrap lain berjalan."""
    if not _BOOTSTRAP_LOCK.acquire(blocking=False):
        logger.info(
            "Bootstrap ALCD lain sedang berjalan — siklus ini dilewati")
        return {"skipped": True, "knowledge_score": 0.0,
                "knowledge_ready": False, "coverage": {}, "nodes": 0}
    try:
        return _run_bootstrap_inner(db, progress_cb)
    finally:
        _BOOTSTRAP_LOCK.release()


def _run_bootstrap_inner(db, progress_cb=None) -> dict:
    """Jalankan pipeline ALCD lengkap: ontologi → akuisisi → evaluasi diri.

    Args:
        db: SQLAlchemy session.
        progress_cb: opsional callable(stage: str, detail: dict).

    Returns:
        {"knowledge_score", "coverage": {topic: {...}}, "nodes": int}
    """
    from app.agents.evaluator import evaluate_node
    from app.models.operational import OntologyNode

    def _progress(stage: str, detail: dict) -> None:
        logger.info("[ALCD] %s — %s", stage, detail)
        _report(stage, detail.get("topic"),
                str(detail.get("objective") or "")[:60])
        if progress_cb:
            progress_cb(stage, detail)

    llm = get_llm_reasoning()

    # ── Fase 1: Ontologi ────────────────────────────────────────────
    _progress("ontology", {"objective": CORE_OBJECTIVE})
    nodes = generate_ontology(llm)[:_MAX_BOOTSTRAP_NODES]

    # Simpan node ontologi (skip duplikat category+subcategory)
    from sqlalchemy import select as _select
    for n in nodes:
        exists = db.scalar(
            _select(OntologyNode.id).where(
                OntologyNode.category == n["category"],
                OntologyNode.subcategory == n.get("subcategory"),
            )
        )
        if not exists:
            db.add(OntologyNode(
                category=n["category"],
                subcategory=n.get("subcategory"),
                description=n.get("description", ""),
                priority=int(n.get("priority", 3)),
                status="pending",
            ))
    db.commit()

    # Wilayah fondasi ilmu hukum — selalu ada (belajar dulu "apa itu
    # hukum" sebelum membaca pasal), walau LLM tidak mengusulkannya.
    if not db.scalar(_select(OntologyNode.id).where(
            OntologyNode.subcategory == "Doktrin & Asas Hukum")):
        db.add(OntologyNode(
            category="Ilmu Hukum",
            subcategory="Doktrin & Asas Hukum",
            description="Fondasi ilmu hukum: asas, teori pemidanaan, "
                        "sistematika perundangan, interpretasi, peta APH",
            priority=1,
            status="pending",
        ))
        db.commit()

    db_nodes = db.scalars(
        _select(OntologyNode).order_by(OntologyNode.priority)
    ).all()

    # ── Fase 1.5: Fondasi — doktrin ilmu hukum + korpus terverifikasi ─
    from app.agents.alcd.doctrine import seed_doctrine
    from app.agents.alcd.external_corpus import import_external_corpus

    if settings.alcd_doctrine_enabled:
        _progress("doktrin", {"topic": "Doktrin & Asas Hukum"})
        try:
            seed_doctrine(db, llm, report=_report)
        except Exception as exc:
            logger.warning("Seed doktrin gagal: %s", exc)
    if settings.alcd_import_external:
        _progress("import", {"topic": "Korpus eksternal (SPKT/LexisAI)"})
        try:
            import_external_corpus(db, report=_report)
        except Exception as exc:
            logger.warning("Impor korpus eksternal gagal: %s", exc)

    # ── Fase 2: Akuisisi (crawl — mengisi celah yang tersisa) ────────
    discoverer = SourceDiscoverer()
    parser = DocumentParser()
    coverage: dict = {}

    for ni, node in enumerate(db_nodes):
        topic = node.subcategory or node.category
        _progress("acquire", {"topic": topic})
        _report("acquire", topic, f"wilayah {ni + 1}/{len(db_nodes)}",
                ni, len(db_nodes))
        try:
            res = _acquire_node(
                {"id": node.id, "category": node.category,
                 "subcategory": node.subcategory,
                 "description": node.description or ""},
                discoverer, parser, db, llm,
            )
        except Exception as exc:
            logger.warning("Akuisisi %s gagal: %s", topic, exc)
            res = {"chunks": 0, "articles": 0, "parsed": []}

        node.laws_ingested = len(res["parsed"])
        node.status = "in_progress" if res["parsed"] else "gap_detected"
        db.commit()
        coverage[topic] = {
            "laws_ingested": len(res["parsed"]),
            "chunks": res["chunks"],
            "score": 0.0,
        }

    # ── Fase 3: Evaluasi diri ───────────────────────────────────────
    from app.database.chroma import get_chroma_client, get_laws_collection

    def _rag_answer(question: str) -> str:
        # Wajib embedder yang sama dengan ingest (prefix E5 "query:").
        from app.agents.alcd.autonomous_ingestor import embed_query
        collection = get_laws_collection(get_chroma_client())
        qv = embed_query(question)
        hits = collection.query(query_embeddings=[qv], n_results=5)
        ctx = "\n".join(hits.get("documents", [[]])[0])
        resp = llm.invoke(
            f"Berdasarkan konteks hukum berikut, jawab pertanyaan.\n\n"
            f"Konteks:\n{ctx}\n\nPertanyaan: {question}\nJawaban:"
        )
        return resp.content if hasattr(resp, "content") else str(resp)

    for node in db_nodes:
        topic = node.subcategory or node.category
        _progress("self_eval", {"topic": topic})
        # Skor deterministik (identitas UU kanonik) menggerakkan
        # readiness; LLM-as-judge tetap dijalankan untuk self_eval_logs /
        # deteksi celah, tapi TIDAK lagi menentukan skor node.
        det_score = _deterministic_node_score(topic, db)
        try:
            ev = evaluate_node(
                llm,
                {"id": node.id, "category": node.category,
                 "subcategory": node.subcategory},
                _rag_answer, db,
            )
            coverage.setdefault(topic, {})["llm_judge_score"] = ev["score"]
        except Exception as exc:
            logger.warning("Self-eval %s gagal: %s", topic, exc)
        node.knowledge_score = det_score
        node.status = (
            "completed" if det_score >= settings.alcd_self_eval_threshold
            else "gap_detected"
        )
        db.commit()
        coverage.setdefault(topic, {})["score"] = det_score

    readiness = check_readiness(db)
    _progress("done", readiness)
    return {
        "knowledge_score": readiness["knowledge_score"],
        "knowledge_ready": readiness["knowledge_ready"],
        "coverage": coverage,
        "nodes": len(db_nodes),
    }


# ---------------------------------------------------------------------------
# LangGraph node — Agent 0
# ---------------------------------------------------------------------------

def alcd_agent(state) -> dict:
    """Node LangGraph: cek kesiapan; bootstrap jika belum siap."""
    from app.database.postgres import SessionLocal

    audit = {
        "agent": "alcd",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    updates: dict = {"audit_trail": [audit]}

    if not settings.alcd_enabled:
        audit.update(status="skipped", note="ALCD_ENABLED=false")
        updates["knowledge_ready"] = True
        return updates

    try:
        with SessionLocal() as db:
            readiness = check_readiness(db)
            if readiness["knowledge_ready"]:
                audit.update(
                    status="success",
                    note="Knowledge base siap; bootstrap dilewati",
                )
            else:
                result = run_bootstrap(db)
                readiness = check_readiness(db)
                audit.update(
                    status="success",
                    note=(
                        "Bootstrap sedang berjalan di job lain — dilewati"
                        if result.get("skipped")
                        else f"Bootstrap: {result['nodes']} node diproses"
                    ),
                )
    except Exception as exc:
        logger.exception("ALCD agent error")
        audit.update(status="error", error=str(exc))
        updates["errors"] = [f"ALCD Agent error: {exc}"]
        updates["knowledge_ready"] = False
        updates["knowledge_score"] = 0.0
        return updates

    updates["knowledge_ready"] = readiness["knowledge_ready"]
    updates["knowledge_score"] = readiness["knowledge_score"]
    updates["ontology_coverage"] = {
        "ontology_nodes": readiness["ontology_nodes"],
        "laws_ingested": readiness["laws_ingested"],
    }
    return updates
