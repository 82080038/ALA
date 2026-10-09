"""
Doctrine Seeder — Fase 0 "Belajar Ilmu Hukum" ala profesor hukum.

Sebelum menjadi penegak hukum, sistem harus memahami ILMU hukum:
asas-asas, teori pemidanaan, anatomi peraturan perundang-undangan,
metode interpretasi, dan peta lembaga APH — bukan sekadar teks pasal.

Setiap konsep dirumuskan sebagai kurikulum deterministik (daftar
konsep standar ilmu hukum Indonesia), lalu LLM menulis penjelasan
berstruktur dalam Bahasa Indonesia. Hasilnya ditanam sebagai dokumen
`law_category="doktrin"` dengan `law_name` berprefiks "DOKTRIN —" dan
`verified=False` (skor 0.5): ini penjelasan konseptual yang digenerate,
bukan sumber primer — labelingnya jujur. Jawaban bernalar hukum nanti
bisa merujuk konsep ini selain pasal.
"""
import logging
import re

logger = logging.getLogger("ala.alcd.doctrine")

# Kurikulum fondasi ilmu hukum — konsep yang wajib dipahami sebelum
# membaca pasal, tersusun berjenjang: hukum DASAR dulu (apa itu hukum,
# sistemnya, sumbernya), baru pengembangan (pidana materiil → formil →
# delik khusus → praktik APH). Ini desain kurikulum, bukan isi:
# penjelasannya ditulis LLM saat bootstrap dan ditandai 'doktrin'.
_FOUNDATION_CONCEPTS: list[tuple[str, str]] = [
    # ── Jenjang I: Ilmu Hukum Dasar ──────────────────────────────────
    ("Pengantar Ilmu Hukum",
     "hukum sebagai kaidah/norma vs kenyataan sosial; objek kajian ilmu "
     "hukum; ius constitutum vs ius constituendum; hubungan hukum, "
     "subjek, objek, dan peristiwa hukum"),
    ("Sistem Hukum Indonesia",
     "tradisi civil law (Eropa Kontinental) warisan kolonial vs common "
     "law; hukum tertulis sebagai sumber utama; kodifikasi; kedudukan "
     "hukum adat dan hukum tidak tertulis"),
    ("Sumber-Sumber Hukum",
     "sumber formil vs materiil: peraturan perundang-undangan, "
     "kebiasaan, yurisprudensi, traktat, doktrin; hierarki dan daya "
     "ikat masing-masing"),
    ("Kodifikasi dan Sejarah Hukum Pidana Indonesia",
     "WvS 1918 → UU 1/1946 → KUHP nasional UU 1/2023: apa yang "
     "dipertahankan, dihapus, dan diubah; makna re-kodifikasi total"),
    ("Hierarki Peraturan Perundang-undangan",
     "urutan UUD 1945 → Tap MPR → UU/Perppu → PP → Perpres → Perda "
     "menurut UU 12/2011 jo. UU 13/2022; akibat hukum peraturan yang "
     "bertentangan dengan yang lebih tinggi"),
    ("Asas-Asas Pembentukan Peraturan",
     "lex superior derogat legi inferiori, lex posterior derogat legi "
     "priori, lex specialis derogat legi generali, dan lex posterior "
     "specialis derogat legi priori generali — kapan asas mana dipakai"),
    ("Asas Legalitas",
     "nullum delictum nulla poena sine praevia lege poenali — Pasal 1 "
     "ayat (1) KUHP; larangan analogi & hukum kebiasaan sebagai dasar "
     "pemidanaan; pengecualian historis"),
    ("Sistematika Undang-Undang",
     "anatomi dokumen: judul → konsiderans Menimbang/Mengingat → dasar "
     "hukum → batang tubuh (BAB→Bagian→Paragraf→Pasal→ayat→huruf) → "
     "ketentuan penutup → penjelasan resmi"),
    ("Tindak Pidana dan Unsur Delik",
     "perbuatan, melawan hukum (materiil vs formil), kesalahan, "
     "dapat dipertanggungjawabkan; delik materiil vs formil, delik "
     "komisi vs omisi, delik aduan vs biasa"),
    ("Kesalahan dan Pertanggungjawaban Pidana",
     "kesengajaan (opzet: opzet als oogmerk, met zekerheidsbewustzijn, "
     "met mogelijkheidsbewustzijn), kealpaan (culpa), alasan pemaaf, "
     "alasan pembenar, kapasitas berpikir"),
    ("Teori Pemidanaan",
     "teori absolut/pembalasan, relatif/tujuan (prevensi umum-khusus, "
     "resosialisasi), gabungan; pidana pokok vs tambahan; ancaman "
     "minimum-khusus"),
    ("Penyertaan, Percobaan, dan Gabungan Tindak Pidana",
     "deelneming (pleger, doenpleger, uitlokker, medeplichtige), poging "
     "dan awal pelaksanaan, concursus idealis vs realis, delik "
     "berlanjut (voortgezette handeling)"),
    # ── Jenjang III: Hukum Acara (formil) ────────────────────────────
    ("Alat Bukti dan Pembuktian",
     "alat bukti sah Pasal 184 KUHAP, bewijs minimum (2 alat bukti + "
     "keyakinan hakim Pasal 183), beban pembuktian, pembuktian "
     "terbalik di Tipikor/TPPU"),
    ("Stadium Hukum Acara Pidana",
     "penyelidikan → penyidikan (penangkapan/penahanan/penggeledahan/"
     "penyitaan) → penuntutan → pemeriksaan di sidang → putusan → "
     "eksekusi; peran tiap lembaga di tiap stadium"),
    ("Lembaga Penegak Hukum (APH)",
     "pembagian kewenangan Polri (UU 2/2002), Kejaksaan (UU 16/2004 "
     "jo. 11/2021), KPK (UU 19/2019), peradilan; koorperatif vs "
     "integratif; kewenangan penyidik PPNS"),
    ("Metode Interpretasi Hukum",
     "gramatikal, sistematis, historis, teleologis/sosiologis, "
     "komparatif, futuristik, konstruksi analogi vs a contrario vs "
     "rechtsverfijning"),
    ("Putusan sebagai Sumber Hukum",
     "beda putusan MA (kasasi, peninjauan kembali, yurisprudensi) vs "
     "putusan MK (pengujian UU, erga omnes); daya ikat preseden di "
     "sistem civil law Indonesia"),
    ("Kedudukan Hukum Sementara dan Status Peraturan",
     "perubahan (jo.), pencabutan, konsolidasi, ketentuan peralihan, "
     "ketentuan penutup; cara membaca status 'berlaku/dicabut'"),
    # ── Jenjang IV: Hukum Pengembangan / Pidana Khusus ───────────────
    ("Hukum Pidana Khusus dan Kualifikasi Delik",
     "karakter delik khusus: korporasi sebagai subjek, ancaman "
     "minimum-khusus, pembuktian terbalik, kewenangan penyidik "
     "khusus (PPNS/KPK); relasi lex specialis terhadap KUHP"),
    ("Delik Khusus Lintas Undang-Undang",
     "peta UU khusus APH: Tipikor, TPPU, Narkotika/Psikotropika, ITE, "
     "TPPO, TPKS, Terorisme, PPPT — apa yang menyimpang dari "
     "KUHP/KUHAP umum dan mengapa"),
    # ── Jenjang V: Praktik — menerapkan hukum pada fakta ─────────────
    ("Analisis Perkara dan Konstruksi Pasal",
     "cara memetakan fakta ke unsur delik (isu → kaidah → penerapan → "
     "simpulan); konstruksi dakwaan alternatif vs subsidier vs "
     "kumulatif; pemilihan pasal primer-pendukung"),
]


