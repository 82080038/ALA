#!/usr/bin/env python3
"""Backfill skema unsur delik ke seluruh korpus yang sudah tertanam.

Dua penyimpanan disentuh:
1. ChromaDB — metadata `elements` (JSON) pada chunk pasal pidana agar
   retrieval membawa struktur unsur ke synthesis.
2. Neo4j — properti `elements` pada node LegalArticle.

Strategi: paginate koleksi, kelompokkan per (law_name, article_number),
rekonstruksi teks pasal utuh (join chunk dengan dedup overlap — ancaman
sering jatuh di chunk >0), parse unsur sekali, lalu update seluruh
chunk pasal itu. Idempotent.

Jalankan:  cd backend && PYTHONPATH=. .venv/bin/python \\
              scripts/backfill_elements.py
"""
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_elements")

_PAGE = 4000


def main() -> int:
    from app.agents.alcd.element_parser import extract_elements
    from app.database.chroma import get_chroma_client, get_laws_collection
    from app.database.neo4j import get_neo4j_driver

    coll = get_laws_collection(get_chroma_client())
    total = coll.count()
    logger.info("Koleksi: %d chunk", total)

    # (law, article) → {"ids": [...], "chunks": {idx: teks}}
    articles: dict[tuple, dict] = defaultdict(lambda: {"ids": [],
                                                       "chunks": {}})
    offset = 0
    while offset < total:
        got = coll.get(limit=_PAGE, offset=offset,
                       include=["documents", "metadatas"])
        if not got["ids"]:
            break
        for did, doc, meta in zip(got["ids"], got["documents"],
                                  got["metadatas"]):
            if not meta:
                continue
            key = (meta.get("law_name"), meta.get("article_number"))
            a = articles[key]
            a["ids"].append(did)
            try:
                ci = int(meta.get("chunk_index", 0))
            except (TypeError, ValueError):
                ci = 0
            a["chunks"][ci] = doc
        offset += len(got["ids"])
        logger.info("… %d/%d chunk dipindai", min(offset, total), total)

    def _join(chunks: dict) -> str:
        """Rekonstruksi teks pasal — buang overlap antar-chunk."""
        parts = [chunks[i] for i in sorted(chunks)]
        text = parts[0] if parts else ""
        for nxt in parts[1:]:
            k = min(len(text), len(nxt), 200)
            while k > 0 and not text.endswith(nxt[:k]):
                k -= 1
            text += nxt[k:]
        return text

    logger.info("Artikel unik: %d — ekstraksi unsur…", len(articles))
    delik = {k: extract_elements(_join(a["chunks"]))
             for k, a in articles.items()}
    delik = {k: v for k, v in delik.items() if v}
    logger.info("Pasal delik terdeteksi: %d", len(delik))

    # Update metadata Chroma per-chunk (append elements ke meta lama).
    updated = 0
    for (law, art), el in delik.items():
        a = articles[(law, art)]
        el_json = json.dumps(el, ensure_ascii=False)
        # Ambil meta lama untuk melestarikan kolom lain.
        got = coll.get(ids=a["ids"], include=["metadatas"])
        metas = []
        for m in got["metadatas"]:
            m = dict(m or {})
            m["elements"] = el_json
            metas.append(m)
        coll.update(ids=a["ids"], metadatas=metas)
        updated += len(a["ids"])
        if updated % 20000 < len(a["ids"]):
            logger.info("… %d chunk Chroma diupdate", updated)
    logger.info("Chroma: %d chunk membawa unsur", updated)

    # Neo4j — set properti elements pada node pasal delik.
    try:
        driver = get_neo4j_driver()
        n = 0
        with driver.session() as s:
            for (law, art), el in delik.items():
                r = s.run(
                    "MATCH (a:LegalArticle {law_name: $ln, "
                    "article_number: $an}) "
                    "SET a.elements = $el RETURN count(a) AS c",
                    ln=law, an=art,
                    el=json.dumps(el, ensure_ascii=False))
                n += r.single()["c"]
        driver.close()
        logger.info("Neo4j: %d node membawa unsur", n)
    except Exception as exc:
        logger.warning("Neo4j skip: %s", exc)

    # Invalidate indeks BM25? tidak perlu — metadata tidak diindeks.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
