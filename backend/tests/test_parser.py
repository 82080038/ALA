"""Uji parser dokumen hukum — format pasal BPK, dedup, xref, chunking."""
from app.agents.alcd.autonomous_ingestor import chunk_text
from app.agents.alcd.document_parser import DocumentParser
from app.agents.alcd.graph_builder import extract_cross_references

PARSER = DocumentParser(rate_limit=0)

# Format nyata dokumen BPK: "Pasal 1." dan "Pasal 1\nAyat (1) ..."
SAMPLE = (
    "UNDANG-UNDANG REPUBLIK INDONESIA NOMOR 15 TAHUN 2002 "
    "TENTANG TINDAK PIDANA PENCUCIAN UANG\n"
    "BAB I KETENTUAN UMUM\n"
    "Pasal 1.\nDalam Undang-Undang ini yang dimaksud dengan pencucian uang "
    "adalah perbuatan menempatkan, mentransfer, membayarkan harta kekayaan.\n"
    "Pasal 3\nSetiap Orang yang dengan sengaja menempatkan harta kekayaan "
    "yang diketahuinya merupakan hasil tindak pidana dipidana penjara "
    "sebagaimana dimaksud dalam Pasal 55 ayat (1) KUHP.\n"
    "Pasal 4\nSetiap Orang yang menyembunyikan atau menyamarkan asal usul "
    "harta kekayaan yang diketahuinya patut diduga hasil tindak pidana "
    "dipidana sesuai Pasal 30 UU ITE dan ketentuan KUHAP Pasal 184.\n"
)


def test_split_articles_dot_format():
    arts = PARSER._split_articles(SAMPLE)
    nums = [a["article_number"] for a in arts]
    assert "Pasal 1" in nums and "Pasal 3" in nums and "Pasal 4" in nums


def test_split_articles_min_length_filter():
    # Marker pasal tanpa isi (entri TOC) harus diabaikan
    text = "Pasal 1\nPasal 2\n" + "x" * 100
    arts = PARSER._split_articles(text)
    assert len(arts) == 1 and arts[0]["article_number"] == "Pasal 2"


def test_split_articles_dedup_keeps_longest():
    # Penjelasan di akhir dokumen menduplikasi nomor pasal → simpan terpanjang
    text = SAMPLE + "\nPasal 3\n" + ("Penjelasan singkat. " * 5)
    arts = PARSER._split_articles(text)
    p3 = [a for a in arts if a["article_number"] == "Pasal 3"]
    assert len(p3) == 1


def test_xref_extracts_law_names():
    arts = PARSER._split_articles(SAMPLE)
    refs = extract_cross_references(arts, "UU TPPU")
    targets = {(r["to_law"], r["to_article"]) for r in refs}
    assert ("KUHP", "Pasal 55") in targets
    assert any(law.startswith("UU") for law, art in targets)


def test_xref_no_self_reference():
    # Referensi ke pasal itu sendiri harus dibuang
    arts = [{"article_number": "Pasal 3",
             "content": "diatur dalam Pasal 3 ayat (1) KUHP lain."}]
    refs = extract_cross_references(arts, "UU X")
    assert all(r["to_article"] != "Pasal 3" for r in refs)


def test_chunk_text_size_and_overlap():
    text = "x" * 1200
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 500 for c in chunks)
    # Overlap: akhir chunk-1 == awal chunk-2
    assert chunks[1].startswith(chunks[0][-50:])


def test_chunk_text_short():
    assert chunk_text("pendek", size=500) == ["pendek"]
