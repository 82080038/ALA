"""
Autonomous Ingestor — ALCD Fase 2c.

Memotong teks hukum menjadi chunks, menghasilkan embedding lokal via
sentence-transformers, dan menyimpan ke koleksi ChromaDB GLOBAL
`indonesian_laws` (TANPA institution_id — pengetahuan hukum dibagikan
semua institusi). Setiap dokumen dicatat di `knowledge_registry`.
"""
import hashlib
import logging
from datetime import datetime, timezone

from app.config import get_embedding_device, settings

logger = logging.getLogger("ala.alcd.ingestor")

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_embedder = None


def _get_embedder():
    """Lazy-load model embedding (CPU/GPU sesuai HIRO)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(
            _EMBED_MODEL.split("/")[-1], device=get_embedding_device()
        )
    return _embedder


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Potong teks menjadi chunks 500 char dengan overlap 50."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
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
    embedder = _get_embedder()

    ids, docs, metas = [], [], []
    for article in parsed["articles"]:
        chunks = chunk_text(article["content"])
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
            })

    if not ids:
        return {"law_name": law_name, "chunks": 0, "articles": 0,
                "status": "failed"}

    embeddings = embedder.encode(docs, show_progress_bar=False).tolist()
    # ChromaDB upsert — idempotent untuk re-ingestion
    collection.upsert(ids=ids, documents=docs, metadatas=metas,
                      embeddings=embeddings)
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
        law_name=result["law_name"],
        law_category=law_category,
        source_url=parsed["source_url"],
        source_domain=parsed["source_url"].split("/")[2]
        if "://" in parsed["source_url"] else "",
        ingestion_status=result["status"],
        chunk_count=result["chunks"],
        article_count=result["articles"],
        verification_score=1.0 if verified else 0.5,
        metadata_={"chapter_count": parsed.get("chapter_count", 0)},
    )
    db.add(entry)
    db.commit()
