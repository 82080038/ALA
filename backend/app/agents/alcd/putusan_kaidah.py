"""Ekstraksi kaidah hukum putusan MA secara struktural — tanpa LLM.

Membedakan lapisan sebuah putusan yang secara doktrin berbeda bobot:

- **ratio decidendi** — alasan hukum yang mengikat (di Indonesia:
  klausa "Menimbang, bahwa …" dalam pertimbangan hukum).
- **obiter dictum** — pertimbangan tambahan (tidak diekstrak khusus,
  cukup tidak dilabeli ratio).
- **amar** — dictum: identitas terdakwa, pasal yang terbukti, dan
  hukuman — diekstrak ke field terstruktur.

Bukan semantik bebas: heuristik posisional pada struktur baku putusan
Indonesia (kepala → riwayat → fakta → pertimbangan → amar).
"""
from __future__ import annotations

import re

# "Menimbang, bahwa …" — kanonik pembuka pertimbangan MA/PN.
_MENIMBANG_RE = re.compile(
    r"menimbang[,:;]?\s*(?:bahwa\s+)?", re.IGNORECASE)
# Klausa ratio: tiap "bahwa X" yang merupakan alasan hukum.
_BAHWA_RE = re.compile(r"bahwa\s+", re.IGNORECASE)
# Amar: "Menyatakan Terdakwa X … terbukti … melanggar Pasal Y",
# "Menjatuhkan pidana … selama N …", "Membebaskan", "Melepaskan".
_AMAR_DECL_RE = re.compile(
    r"(menyatakan|membebaskan|melepaskan|menghukum|menjatuhkan|"
    r"menolak|mengabulkan|memerintahkan)",
    re.IGNORECASE)
_TERBUKTI_RE = re.compile(
    r"terbukti(?:\s+secara\s+sah\s+dan\s+meyakinkan)?\s+"
    r"(?:bersalah\s+)?(?:melakukan|melanggar|mencurangi)?",
    re.IGNORECASE)
# Sitasi pasal penuh bila tersedia ("Pasal 112 ayat (1) UU RI No 35
# Tahun 2009"), jatuh ke "Pasal N" bila hanya nomornya.
_PASAL_AMAR_RE = re.compile(
    r"Pasal\s+\d+[A-Za-z]?\s*(?:ayat\s*\([^)]*\)\s*)?"
    r"(?:UU\s*(?:RI\s*)?(?:No\.?|Nomor\s*)?\s*\d+\s*Tahun\s*\d{4}"
    r"|KUHP|KUHAP)?",
    re.IGNORECASE)
_HUKUMAN_RE = re.compile(
    r"pidana\s+penjara\s+(?:selama\s+)?([^.;]{0,60})",
    re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z(0-9])")


def extract_kaidah(sections: list[dict]) -> dict:
    """Ekstrak ratio decidendi + amar terstruktur dari seksi putusan.

    `sections`: list [{"article_number"/"title", "content"}] seperti
    output `_hf_putusan_documents` (tag → judul seksi).
    """
    pertimbangan = amar = ""
    for s in sections:
        tag = (s.get("title") or s.get("article_number") or "").lower()
        tag = tag.replace(" ", "_")
        if "pertimbangan" in tag:
            pertimbangan = s.get("content", "")
        elif "amar" in tag:
            amar = s.get("content", "")

    out: dict = {"ratio_decidendi": [], "amar": {}}
    if pertimbangan:
        # Ambil segmen setelah "Menimbang" pertama — di situlah ratio
        # hidup; paragraf sebelumnya hanyalah pembuka formalitas.
        m = _MENIMBANG_RE.search(pertimbangan)
        seg = pertimbangan[m.start():] if m else pertimbangan
        # Tiap klausa 'menimbang, bahwa …' adalah satu ratio — pisah
        # pada batas marker agar klausa tidak saling tercampur.
        clauses = _MENIMBANG_RE.split(seg)
        for sent in clauses:
            sent = " ".join(sent.split())
            if len(sent) < 40:
                continue
            if _BAHWA_RE.match(sent):
                sent = _BAHWA_RE.sub("", sent, count=1)
            if len(out["ratio_decidendi"]) < 8:
                out["ratio_decidendi"].append(sent[:500])
        out["ratio_decidendi"] = [
            r for r in out["ratio_decidendi"] if len(r) > 30]
        # Pasal yang dipertimbangkan — kandidat dasar pemidanaan walau
        # amar (sering hasil OCR) tidak menyebutnya.
        out["pasal_pertimbangan"] = sorted({
            m.group(0).strip()
            for m in _PASAL_AMAR_RE.finditer(pertimbangan)})[:8]

    if amar:
        a: dict = {}
        if m := _TERBUKTI_RE.search(amar):
            a["terbukti"] = True
            a["frasa_terbukti"] = m.group(0).strip()
        elif m2 := re.search(r"membebaskan|melepaskan", amar, re.I):
            a["terbukti"] = False
            a["status"] = m2.group(0).lower()
        else:
            a["terbukti"] = None
        a["pasal_amar"] = sorted({
            m.group(0).strip()
            for m in _PASAL_AMAR_RE.finditer(amar)})[:6]
        if m := _HUKUMAN_RE.search(amar):
            a["hukuman"] = " ".join(m.group(1).split())[:120]
        a["diksi"] = sorted({
            m.group(0).lower()
            for m in _AMAR_DECL_RE.finditer(amar)})
        out["amar"] = a
    return out
