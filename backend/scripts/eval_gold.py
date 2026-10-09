"""Gold Benchmark — evaluasi retrieval terhadap dataset QA terverifikasi.

Menggantikan evaluasi "LLM menilai dirinya sendiri" dengan gold set
eksternal: `tests/gold/id_reg_qa.jsonl` (400 pasangan Q→A dari
`horelulus/ID_REG_QA_Small` HuggingFace — QA dihasilkan dari pasal
regulasi RI asli).

Metrik (pola eval_retrieval SPKT):
- **Coverage**: berapa pertanyaan gold yang UU-nya memang ada di registry
  (hanya ini yang secara fisik bisa di-retrieve).
- **P@k / HitRate@k**: proporsi pertanyaan yang pasal gold-nya muncul
  di top-k hasil `_rag_retrieve` (UU yang benar DAN pasal yang benar).
- **MRR**: mean reciprocal rank dari posisi hit pertama.

Jalankan (dari backend/):
    .venv/bin/python scripts/eval_gold.py [--k 10] [--limit N]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_GOLD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "gold")

# "…Nomor 13 Tahun 2009 … Pasal 1" — nomor/tahun/pasal gold.
_GOLD_RE = re.compile(
    r"Nomor\s+(\d+)\s+Tahun\s+(\d{4}).*?Pasal\s+(\d+)", re.IGNORECASE)
_LAW_ID_RE = re.compile(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})", re.IGNORECASE)


def _gold_key(row: dict) -> tuple[str, str, str] | None:
    """Kunci (nomor, tahun, pasal) — dari kolom eksplisit
    (`ala_curated.jsonl`) atau parse teks pertanyaan (ID_REG_QA)."""
    if row.get("law_number") and row.get("law_year") and row.get("pasal"):
        return (str(row["law_number"]).lstrip("0"),
                str(row["law_year"]), str(row["pasal"]).lstrip("0"))
    m = _GOLD_RE.search(row.get("Question") or row.get("question") or "")
    if not m:
        return None
    return (m.group(1).lstrip("0"), m.group(2), m.group(3).lstrip("0"))


def _known_laws() -> set[tuple[str, str]]:
    """Himpunan (nomor, tahun) UU yang teregistrasi — coverage check."""
    from app.database.postgres import SessionLocal
    from app.models.operational import KnowledgeRegistry
    from sqlalchemy import select

    ids = set()
    with SessionLocal() as db:
        for law_name, law_number in db.execute(select(
                KnowledgeRegistry.law_name,
                KnowledgeRegistry.law_number)):
            m = _LAW_ID_RE.search(law_name or "")
            year = m.group(2) if m else None
            if law_number and year:
                ids.add((law_number.lstrip("0"), year))
    return ids


def _hit(results: list[dict], gold: tuple[str, str, str]) -> int | None:
    """Rank (1-based) hit pertama: UU benar (nomor+tahun di law_name)
    DAN pasal benar. None jika tidak ada."""
    gnum, gyear, gpasal = gold
    for rank, r in enumerate(results, 1):
        m = _LAW_ID_RE.search(r.get("law_name", ""))
        if not m or m.group(1).lstrip("0") != gnum or m.group(2) != gyear:
            continue
        no = str(r.get("article_number", "")).split()[-1].lstrip("0")
        if no == gpasal:
            return rank
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Gold benchmark retrieval ALA")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--match", default="",
                    help="hanya berkas gold yang namanya mengandung ini")
    args = ap.parse_args()

    pairs = []
    total_rows = 0
    for fname in sorted(os.listdir(_GOLD_DIR)):
        if not fname.endswith(".jsonl"):
            continue
        if args.match and args.match not in fname:
            continue
        with open(os.path.join(_GOLD_DIR, fname), encoding="utf-8") as f:
            for line in f:
                total_rows += 1
                row = json.loads(line)
                g = _gold_key(row)
                q = row.get("Question") or row.get("question")
                if g and q:
                    pairs.append((q, g, fname))
    if args.limit:
        pairs = pairs[:args.limit]
    print(f"Gold set: {len(pairs)} pertanyaan berkunci pasal "
          f"(dari {total_rows} baris di {_GOLD_DIR})")

    known = _known_laws()
    n_covered = sum(1 for _, g, _ in pairs if (g[0], g[1]) in known)
    print(f"Coverage korpus: {n_covered}/{len(pairs)} UU gold "
          f"teregistrasi ({len(pairs) - n_covered} di luar korpus — "
          f"otomatis miss, tapi dicatat jujur)")

    from app.agents.legal_foundation import _rag_retrieve

    rr = 0.0
    p_at_k = p_at_k_cov = 0
    for i, (q, gold, src) in enumerate(pairs):
        try:
            results = _rag_retrieve(q, n_results=args.k)
        except Exception as exc:
            print(f"  [{i}] retrieve gagal: {exc}")
            results = []
        rank = _hit(results, gold)
        if rank:
            p_at_k += 1
            rr += 1.0 / rank
            if (gold[0], gold[1]) in known:
                p_at_k_cov += 1
        if (i + 1) % 25 == 0:
            print(f"  … {i + 1}/{len(pairs)} — "
                  f"P@{args.k} sementara {p_at_k / (i + 1):.3f}")

    n = max(len(pairs), 1)
    print("\n══ HASIL GOLD BENCHMARK ══")
    print(f"Pertanyaan dievaluasi : {len(pairs)}")
    print(f"HitRate@{args.k} (P@k) : {p_at_k / n:.3f}  ({p_at_k} hit)")
    print(f"MRR@{args.k}           : {rr / n:.3f}")
    if n_covered:
        print(f"P@{args.k} (hanya UU tercakup): {p_at_k_cov / n_covered:.3f} "
              f"({p_at_k_cov}/{n_covered})")
    print(f"Catatan: {len(pairs) - n_covered} pertanyaan menunjuk "
          f"UU yang belum ada di korpus — P@k menaik otomatis saat "
          f"coverage bertumbuh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
