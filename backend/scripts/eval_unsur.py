#!/usr/bin/env python3
"""Benchmark unsur delik — evaluasi metadata `elements` di ChromaDB
terhadap gold set terstruktur (tests/gold/ala_unsur.jsonl).

Metrik per kasus (deterministik, tanpa LLM):
- pelaku   : substring ekspektasi ada di pelaku terekstrak
- sikap    : precision/recall frasa sikap batin
- penjara  : min/maks/seumur_hidup numerik sama
- denda    : denda_rp ≥ ekspektasi (parser menyimpan batas pertama)
- dipidana : frasa kriminalisasi cocok

Jalankan: cd backend && .venv/bin/python scripts/eval_unsur.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GOLD = Path(__file__).resolve().parents[1] / "tests/gold/ala_unsur.jsonl"


def _fetch_elements() -> dict:
    """(law_keyword, article) -> elements dari metadata Chroma."""
    import chromadb
    from app.config import settings

    c = chromadb.HttpClient(
        host=settings.chromadb_host, port=int(settings.chromadb_port))
    coll = c.get_collection("indonesian_laws")
    gold = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    out = {}
    off = 0
    while True:
        res = coll.get(limit=4000, offset=off, include=["metadatas"])
        if not res["metadatas"]:
            break
        off += 4000
        for m in res["metadatas"]:
            el = m.get("elements")
            if not el:
                continue
            ln = (m.get("law_name") or "").lower()
            an = m.get("article_number") or ""
            for g in gold:
                key = g["id"]
                if key in out:
                    continue
                if (g["law_keyword"].lower() in ln
                        and an == g["article_number"]):
                    out[key] = json.loads(el)
    return out


def _score(gold: dict, el: dict | None) -> dict:
    if not el:
        return {"found": False}
    exp = gold["expect"]
    r = {"found": True}
    if "pelaku_contains" in exp:
        r["pelaku"] = exp["pelaku_contains"] in (el.get("pelaku") or "").lower()
    if "sikap_subset" in exp:
        got = set(el.get("sikap_batin") or [])
        want = set(exp["sikap_subset"])
        r["sikap_recall"] = len(want & got) / len(want)
        r["sikap_precision"] = len(want & got) / max(len(got), 1)
    pj = (el.get("ancaman") or {}).get("penjara") or {}
    if "penjara_min" in exp:
        r["penjara_min"] = pj.get("min") == exp["penjara_min"]
    if "penjara_max" in exp:
        r["penjara_max"] = pj.get("maks") == exp["penjara_max"]
    if "seumur_hidup" in exp:
        r["seumur_hidup"] = bool(pj.get("seumur_hidup")) == exp["seumur_hidup"]
    if "denda_min" in exp:
        r["denda"] = (el.get("ancaman") or {}).get(
            "denda_rp", 0) >= exp["denda_min"]
    if "dipidana" in exp:
        r["dipidana"] = el.get("dipidana_di") == exp["dipidana"]
    return r


def main() -> int:
    gold = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    fetched = _fetch_elements()
    n_found = sum(1 for g in gold if g["id"] in fetched)
    scores = {g["id"]: _score(g, fetched.get(g["id"])) for g in gold}

    def _avg(field):
        vals = [s[field] for s in scores.values() if field in s]
        return sum(vals) / len(vals) if vals else None

    print(f"Gold: {len(gold)} kasus | unsur ditemukan: {n_found}")
    for g in gold:
        s = scores[g["id"]]
        if not s["found"]:
            print(f"  MISS  {g['id']:26} {g['note']}")
            continue
        bad = [k for k, v in s.items()
               if k != "found" and v is not True and v != 1.0]
        tag = "OK  " if not bad else f"PART ({','.join(bad)})"
        print(f"  {tag} {g['id']:26} {g['note']}")
    print("\nMetrik agregat:")
    for f in ("pelaku", "sikap_recall", "sikap_precision", "penjara_min",
              "penjara_max", "seumur_hidup", "denda", "dipidana"):
        v = _avg(f)
        if v is not None:
            print(f"  {f:16} {v:.3f}")
    print(f"  coverage         {n_found/len(gold):.3f}")
    return 0 if n_found == len(gold) else 1


if __name__ == "__main__":
    raise SystemExit(main())
