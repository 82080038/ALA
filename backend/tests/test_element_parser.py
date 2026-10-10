"""Regresi unsur delik — parsing deterministik rumusan pidana."""
from app.agents.alcd.element_parser import extract_elements


def test_pencurian_kuhp():
    e = extract_elements(
        "Barang siapa mengambil suatu barang, yang seluruhnya atau "
        "sebagian kepunyaan orang lain, dengan maksud untuk dimiliki "
        "secara melawan hukum, diancam karena pencurian, dengan pidana "
        "penjara paling lama lima tahun.")
    assert e["pelaku"] == "Barang siapa"
    assert "mengambil" in e["perbuatan"]
    # Tidak ada konjungsi menggantung sisa penghapusan sikap batin.
    assert not e["perbuatan"].rstrip().endswith(("secara", "dan", "atau"))
    assert "melawan hukum" in e["sikap_batin"]
    assert e["ancaman"]["penjara"]["maks"] == 5


def test_tipikor_rentang_dan_seumur_hidup():
    e = extract_elements(
        "Setiap orang yang secara melawan hukum melakukan perbuatan "
        "memperkaya diri sendiri atau orang lain atau suatu korporasi "
        "yang dapat merugikan keuangan negara atau perekonomian negara, "
        "dipidana dengan pidana penjara seumur hidup atau pidana penjara "
        "paling singkat 4 tahun dan paling lama 20 tahun dan denda "
        "paling sedikit Rp 200.000.000,00 dan paling banyak "
        "Rp 1.000.000.000,00.")
    assert e["pelaku"].lower() == "setiap orang"
    assert e["ancaman"]["penjara"]["seumur_hidup"] is True
    assert e["ancaman"]["penjara"]["min"] == 4.0
    assert e["ancaman"]["penjara"]["maks"] == 20.0
    assert e["ancaman"]["denda_rp"] == 200_000_000.0


def test_denda_format_indonesia():
    e = extract_elements(
        "Setiap Orang dipidana dengan pidana penjara paling lama 6 "
        "(enam) tahun dan/atau denda paling banyak Rp1.000.000.000,00.")
    assert e["ancaman"]["penjara"]["maks"] == 6
    assert e["ancaman"]["denda_rp"] == 1_000_000_000.0


def test_ayat_prefix_dan_header_pasal():
    e = extract_elements(
        "(1) Setiap orang yang tanpa hak atau melawan hukum menanam "
        "Narkotika Golongan I, dipidana dengan pidana penjara paling "
        "singkat 4 tahun dan paling lama 12 tahun.")
    assert e["pelaku"].lower().startswith("setiap orang")
    assert "yang atau" not in e["perbuatan"]
    assert e["ancaman"]["penjara"]["min"] == 4.0
    assert e["ancaman"]["penjara"]["maks"] == 12.0
    e2 = extract_elements(
        "Pasal 362 Barang siapa mengambil barang sesuatu untuk dimiliki "
        "secara melawan hukum, diancam pidana penjara lima tahun.")
    assert e2["pelaku"] == "Barang siapa"


def test_bukan_delik_tidak_diparse():
    assert extract_elements(
        "Ketentuan lebih lanjut diatur dengan Peraturan Pemerintah."
    ) is None
    assert extract_elements("") is None
    assert extract_elements(None) is None


def test_sikap_batin_terpisah_dari_perbuatan():
    e = extract_elements(
        "Setiap Orang dengan sengaja dan tanpa hak mengakses Komputer "
        "milik Orang lain dipidana dengan pidana penjara paling lama 8 "
        "(delapan) tahun.")
    assert "dengan sengaja" in e["sikap_batin"]
    assert "tanpa hak" in e["sikap_batin"]
    assert "sengaja" not in e["perbuatan"]
    assert "tanpa hak" not in e["perbuatan"]
