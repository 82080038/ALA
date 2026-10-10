#!/usr/bin/env python3
"""Backfill edge CITES putusan→pasal UU untuk yurisprudensi yang sudah
tertanam (hf://putusan/*). Membaca ulang parquet sumber (bukan chunk
Chroma — teks seksi utuh diperlukan untuk ekstraksi sitasi).

Jalankan:  cd backend && PYTHONPATH=. .venv/bin/python \
              scripts/link_putusan_graph.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.agents.alcd.external_corpus import _hf_putusan_documents  # noqa: E402
from app.agents.alcd.graph_builder import (  # noqa: E402
    build_law_name_map,
    extract_putusan_citations,
    link_putusan_citations,
)
from app.database.neo4j import get_neo4j_driver  # noqa: E402
from app.database.postgres import SessionLocal  # noqa: E402
from app.models.operational import KnowledgeRegistry  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("link_putusan")


def main() -> int:
    db = SessionLocal()
    try:
        # Registry adalah sumber kebenaran nama node (law_name Neo4j
        # harus identik agar edge MATCH berhasil).
        name_by_src = {
            r.source_url: r.law_name
            for r in db.scalars(
                select(KnowledgeRegistry).where(
                    KnowledgeRegistry.source_url.like("hf://putusan/%"),
                    KnowledgeRegistry.ingestion_status.in_(
                        ["completed", "verified"]),
                )
            )
        }
        law_map = build_law_name_map(db)
    finally:
        db.close()

    logger.info("Putusan teregistrasi: %d · resolver UU: %d",
                len(name_by_src), len(law_map))
    driver = get_neo4j_driver()
    docs = cited = edges = 0
    try:
        for parsed in _hf_putusan_documents():
            name = name_by_src.get(parsed["source_url"])
            if not name:
                continue  # belum teregistrasi — bukan urusan backfill
            refs = extract_putusan_citations(parsed["articles"], law_map)
            docs += 1
            if not refs:
                continue
            cited += 1
            try:
                edges += link_putusan_citations(
                    driver, name, parsed["articles"], refs)
            except Exception as exc:
                logger.warning("Link %s gagal: %s", name[:60], exc)
            if docs % 200 == 0:
                logger.info("  …%d diproses, %d menyitasi, %d edge",
                            docs, cited, edges)
    finally:
        driver.close()
    logger.info("SELESAI: %d putusan, %d menyitasi UU, %d edge CITES",
                docs, cited, edges)
    return 0


if __name__ == "__main__":
    sys.exit(main())
