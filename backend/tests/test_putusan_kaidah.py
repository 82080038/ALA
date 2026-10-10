"""Regresi ekstraksi kaidah putusan — ratio/amar struktural."""
from app.agents.alcd.putusan_kaidah import extract_kaidah

_PERTIMBANGAN = (
    "Menimbang, bahwa terdakwa didakwa melanggar Pasal 112 ayat (1) "
    "UU RI No 35 Tahun 2009 tentang Narkotika; "
    "Menimbang, bahwa unsur tanpa hak atau melawan hukum telah "
    "terpenuhi berdasarkan fakta persidangan; "
    "Menimbang, bahwa oleh karena itu dakwaan primair terbukti;")

_AMAR = (
    "MENGADILI: Menyatakan Terdakwa Ahmad telah terbukti secara sah "
    "dan meyakinkan bersalah melakukan tindak pidana; Menjatuhkan "
    "pidana terhadap Terdakwa dengan pidana penjara selama 5 (lima) "
    "tahun;")

_AMAR_BEBAS = (
    "MENGADILI: Membebaskan Terdakwa dari segala dakwaan; "
    "Memulihkan hak Terdakwa;")


def _sections(pertimbangan=_PERTIMBANGAN, amar=_AMAR):
    return [
        {"title": "kepala_putusan", "content": "DEMI KEADILAN"},
        {"title": "pertimbangan_hukum", "content": pertimbangan},
        {"title": "amar_putusan", "content": amar},
    ]


def test_ratio_terpisah_per_menimbang():
    k = extract_kaidah(_sections())
    assert len(k["ratio_decidendi"]) == 3
    # Tiap klausa adalah unit utuh — tidak saling tercampur.
    assert "Pasal 112" in k["ratio_decidendi"][0]
    assert all(not r.startswith("menimbang") for r in k["ratio_decidendi"])


def test_pasal_pertimbangan_ekstraksi_penuh():
    k = extract_kaidah(_sections())
    assert any("Pasal 112" in p and "35" in p
               for p in k["pasal_pertimbangan"])


def test_amar_terbukti_dan_hukuman():
    k = extract_kaidah(_sections())
    assert k["amar"]["terbukti"] is True
    assert "sah dan meyakinkan" in k["amar"]["frasa_terbukti"]
    assert "5 (lima) tahun" in k["amar"]["hukuman"]
    assert "menjatuhkan" in k["amar"]["diksi"]


def test_amar_bebas():
    k = extract_kaidah(_sections(amar=_AMAR_BEBAS))
    assert k["amar"]["terbukti"] is False
    assert "membebaskan" in k["amar"]["diksi"]


def test_tanpa_seksi_kosong():
    k = extract_kaidah([{"title": "fakta", "content": "…"}])
    assert k["ratio_decidendi"] == []
    assert k["amar"] == {}
