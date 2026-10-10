#!/usr/bin/env python3
"""Backfill kaidah putusan — ratio decidendi + amar terstruktur —
ke properti node putusan di Neo4j.

Properti yang di-set pada node LegalArticle putusan:
- `kaidah` (JSON): {"ratio_decidendi": [...], "amar": {...},
                    "pasal_pertimbangan": [...]} pada node seksi
  'Pertimbangan Hukum' (kaidah disimpan di node pertimbangan).
- `amar` (JSON) pada node 'Amar Putusan'.

Jalankan:  cd backend && PYTHONPATH=. .venv/bin/python \\
              scripts/extract_kaidah_putusan.py
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("kaidah_putusan")


def main() -> int:
    from app.agents.alcd.external_corpus import _hf_putusan_documents
    from app.agents.alcd.putusan_kaidah import extract_kaidah
    from app.database.chroma import get_chroma_client, get_laws_collection
    from app.database.neo4j import get_neo4j_driver

    coll = get_laws_collection(get_chroma_client())
    driver = get_neo4j_driver()
    docs = list(_hf_putusan_documents())
    logger.info("Putusan: %d", len(docs))
    n = n_chroma = 0
    with driver.session() as s:
        for doc in docs:
            k = extract_kaidah(doc["articles"])
            if not k["ratio_decidendi"] and not k["amar"]:
                continue
            n += s.run(
                "MATCH (a:LegalArticle {law_name: $ln, "
                "article_number: 'Pertimbangan Hukum'}) "
                "SET a.kaidah = $k RETURN count(a) AS c",
                ln=doc["law_name"],
                k=json.dumps(k, ensure_ascii=False)).single()["c"]
            if k["amar"]:
                s.run(
                    "MATCH (a:LegalArticle {law_name: $ln, "
                    "article_number: 'Amar Putusan'}) "
                    "SET a.amar = $a",
                    ln=doc["law_name"],
                    a=json.dumps(k["amar"], ensure_ascii=False))
            # Tempelkan kaidah juga ke chunk Chroma putusan —
            # source_url hf://putusan/<hash> unik per dokumen.
            got = coll.get(
                where={"$and": [
                    {"source_url": {"$eq": doc["source_url"]}},
                    {"article_number": {"$eq": "Pertimbangan Hukum"}}]},
                include=["metadatas"])
            if got["ids"]:
                metas = []
                for m in got["metadatas"]:
                    m = dict(m or {})
                    m["kaidah"] = json.dumps(k, ensure_ascii=False)
                    metas.append(m)
                coll.update(ids=got["ids"], metadatas=metas)
                n_chroma += len(got["ids"])
            if n % 200 == 0:
                logger.info("… %d putusan", n)
    driver.close()
    logger.info("Selesai — %d putusan membawa kaidah; %d chunk Chroma",
                n, n_chroma)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
