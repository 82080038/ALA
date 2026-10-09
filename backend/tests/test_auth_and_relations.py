"""Uji komponen keamanan & relasi hukum — offline, tanpa DB."""
import uuid

from app.auth import (
    create_token, decode_token, hash_password, verify_password)
from app.agents.alcd.external_corpus import _extract_law_relations
from app.agents.legal_foundation import (
    _law_pairs_of, _mention_boosts, _query_law_mentions)


def test_jwt_roundtrip():
    uid, iid = uuid.uuid4(), uuid.uuid4()
    token = create_token(uid, iid, "penyidik", "premium_l1")
    claims = decode_token(token)
    assert claims["sub"] == str(uid)
    assert claims["inst"] == str(iid)
    assert claims["role"] == "penyidik"
    assert claims["tier"] == "premium_l1"


def test_jwt_rejects_garbage():
    assert decode_token("bukan.token.jwt") is None
    assert decode_token("") is None


def test_password_hash_roundtrip():
    h = hash_password("Sandi#Kuat123")
    assert verify_password("Sandi#Kuat123", h)
    assert not verify_password("salah", h)
    assert h.startswith("$2")  # bcrypt


def test_query_law_mentions_explicit():
    m = _query_law_mentions("pelanggaran UU Nomor 8 Tahun 1981 pasal 184")
    assert ("8", "1981") in m


def test_query_law_mentions_alias():
    m = _query_law_mentions("alat bukti menurut KUHAP")
    assert ("8", "1981") in m
    m2 = _query_law_mentions("modus pencucian uang via crypto")
    assert ("8", "2010") in m2


def test_mention_boosts_rank_law_and_pasal():
    metas = [
        {"law_name": "KUHAP — UU Nomor 8 Tahun 1981",
         "article_number": "Pasal 184"},
        {"law_name": "UU Tipikor — UU Nomor 31 Tahun 1999",
         "article_number": "Pasal 184"},
        {"law_name": "KUHP — UU Nomor 1 Tahun 2023",
         "article_number": "Pasal 1"},
    ]
    boosts = _mention_boosts("KUHAP pasal 184", ["a", "b", "c"], metas)
    # law+pasal cocok → boost ganda; pasal saja di UU lain → boost kecil
    assert boosts["a"] > boosts.get("b", 0) > 0
    assert "c" not in boosts


def test_law_pairs_from_name():
    assert ("19", "2016") in _law_pairs_of(
        "UU ITE — UU Nomor 19 Tahun 2016")


def test_extract_revokes_same_sentence_only():
    # 'dicabut' dalam kalimat berbeda TIDAK boleh menyeret ref lain
    t = ("Undang-Undang Nomor 8 Tahun 1981 dicabut dan dinyatakan "
         "tidak berlaku. Undang-Undang Nomor 30 Tahun 2002 mengubah "
         "ketentuan lain.")
    rels = _extract_law_relations(t, "20", "2025")
    assert rels["revokes"] == ["UU Nomor 8 Tahun 1981"]
    assert rels["amends"] == []
    assert rels["amended_by"] == []


def test_extract_amends_and_amended_by():
    t = ("Undang-undang ini mengubah Undang-Undang Nomor 19 Tahun 2016. "
         "Ketentuan Undang-Undang Nomor 11 Tahun 2008 diubah dengan "
         "undang-undang ini.")
    rels = _extract_law_relations(t, "1", "2024")
    assert "UU Nomor 19 Tahun 2016" in rels["amends"]
    assert "UU Nomor 11 Tahun 2008" in rels["amends"]


def test_audit_digest_timezone_normalization():
    """Regresi: timestamptz dibaca kembali dengan offset sesi (+07:00)
    — digest harus identik untuk instan yang sama."""
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace

    from app.audit import _entry_digest

    ts_utc = datetime(2026, 10, 10, 3, 0, 0, tzinfo=timezone.utc)
    ts_wib = ts_utc.astimezone(timezone(timedelta(hours=7)))
    row_a = SimpleNamespace(request_id=uuid.uuid4(), action="analyze",
                            action_taken="x", institution_id=None,
                            user_id=None, timestamp=ts_utc)
    row_b = SimpleNamespace(request_id=row_a.request_id, action="analyze",
                            action_taken="x", institution_id=None,
                            user_id=None, timestamp=ts_wib)
    assert _entry_digest(row_a, "0" * 64) == _entry_digest(row_b, "0" * 64)


def test_event_years_ignores_law_citations():
    """Tahun identitas UU bukan tahun peristiwa — false-positive
    anakronisme terhadap UU yang disebut harus hilang."""
    from app.agents.legal_foundation import _event_years_of

    assert _event_years_of("UU 19/2016 Pasal 27") == []
    assert _event_years_of("UU Nomor 35 Tahun 2009 tentang Narkotika") == []
    assert _event_years_of(
        "peristiwa 2020 melanggar UU No 8 Tahun 2010") == [2020]
    assert _event_years_of("tindak pidana tahun 2019 dan 2021") == [
        2019, 2021]
    assert _event_years_of("modus pencucian uang crypto") == []


def test_extract_skips_self_reference():
    t = "Undang-undang ini mencabut Undang-Undang Nomor 1 Tahun 2024."
    rels = _extract_law_relations(t, "1", "2024")
    assert rels == {"revokes": [], "amends": [], "amended_by": []}
