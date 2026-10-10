#!/usr/bin/env python3
"""Bangun hirarki normatif antar peraturan di Neo4j.

Tiga jenis relasi, semuanya berbasis bukti/doktrin yang dapat
dipertanggungjawabkan — bukan tebakan model:

1. SUPERIOR_TO — peraturan pelaksana (Perkap/Perpol/PP/Perpres/dll)
   ke UU yang menjadi dasar hukumnya. Sumber: edge CITES non-putusan
   (konsiderans 'Mengingat' + sitasi pasal). Grounded, bukan asumsi.

2. NEWER_THAN — UU yang lebih muda terhadap UU satu keluarga (subjek
   sama, tahun beda) di wilayah ontologi yang sama — proxy lex
   posteriori. Pasangan dibatasi subjek yang berbagi kata pembeda
   agar "UU Minerba" vs "UU Kesehatan" tidak tertaut sembarangan.

3. SPECIALIS_OF — undang-undang pidana sektoral (Tipikor, Narkotika,
   TPPU, ITE, TPKS, TPPO, KDRT, Perlindungan Anak) terhadap KUHP —
   lex specialis derogat legi generali, doktrin baku hukum pidana.
   Properti `co_cited` mencatat berapa putusan yang menyitasi KEDUA
   undang-undang bersama — bukti empiris hubungan tersebut.

Jalankan:  cd backend && PYTHONPATH=. .venv/bin/python \\
              scripts/build_norm_hierarchy.py
"""
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("norm_hierarchy")

_KUHP_IDS = {("1", "1946"), ("1", "2023"), ("1", "2026")}
# Pasal-pasal sektoral yang secara doktrin lex specialis thd KUHP.
_SPECIAL_IDS = {
    ("35", "2009"), ("5", "1997"),          # Narkotika, Psikotropika
    ("31", "1999"), ("20", "2001"),         # Tipikor
    ("8", "2010"),                          # TPPU
    ("11", "2008"), ("19", "2016"), ("1", "2024"),  # ITE
    ("21", "2007"),                         # TPPO
    ("23", "2004"),                         # KDRT
    ("12", "2022"),                         # TPKS
    ("23", "2002"), ("35", "2014"), ("17", "2016"),  # Perlintas anak
}

_LAW_ID_RE = re.compile(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})")
_WORD_RE = re.compile(r"[a-zA-Z]{6,}")
_STOP = {"indonesia", "republik", "negara", "tentang", "nomor",
         "tahun", "undang", "peraturan", "pemerintah"}


def _law_id(name: str):
    m = _LAW_ID_RE.search(name or "")
    return (m.group(1).lstrip("0"), m.group(2)) if m else None


def _subject_words(name: str) -> set:
    tail = name.split("tentang")[-1] if "tentang" in name.lower() else name
    return {w for w in _WORD_RE.findall(tail.lower()) if w not in _STOP}


def main() -> int:
    from app.database.neo4j import get_neo4j_driver
    from app.database.postgres import SessionLocal
    from app.models.operational import KnowledgeRegistry
    from sqlalchemy import select

    db = SessionLocal()
    laws = [r.law_name for r in db.scalars(
        select(KnowledgeRegistry).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"])))]
    db.close()

    driver = get_neo4j_driver()
    with driver.session() as s:
        # 0. Pastikan LegalDoc untuk tiap UU registry (idempotent).
        s.run(
            "UNWIND $names AS n MERGE (d:LegalDoc {name: n}) "
            "ON CREATE SET d.scope = 'GLOBAL' RETURN count(*)",
            names=laws).consume()

        # 1. SUPERIOR_TO — konsiderans/dasar hukum (CITES non-putusan).
        pairs = s.run(
            "MATCH (a:LegalArticle)-[:CITES]->(b:LegalArticle) "
            "WHERE NOT a.law_name STARTS WITH 'Putusan' "
            "RETURN DISTINCT a.law_name AS f, b.law_name AS t").values()
        n_sup = 0
        for f, t in pairs:
            s.run(
                "MERGE (a:LegalDoc {name: $f}) "
                "MERGE (b:LegalDoc {name: $t}) "
                "MERGE (b)-[:SUPERIOR_TO]->(a)",
                f=f, t=t)
            n_sup += 1
        logger.info("SUPERIOR_TO: %d edge (dasar hukum)", n_sup)

        # 2. NEWER_THAN — satu wilayah, subjek berbagi kata pembeda.
        grouped: dict[int, list] = defaultdict(list)
        try:
            import requests
            import uuid as _uuid
            ont = requests.get(
                "http://localhost:8080/api/v1/alcd/ontology",
                headers={"X-Institution-ID": str(_uuid.uuid4()),
                         "X-Role": "admin"},
                timeout=30).json()
            for i, node in enumerate(ont.get("nodes", [])):
                for l in node.get("laws", []):
                    if l.get("law_year"):
                        grouped[i].append(
                            (l["law_name"], str(l["law_year"])))
        except Exception:
            # Offline fallback — semua UU satu kelompok, subjek filter
            # tetap menjaga presisi.
            for ln in laws:
                m = _LAW_ID_RE.search(ln or "")
                if m:
                    grouped[0].append((ln, m.group(2)))
        n_new = 0
        for members in grouped.values():
            for i, (la, ya) in enumerate(members):
                for lb, yb in members[i + 1:]:
                    if ya == yb:
                        continue
                    if not (_subject_words(la) & _subject_words(lb)):
                        continue
                    newer, older = (la, lb) if ya > yb else (lb, la)
                    s.run(
                        "MERGE (a:LegalDoc {name: $n}) "
                        "MERGE (b:LegalDoc {name: $o}) "
                        "MERGE (a)-[:NEWER_THAN]->(b)",
                        n=newer, o=older)
                    n_new += 1
        logger.info("NEWER_THAN: %d edge (lex posteriori)", n_new)

        # 3. SPECIALIS_OF — pidana sektoral → KUHP (doktrin), plus
        # bukti ko-sitasi putusan sebagai properti.
        name_by_id = {}
        for ln in laws:
            lid = _law_id(ln or "")
            if lid:
                name_by_id.setdefault(lid, []).append(ln)
        kuhp = [n for i in _KUHP_IDS for n in name_by_id.get(i, [])]
        co = s.run(
            "MATCH (p:LegalArticle)-[:CITES]->(x:LegalArticle), "
            "      (p)-[:CITES]->(y:LegalArticle) "
            "WHERE x.law_name <> y.law_name "
            "RETURN x.law_name AS a, y.law_name AS b, "
            "count(DISTINCT p.law_name) AS n").values()
        co_count = defaultdict(int)
        for a, b, n in co:
            co_count[frozenset((a, b))] = max(
                co_count[frozenset((a, b))], n)
        n_sp = 0
        for sid in _SPECIAL_IDS:
            for spec in name_by_id.get(sid, []):
                for k in kuhp:
                    s.run(
                        "MERGE (a:LegalDoc {name: $s}) "
                        "MERGE (b:LegalDoc {name: $k}) "
                        "MERGE (a)-[r:SPECIALIS_OF]->(b) "
                        "SET r.co_cited = $n",
                        s=spec, k=k,
                        n=co_count[frozenset((spec, k))])
                    n_sp += 1
        logger.info("SPECIALIS_OF: %d edge (%d KUHP target)", n_sp,
                    len(kuhp))
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
