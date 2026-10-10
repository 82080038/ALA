"""Ekstraksi unsur delik — parsing deterministik rumusan pasal pidana
Indonesia menjadi skema unsur terstruktur.

Rumusan delik Indonesia bersifat formulaik sehingga dapat di-parse
tanpa LLM:

    <pelaku> + <perbuatan> + <sikap batin/cara> + "dipidana …"
    <ancaman: penjara/kurungan/denda + rentang>

Contoh — "Setiap Orang yang dengan sengaja dan tanpa hak mengakses
Komputer … dipidana dengan pidana penjara paling lama 8 (delapan)
tahun":

    {"pelaku": "Setiap Orang",
     "perbuatan": "mengakses Komputer …",
     "sikap_batin": ["dengan sengaja", "tanpa hak"],
     "ancaman": {"penjara": {"maks_tahun": 8}, "denda": null},
     "pemberatan": false}

Tujuan: jawaban hukum = pemetaan fakta→unsur yang dapat diverifikasi,
bukan prosa bebas LLM.
"""
from __future__ import annotations

import re

# "dipidana"/"diancam" — penanda rumusan delik.
_DELIK_RE = re.compile(r"\b(di?pidana|diancam)\b", re.IGNORECASE)

# Subjek delik yang umum di perumusan Indonesia.
_PELAKU_RE = re.compile(
    r"^\s*(setiap\s+orang|barang\s*siapa|barangsiapa|korporasi|"
    r"pegawai\s+negeri|setiap\s+korporasi|pemimpin\s+dan/atau\s+penanggung\s+jawab)",
    re.IGNORECASE)

# Sikap batin / cara perbuatan — frasa kanonik hukum pidana.
_SIKAP_PATTERNS = [
    r"dengan\s+sengaja",
    r"dengan\s+melawan\s+(?:hukum|hak)",
    r"melawan\s+hukum",
    r"tanpa\s+hak",
    r"karena\s+kelalaian(?:nya)?",
    r"dengan\s+maksud",
    r"dengan\s+kekerasan\s+atau\s+ancaman\s+kekerasan",
    r"dengan\s+kekerasan",
    r"ancaman\s+kekerasan",
    r"secara\s+tidak\s+sah",
    r"secara\s+mela(r|w)wan\s+hukum",
    r"tanpa\s+izin",
    r"tanpa\s+sepengetahuan",
    r"dengan\s+tipu\s+muslihat",
]
_SIKAP_RE = re.compile("|".join(_SIKAP_PATTERNS), re.IGNORECASE)

_NUM_WORD = {
    "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6,
    "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
    "sebelas": 11, "dua belas": 12, "lima belas": 15, "dua puluh": 20,
}
_NUM_ALT = "|".join(sorted(_NUM_WORD, key=len, reverse=True))

# "pidana penjara paling lama 8 (delapan) tahun" / "penjara seumur
# hidup" / "pidana mati" — angka digit ATAU kata (KUHP lama: "lima
# tahun").
_PENJARA_RE = re.compile(
    r"(?:pidana\s+)?penjara\s+"
    r"(?:(?:paling\s+)?(?P<bound>lama|singkat)\s+)?"
    r"(?:(?P<val>\d+(?:[.,]\d+)?|(?:" + _NUM_ALT + r"))\s*"
    r"(?:\([^)]*\))?\s*"
    r"(?P<unit>tahun|bulan|hari)|seumur\s+hidup|mati)",
    re.IGNORECASE)
_MATI_RE = re.compile(r"pidana\s+mati", re.IGNORECASE)
_KURUNGAN_RE = re.compile(
    r"pidana\s+kurungan\s+paling\s+lama\s+"
    r"(?P<val>\d+(?:[.,]\d+)?)\s*(?:\([^)]*\))?\s*"
    r"(?P<unit>tahun|bulan)",
    re.IGNORECASE)
# Rentang berantai: "… penjara paling singkat 4 tahun DAN paling lama
# 20 tahun" — segmen kedua tak lagi didahului kata 'penjara'. Hanya
# dipakai bila 'penjara' memang muncul di teks ancaman.
_RANGE_RE = re.compile(
    r"(?:(?:paling\s+)?(?P<bound>lama|singkat)\s+)"
    r"(?P<val>\d+(?:[.,]\d+)?|(?:" + _NUM_ALT + r"))\s*"
    r"(?:\([^)]*\))?\s*(?P<unit>tahun|bulan|hari)",
    re.IGNORECASE)

_DENDA_RE = re.compile(
    r"denda(?:\s+paling\s+(banyak|sedikit))?\s*(?:sebesar|sejumlah)?\s*"
    r"Rp\.?\s*([\d.,]+)",
    re.IGNORECASE)
_PEMBERATAN_RE = re.compile(
    r"pidana\s+(?:nya\s+)?ditambah|diperberat|ancaman\s+pidana.{0,30}"
    r"ditambah|diancam.{0,40}ditambah", re.IGNORECASE | re.DOTALL)


def _durasi(m: re.Match) -> dict:
    """Rentang pidana dari match _PENJARA_RE/_KURUNGAN_RE."""
    out: dict = {}
    if m.group(0) and "seumur" in m.group(0).lower():
        return {"seumur_hidup": True}
    if m.group(0) and "mati" in m.group(0).lower():
        return {"pidana_mati": True}
    val = m.groupdict().get("val")
    unit = (m.groupdict().get("unit") or "").lower()
    if val:
        val = val.strip().lower()
        n = _NUM_WORD.get(val) if not val[0].isdigit() else float(
            val.replace(",", "."))
        bound = (m.groupdict().get("bound") or "lama").lower()
        out["maks" if bound == "lama" else "min"] = (
            n if unit == "tahun" else
            round(n / 12, 2) if unit == "bulan" else
            round(n / 365, 3))
        out["satuan"] = "tahun_ekuivalen"
    return out


