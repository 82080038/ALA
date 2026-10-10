#!/usr/bin/env python3
"""Benchmark kaidah putusan — coverage & konsistensi struktural
ekstraksi ratio/amar pada node putusan di Neo4j.

Metrik (deterministik):
- coverage_ratio  : putusan yang membawa ratio_decidendi non-kosong
- coverage_amar   : putusan yang membawa amar terstruktur
- outcome_dist    : distribusi terbukti/bebas/unknown
- pasal_rate      : bagian yang membawa sitasi pasal pertimbangan

Jalankan: cd backend && .venv/bin/python scripts/eval_kaidah.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from app.database.neo4j import get_neo4j_driver

    d = get_neo4j_driver()
    with d.session() as s:
        total = s.run(
            "MATCH (a:LegalArticle) WHERE a.law_name STARTS WITH "
            "'Putusan MA' AND a.article_number = 'Pertimbangan Hukum' "
            "RETURN count(a) AS c").single()["c"]
        rows = s.run(
            "MATCH (a:LegalArticle) WHERE a.law_name STARTS WITH "
            "'Putusan MA' AND a.kaidah IS NOT NULL "
            "RETURN a.kaidah AS k").values()
    d.close()

    n_ratio = n_amar = n_pasal = 0
    outcome = Counter()
    for (kjson,) in rows:
        k = json.loads(kjson)
        if k.get("ratio_decidendi"):
            n_ratio += 1
        if k.get("amar"):
            n_amar += 1
            tb = k["amar"].get("terbukti")
            outcome["terbukti" if tb is True else
                      "bebas/lepas" if tb is False else "unknown"] += 1
            if k["amar"].get("hukuman"):
                outcome["dengan_hukuman"] += 1
        if k.get("pasal_pertimbangan"):
            n_pasal += 1

    n = len(rows)
    print(f"Node 'Pertimbangan Hukum' putusan : {total}")
    print(f"Membawa kaidah                  : {n} ({n/max(total,1):.1%})")
    print(f"  ratio_decidendi non-kosong    : {n_ratio}")
    print(f"  amar terstruktur              : {n_amar}")
    print(f"  pasal_pertimbangan            : {n_pasal}")
    print(f"  outcome                       : {dict(outcome)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