_GLOSS_PROMPT = (
    "Anda profesor hukum Indonesia menulis bahan ajar singkat untuk "
    "penyidik APH. Tulis penjelasan terstruktur tentang konsep berikut "
    "dalam Bahasa Indonesia hukum yang baku.\n\n"
    "KONSEP: {concept}\nFOKUS: {focus}\n\n"
    "Format wajib:\n"
    "1. DEFINISI — satu paragraf definisi presisi.\n"
    "2. DASAR HUKUM — pasal/UU tempat konsep ini berpijak "
    "(sebutkan identitasnya; bila ragu, katakan ragu — jangan "
    "mengarang nomor pasal).\n"
    "3. PENJELASAN — 2-3 paragraf mendalam, contoh konkret konteks "
    "penegakan hukum.\n"
    "4. RELEVANSI APH — satu paragraf bagaimana konsep ini dipakai "
    "penyidik/penuntut praktik.\n\n"
    "Jawab langsung dengan substansi, tanpa pengantar."
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


def seed_doctrine(db, llm, report=None) -> dict:
    """Bangun doktrin fondasi — idempotent via source_url doktrin://."""
    from app.agents.alcd.autonomous_ingestor import (
        ingest_parsed_document, register_knowledge)
    from app.agents.alcd.graph_builder import build_graph_for_document
    from app.models.operational import KnowledgeRegistry
    from sqlalchemy import select

    def _rep(stage, topic, detail, done=None, total=None):
        if report:
            report(stage, topic, detail, done, total)

    seeded, skipped = 0, 0
    n_concepts = len(_FOUNDATION_CONCEPTS)
    for ci, (concept, focus) in enumerate(_FOUNDATION_CONCEPTS):
        url = f"doktrin://ala/{_slug(concept)}"
        exists = db.scalar(
            select(KnowledgeRegistry.id).where(
                KnowledgeRegistry.source_url == url,
                KnowledgeRegistry.ingestion_status.in_(
                    ["completed", "verified"])))
        if exists:
            skipped += 1
            continue
        _rep("doktrin", "Ilmu Hukum", concept, ci + 1, n_concepts)
        try:
            resp = llm.invoke(
                _GLOSS_PROMPT.format(concept=concept, focus=focus))
            gloss = (resp.content if hasattr(resp, "content")
                     else str(resp)).strip()
        except Exception as exc:
            logger.warning("Doktrin %s gagal digenerate: %s",
                           concept, exc)
            continue
        if len(gloss) < 200:
            logger.info("Doktrin %s terlalu pendek — dilewati", concept)
            continue
        parsed = {
            "law_name": f"DOKTRIN — {concept}",
            "law_number": None,
            "law_year": None,
            "law_subject": concept,
            "articles": [{"article_number": "Konsep",
                          "title": concept, "content": gloss}],
            "chapter_count": 0,
            "source_url": url,
            "source_status": "doktrin",
        }
        try:
            # verified=False — skor 0.5: ini konten LLM, bukan sumber
            # primer. Kategori 'doktrin' memisahkannya dari pasal UU.
            res = ingest_parsed_document(parsed, "doktrin", False)
            register_knowledge(db, parsed, res, "doktrin", False)
            build_graph_for_document(res["law_name"], parsed["articles"])
            seeded += 1
        except Exception as exc:
            db.rollback()
            logger.warning("Ingest doktrin %s gagal: %s", concept, exc)
    logger.info("Doktrin fondasi: %d ditanam, %d sudah ada",
                seeded, skipped)
    return {"seeded": seeded, "skipped": skipped}
