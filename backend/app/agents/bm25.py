"""
BM25 murni-Python — lapisan leksikal untuk hybrid retrieval.

Dense embedding (E5) menangkap makna tapi bisa melewatkan istilah
hukum literal ("pencurian dengan pemberatan" → "barang siapa mengambil
barang…"). BM25 menutup celah itu; hasil digabung dengan Reciprocal
Rank Fusion di legal_foundation — pola hybrid yang sama dipakai
sistem legal-RAG produksi (EscavAI, dkk.).
"""
import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Stopword fungsional Indonesia — dibuang agar kata isi menentukan.
_STOPS = frozenset(
    "yang dan di ke dari dalam atau atas untuk dengan pada adalah adalah "
    "ini itu juga tidak akan telah sebagai dapat oleh karena bagi lebih "
    "satu dua ia dia kami kita mereka ada pun hanya saja agar jika bila "
    "masih sudah belum tidak no nr uu".split()
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPS]


class BM25Index:
    """Indeks BM25 (k1=1.5, b=0.75) atas dokumen chunk."""

    def __init__(self, docs: list[str]):
        self._tf: list[dict[str, int]] = []
        self._dl: list[int] = []
        df: dict[str, int] = {}
        for doc in docs:
            toks = _tokens(doc)
            self._dl.append(len(toks))
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            for t in tf:
                df[t] = df.get(t, 0) + 1
        n = len(docs)
        self._idf = {
            t: math.log(1 + (n - d + 0.5) / (d + 0.5))
            for t, d in df.items()
        }
        self._avgdl = (sum(self._dl) / n) if n else 1.0
        self._k1, self._b = 1.5, 0.75

    def search(self, query: str, top_k: int = 24) -> list[tuple[int, float]]:
        """Return [(doc_index, skor)] menurun, hanya skor > 0."""
        qterms = _tokens(query)
        if not qterms:
            return []
        scored = []
        for i, (tf, dl) in enumerate(zip(self._tf, self._dl)):
            s = 0.0
            for t in qterms:
                f = tf.get(t)
                if not f:
                    continue
                idf = self._idf.get(t, 0.0)
                s += idf * f * (self._k1 + 1) / (
                    f + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
                )
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]
