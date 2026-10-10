"""
Autonomous Ingestor — ALCD Fase 2c.

Memotong teks hukum menjadi chunks, menghasilkan embedding lokal via
sentence-transformers, dan menyimpan ke koleksi ChromaDB GLOBAL
`indonesian_laws` (TANPA institution_id — pengetahuan hukum dibagikan
semua institusi). Setiap dokumen dicatat di `knowledge_registry`.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone

from app.config import get_embedding_device, settings

logger = logging.getLogger("ala.alcd.ingestor")

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
# Batas chunk per satu artikel/seksi — putusan MA dengan transkrip
# fakta ratusan halaman (ratusan ribu chunk) menggantung embedding
# CPU belasan menit per dokumen; 200 chunk ≈ 100KB teks.
_MAX_CHUNKS_PER_ARTICLE = 200
# Multilingual-E5 — retrieval terbaik untuk bahasa Indonesia dari model
# yang muat di hardware (384-dim, 118M param). Wajib prefix asimetris:
# "query: " untuk pencarian, "passage: " untuk dokumen (spec E5).
# CATATAN: menyimpang dari DEVIN_PROMPT yang mengunci all-MiniLM-L6-v2 —
# L6 English-centric terbukti menghasilkan skor relevansi ~0 untuk
# teks hukum Indonesia; kualitas retrieval menang atas kaku spesifikasi.
# Model dikonfigurasi via settings.embedding_model — ganti model =
# ruang vektor berubah → WAJIB re-embed seluruh koleksi.
_EMBED_MODEL = None


def _embed_model_name() -> str:
    return _EMBED_MODEL or settings.embedding_model


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed dokumen/passage dengan prefix E5 wajib."""
    return _get_embedder().encode(
        ["passage: " + t for t in texts], show_progress_bar=False
    ).tolist()


def embed_query(query: str) -> list[float]:
    """Embed satu query pencarian dengan prefix E5 wajib."""
    return _get_embedder().encode("query: " + query).tolist()

_embedder = None


def _get_embedder():
    """Lazy-load model embedding (CPU/GPU sesuai HIRO)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(
            _embed_model_name(), device=get_embedding_device()
        )
    return _embedder


def chunk_text(text: str, size: int = _CHUNK_SIZE,
               overlap: int = _CHUNK_OVERLAP,
               limit: int | None = None) -> list[str]:
    """Potong teks menjadi chunks 500 char dengan overlap 50.
    `limit` menghentikan pemotongan lebih awal — teks patologis
    (ratusan MB) tidak dimaterialisasi penuh ke memori."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
            if limit is not None and len(chunks) >= limit:
                break
        start += size - overlap
    return chunks


def _doc_id(law_name: str, article_number: str, chunk_index: int) -> str:
    raw = f"{law_name}|{article_number}|{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def ingest_parsed_document(
    parsed: dict,
    law_category: str = "materiil",
    verified: bool = False,
) -> dict:
    """Embed + simpan dokumen terparse ke ChromaDB GLOBAL.

    Args:
        parsed: output DocumentParser.parse() —
            `{"law_name", "articles", "source_url"}`.
        law_category: materiil | formil | regulasi | yurisprudensi.
        verified: terverifikasi lintas ≥2 sumber.

    Returns:
        `{"law_name", "chunks", "articles", "status"}` untuk registry.
    """
    law_name = parsed["law_name"]
    from app.database.chroma import get_chroma_client, get_laws_collection

    collection = get_laws_collection(get_chroma_client())

    ids, docs, metas = [], [], []
    truncated = 0
    for article in parsed["articles"]:
        # Batas per-artikel: seksi patologis (transkrip fakta putusan
        # ratusan halaman) tetap masuk tetapi tidak menghabiskan
        # belasan menit chunking+embedding CPU — kepalanya cukup
        # untuk retrieval. limit di-pass agar daftar chunk tidak
        # dimaterialisasi penuh dari teks multi-MB.
        if len(article["content"]) > _MAX_CHUNKS_PER_ARTICLE * _CHUNK_SIZE:
            truncated += len(article["content"]) // _CHUNK_SIZE
        chunks = chunk_text(article["content"],
                            limit=_MAX_CHUNKS_PER_ARTICLE)
        # Skema unsur delik — pasal pidana membawa struktur
        # pelaku/perbuatan/sikap batin/ancaman yang dapat dibaca mesin.
        from app.agents.alcd.element_parser import extract_elements

        elements = extract_elements(article["content"])
        for i, chunk in enumerate(chunks):
            ids.append(_doc_id(law_name, article["article_number"], i))
            docs.append(chunk)
            metas.append({
                "law_name": law_name,
                "article_number": article["article_number"],
                "topic": article.get("title", ""),
                "law_category": law_category,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "source_url": parsed["source_url"],
                "discovery_date": datetime.now(timezone.utc).date().isoformat(),
                "verified": verified,
                # TIDAK ada institution_id — namespace GLOBAL
                **({"elements": json.dumps(elements,
                                           ensure_ascii=False)}
                   if elements else {}),
            })

    if not ids:
        return {"law_name": law_name, "chunks": 0, "articles": 0,
                "status": "failed"}

    embeddings = embed_documents(docs)
    # ChromaDB upsert — idempotent untuk re-ingestion
    collection.upsert(ids=ids, documents=docs, metadatas=metas,
                      embeddings=embeddings)
    # Indeks BM25 kini basi — invalidate (cache + snapshot disk) agar
    # rebuild pada query berikutnya, bukan membaca data usang.
    try:
        from app.agents.legal_foundation import invalidate_lexical_index

        invalidate_lexical_index()
    except Exception:
        pass
    if truncated:
        logger.warning("Ingest %s: %d chunk dipangkas (batas %d/artikel)",
                       law_name, truncated, _MAX_CHUNKS_PER_ARTICLE)
    logger.info("Ingest %s: %d artikel, %d chunks", law_name,
                len(parsed["articles"]), len(ids))
    return {
        "law_name": law_name,
        "chunks": len(ids),
        "articles": len(parsed["articles"]),
        "status": "completed",
    }


def register_knowledge(db, parsed: dict, result: dict, law_category: str,
                       verified: bool) -> None:
    """Catat hasil ingestion ke tabel knowledge_registry (GLOBAL)."""
    from app.models.operational import KnowledgeRegistry

    entry = KnowledgeRegistry(
        law_name=result["law_name"][:255],
        law_number=parsed.get("law_number"),
        law_category=law_category,
        source_url=parsed["source_url"],
        source_domain=parsed["source_url"].split("/")[2]
        if "://" in parsed["source_url"] else "",
        ingestion_status=result["status"],
        chunk_count=result["chunks"],
        article_count=result["articles"],
        verification_score=1.0 if verified else 0.5,
        metadata_={
            "chapter_count": parsed.get("chapter_count", 0),
            "law_year": parsed.get("law_year"),
            "law_subject": parsed.get("law_subject"),
            "source_status": parsed.get("source_status"),
            "amends": parsed.get("amends") or [],
            "revokes": parsed.get("revokes") or [],
            "amended_by": parsed.get("amended_by") or [],
        },
    )
    db.add(entry)
    db.commit()