def extract_elements(content: str) -> dict | None:
    """Parse rumusan delik → skema unsur. None jika bukan pasal pidana
    (tidak mengandung 'dipidana'/'diancam')."""
    if not content:
        return None
    m = _DELIK_RE.search(content)
    if not m:
        return None

    pre, post = content[:m.start()], content[m.end():]
    # Ayat pembuka "(1) Setiap Orang …" dan header "Pasal 362 …" di
    # konten — buang penomoran agar subjek tetap dikenali.
    pre = re.sub(r"^\s*(?:Pasal\s+\d+[A-Za-z]?\s*)?\(\d+\)\s*",
                 "", pre)
    pre = re.sub(r"^\s*Pasal\s+\d+[A-Za-z]?\s+", "", pre)
    pelaku_m = _PELAKU_RE.match(pre)
    pelaku = pelaku_m.group(1) if pelaku_m else None
    perbuatan = pre[pelaku_m.end():] if pelaku_m else pre
    # Buang penghubung formil di kepala perbuatan.
    perbuatan = re.sub(
        r"^\s*(yang|barang|siapa|,|\.|:)+", " ", perbuatan).strip()

    sikap = sorted({
        " ".join(m2.group(0).lower().split())
        for m2 in _SIKAP_RE.finditer(pre)})
    # Sikap batin bukan bagian perbuatan — keluarkan dari klausa
    # agar unsur bersih ("dengan sengaja dan tanpa hak mengakses" →
    # perbuatan "mengakses", sikap ["dengan sengaja", "tanpa hak"]).
    perbuatan = _SIKAP_RE.sub(" ", perbuatan)
    perbuatan = re.sub(
        r"^\s*(yang|dan|atau|secara|,|\.|:)+", " ", perbuatan).strip()
    perbuatan = re.sub(r"\s+", " ", perbuatan).strip(" ,.;:")
    # Konjungsi yatim: "yang tanpa hak atau melawan hukum menanam" →
    # "yang atau menanam" — gabung sisa "yang atau/dan" → "yang".
    perbuatan = re.sub(r"\byang\s+(?:dan|atau)\s+", "yang ",
                       perbuatan)
    # Konjungsi yatim sebelum koma ("… lain secara , dengan memakai"
    # sisa penghapusan "melawan hukum") + koma ganda.
    perbuatan = re.sub(r"\s*(?:secara|dengan|dan|atau)\s*(?=,)", "",
                       perbuatan)
    perbuatan = re.sub(r"(?:\s*,){2,}", ",", perbuatan)
    perbuatan = re.sub(r"\s+", " ", perbuatan).strip(" ,.;:")
    # Konjungsi menggantung di ekor — sisa penghapusan sikap batin
    # ("untuk dimiliki secara melawan hukum" → "untuk dimiliki").
    perbuatan = re.sub(
        r"(?:\s+(?:dan|atau|secara|dengan|yang))+\s*$", "",
        perbuatan).strip(" ,.;:")[:400]

    ancaman: dict = {"penjara": None, "kurungan": None,
                     "denda_rp": None, "mati": False}
    def _merge_penjara(acc: dict, d: dict) -> None:
        """Agregat multi-ayat: min = terkecil, maks = terbesar —
        ancaman pasal = rentang keseluruhan ayatnya."""
        for k, v in d.items():
            if k == "min":
                acc["min"] = min(acc.get("min", v), v)
            elif k == "maks":
                acc["maks"] = max(acc.get("maks", v), v)
            else:
                acc[k] = v

    # Gabungkan SEMUA rentang penjara (mis. "seumur hidup ATAU paling
    # singkat 4 tahun dan paling lama 20 tahun").
    for pm in _PENJARA_RE.finditer(post):
        if ancaman["penjara"] is None:
            ancaman["penjara"] = {}
        _merge_penjara(ancaman["penjara"], _durasi(pm))
    # Lengkapi rentang berantai ("… dan paling lama 20 tahun").
    if ancaman["penjara"] is not None:
        for rm in _RANGE_RE.finditer(post):
            # Jangan serap rentang kurungan/denda sebagai penjara.
            ctx = post[max(0, rm.start() - 40):rm.start()]
            if re.search(r"(kurungan|denda|denda pidana)\W*$", ctx):
                continue
            _merge_penjara(ancaman["penjara"], _durasi(rm))
    km = _KURUNGAN_RE.search(post)
    if km:
        ancaman["kurungan"] = _durasi(km) or {"ada": True}
    dm = _DENDA_RE.search(post)
    if dm:
        # "Rp800.000.000,00" → buang desimal ",00" lalu titik ribuan.
        raw = dm.group(2).split(",")[0]
        ancaman["denda_rp"] = float(re.sub(r"[^\d]", "", raw) or 0)
    ancaman["mati"] = bool(_MATI_RE.search(post))

    return {
        "pelaku": (pelaku or "subjek tidak eksplisit"),
        "perbuatan": perbuatan or None,
        "sikap_batin": sikap,
        "ancaman": {k: v for k, v in ancaman.items() if v},
        "pemberatan": bool(_PEMBERATAN_RE.search(post)),
        "dipidana_di": "dipidana" if "dipidana" in m.group(1).lower()
                        else "diancam",
    }
