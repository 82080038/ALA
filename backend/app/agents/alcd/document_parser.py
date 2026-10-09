"""
Document Parser — ALCD Fase 2b.

Mengunduh dokumen hukum (HTML/PDF) dari sumber yang ditemukan
SourceDiscoverer, lalu mengekstrak konten terstruktur: nama UU, nomor
pasal, bab, dan isi teks.
"""
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger("ala.alcd.parser")

# UA browser asli — portal pemerintah (BPK/JDIH) sering memblokir UA bot
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
# Marker pasal di awal baris: "Pasal 5", "Pasal 5.", "Pasal 5 ..." (TOC)
_PASAL_RE = re.compile(
    r"(?m)^\s*Pasal\s+(\d+[A-Za-z]?)\.?\s*(?:\.{2,}\s*\d*)?\s*$")
_BAB_RE = re.compile(r"(?m)^\s*BAB\s+([IVXLCDM]+|\d+)", re.IGNORECASE)
_LAW_NAME_RE = re.compile(
    r"(UNDANG-UNDANG|PERATURAN|KITAB UNDANG-UNDANG)[^\n]{0,120}", re.IGNORECASE
)
# Lebih spesifik: "UNDANG-UNDANG REPUBLIK INDONESIA NOMOR 8 TAHUN 2010"
_LAW_NUMBERED_RE = re.compile(
    r"(UNDANG-UNDANG|PERATURAN)[^\n]{0,60}?(?:NOMOR|NO\.?)\s*[\w.]+\s*TAHUN\s*\d{4}",
    re.IGNORECASE,
)
# Ekstrak nomor + tahun untuk verifikasi identitas dokumen
_LAW_ID_RE = re.compile(
    r"(?:NOMOR|NO\.?)\s*([\w./-]+)\s*TAHUN\s*(\d{4})", re.IGNORECASE)
# Subjek hukum: klausa "TENTANG <subjek>" di blok judul — topik kanonik
# dokumen. Isi pasal boleh menyebut istilah apa pun, sehingga verifikasi
# topik HARUS memakai subjek ini, bukan isi. (Pola baku: "…NOMOR n TAHUN
# t TENTANG <subjek> DENGAN RAHMAT TUHAN…")
_LAW_SUBJECT_RE = re.compile(
    r"\bTENTANG\s+(.+?)(?=\s+DENGAN\s+RAHMAT\b|\s+Menimbang\b|\s+Mengingat\b|$)",
    re.IGNORECASE)


class DocumentParser:
    """Unduh dan parse dokumen hukum menjadi struktur pasal."""

    def __init__(self, rate_limit: int | None = None):
        self.rate_limit = rate_limit or settings.alcd_crawl_rate_limit or 1
        self._last_hit: dict[str, float] = {}

    def _throttle(self, url: str) -> None:
        domain = urlparse(url).netloc
        last = self._last_hit.get(domain, 0.0)
        wait = (1.0 / self.rate_limit) - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_hit[domain] = time.monotonic()

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def download(self, url: str, timeout: int = 30) -> tuple[bytes, str] | None:
        """Unduh dokumen. Returns (content_bytes, content_type) atau None."""
        self._throttle(url)
        try:
            resp = None
            for attempt in range(3):
                resp = httpx.get(
                    url,
                    headers={"User-Agent": _UA},
                    timeout=timeout,
                    follow_redirects=True,
                )
                if resp.status_code != 403:
                    break
                wait = 5 * (attempt + 1)
                logger.info("403 dari %s — backoff %ds", url, wait)
                time.sleep(wait)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "").lower()
            return resp.content, ctype
        except Exception as exc:
            logger.warning("Gagal unduh %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _html_to_text(self, html: bytes) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text("\n")

    def _pdf_to_text(self, pdf: bytes) -> str:
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(pdf))
            # KUHP (UU 1/2023) ~345 halaman — jangan potong di 200.
            return "\n".join(
                (p.extract_text() or "") for p in reader.pages[:600]
            )
        except Exception as exc:
            logger.warning("PDF parse gagal: %s", exc)
            return ""

    # Bagian PENJELASAN di akhir UU mengulang nomor pasal — potong sebelum
    # di-split agar pasal normatif tidak tertimpa teks penjelasan.
    _PENJELASAN_RE = re.compile(
        r"(?m)^\s*PENJELASAN\b[^\n]*$", re.IGNORECASE)

    # Penanda struktur di atas pasal (pola pengurai-regulasi):
    # BAB → Bagian → Paragraf. Pasal membawa konteks hierarkinya
    # agar chunk retrieval tidak "yatim" (pattern ID_REG_MD_RAG).
    _STRUCT_RES = [
        ("bab", re.compile(
            r"(?m)^\s*BAB\s+[IVXLCDM]+\b[^\n]*", re.IGNORECASE)),
        ("bagian", re.compile(
            r"(?m)^\s*Bagian\s+Ke?\w+\b[^\n]*", re.IGNORECASE)),
        ("paragraf", re.compile(
            r"(?m)^\s*Paragraf\s+\w+\b[^\n]*", re.IGNORECASE)),
    ]

    def _struct_markers(self, text: str) -> list[tuple[int, int, str]]:
        """(posisi, level, label) untuk BAB/Bagian/Paragraf — label
        digabung baris judul berikutnya bila pendek."""
        marks: list[tuple[int, int, str]] = []
        for level, (_kind, rx) in enumerate(self._STRUCT_RES):
            for m in rx.finditer(text):
                label = m.group(0).strip()
                # Baris berikutnya sering judul bab (huruf besar semua).
                nxt = text[m.end():m.end() + 200].lstrip("\n")
                nline = nxt.split("\n", 1)[0].strip()
                if (nline and len(nline) <= 90
                        and not re.match(r"(?i)(pasal|ayat|bab|bagian|"
                                         r"paragraf)\b", nline)):
                    label = f"{label} {nline}"
                marks.append((m.start(), level, " ".join(label.split())))
        marks.sort()
        return marks

    def _split_articles(self, text: str) -> list[dict]:
        """Pisahkan teks menjadi daftar pasal via marker 'Pasal N',
        masing-masing membawa jalur hierarki Bab/Bagian/Paragraf."""
        penjelasan = self._PENJELASAN_RE.search(text)
        if penjelasan and penjelasan.start() > len(text) // 2:
            text = text[:penjelasan.start()]
        marks = self._struct_markers(text)
        matches = list(_PASAL_RE.finditer(text))
        articles = []
        seen: set[str] = set()
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if len(body) < 30:  # abaikan marker tanpa isi / entri TOC
                continue
            key = f"Pasal {m.group(1)}"
            # Duplikat nomor pasal — pertahankan kemunculan pertama
            # (bagian normatif selalu mendahului penjelasan/TOC)
            if key in seen:
                continue
            seen.add(key)
            # Hierarki aktif: penanda struktur terakhir per level
            # sebelum posisi pasal ini.
            hier: dict[int, str] = {}
            for pos, level, label in marks:
                if pos >= m.start():
                    break
                hier[level] = label
                hier = {lv: lb for lv, lb in hier.items() if lv <= level}
            path = " · ".join(hier[lv] for lv in sorted(hier))
            articles.append({
                "article_number": key,
                "hierarchy": path,
                # Anchor konteks ke isi — chunk tetap tahu ia berada
                # di Bab/Bagian mana (chunk tidak terpotong dari
                # konteks strukturnya).
                "content": (f"[{path}]\n{body}" if path else body)[:8000],
            })
        return articles

    # ------------------------------------------------------------------
    # OCR — fallback untuk PDF scan tanpa text-layer (mis. UU 1/2023 KUHP
    # di BPK). Probe murah dulu (4 halaman, pdftoppm+tesseract 'ind') untuk
    # memastikan dokumen berbentuk UU; baru OCR penuh via ocrmypdf.
    # ------------------------------------------------------------------
    _OCR_PROBE_PAGES = 4

    def _ocr_probe(self, pdf: bytes) -> str:
        """OCR halaman awal — cukup untuk membaca blok judul."""
        import os
        import subprocess
        import tempfile

        try:
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, "in.pdf")
                with open(src, "wb") as f:
                    f.write(pdf)
                subprocess.run(
                    ["pdftoppm", "-r", "200", "-l",
                     str(self._OCR_PROBE_PAGES), "-gray", "-png",
                     src, os.path.join(td, "pg")],
                    check=True, capture_output=True, timeout=180)
                texts = []
                for name in sorted(os.listdir(td)):
                    if name.endswith(".png"):
                        r = subprocess.run(
                            ["tesseract", os.path.join(td, name), "stdout",
                             "-l", "ind", "--psm", "6"],
                            capture_output=True, text=True, timeout=120)
                        texts.append(r.stdout or "")
                return "\n".join(texts)
        except Exception as exc:
            logger.warning("OCR probe gagal: %s", exc)
            return ""

    def _ocr_full(self, pdf: bytes) -> str:
        """OCR seluruh dokumen via ocrmypdf (lapisan teks ind+eng)."""
        import os
        import subprocess
        import tempfile

        try:
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, "in.pdf")
                dst = os.path.join(td, "out.pdf")
                with open(src, "wb") as f:
                    f.write(pdf)
                r = subprocess.run(
                    ["ocrmypdf", "--skip-text", "-l", "ind+eng",
                     "--deskew", "--jobs", "4", src, dst],
                    capture_output=True, timeout=1800)
                if r.returncode != 0:
                    logger.warning("ocrmypdf gagal: %s",
                                   (r.stderr or b"")[:300])
                    return ""
                with open(dst, "rb") as f:
                    return self._pdf_to_text(f.read())
        except Exception as exc:
            logger.warning("OCR penuh gagal: %s", exc)
            return ""

    @staticmethod
    def _details_meta(text: str) -> dict:
        """Metadata halaman Details BPK — Subjek + Status berlaku.

        'Status: Tidak Berlaku / Dicabut' adalah sinyal temporalitas:
        dokumen usang tidak boleh masuk korpus (verifikasi ground-truth
        ala reference-audit, bukan hanya keberadaan file)."""
        meta: dict = {}
        for key, label in (("source_subject", "Subjek"),
                           ("source_status", "Status")):
            m = re.search(
                rf"(?im)^\s*{label}\b[ \t]*:[ \t]*([^\n]{{2,120}})", text)
            if not m:
                m = re.search(
                    rf"(?im)^\s*{label}\b[ \t]*\r?\n[ \t]*([^\n]{{2,120}})",
                    text)
            if m:
                meta[key] = m.group(1).strip()
        return meta

    @staticmethod
    def _pick_pdf_link(page_url: str, links: list[str]) -> str | None:
        """Pilih link unduhan PDF yang identitas filename-nya cocok
        identitas slug halaman detail; fallback link pertama."""
        if not links:
            return None
        from urllib.parse import unquote

        def _ident(u: str) -> tuple[str, str] | None:
            m = re.search(
                r"(?:Nomor|No\.?)[-_ %]*(\d+)[-_ %]*Tahun[-_ %]*(\d{4})",
                unquote(u), re.IGNORECASE)
            return (m.group(1), m.group(2)) if m else None

        slug = _ident(page_url)
        if slug:
            for link in links:
                if _ident(link) == slug:
                    return link
        return links[0]

    def parse(self, url: str) -> dict | None:
        """Unduh + parse dokumen jadi `{"law_name", "articles", "source_url"}`.

        Returns None jika dokumen tidak dapat diunduh atau tidak
        mengandung pasal sama sekali.
        """
        fetched = self.download(url)
        if not fetched:
            return None
        content, ctype = fetched
        meta: dict = {}

        if "pdf" in ctype or url.lower().endswith(".pdf"):
            pdf_bytes: bytes | None = content
            text = self._pdf_to_text(content)
        else:
            pdf_bytes = None
            text = self._html_to_text(content)
            # Halaman detail (bukan PDF langsung): ikuti link /Download/*.pdf.
            # ID /Download/<file_id> ≠ ID /Details/<record_id> — halaman
            # bisa memuat beberapa berkas; pilih yang identitas filename-
            # nya cocok dengan slug halaman (LexisAI: 'uu-no-17-2016').
            if (not text or len(text) < 200 or
                    not self._split_articles(text)):
                meta = self._details_meta(text)
                pdf_links = re.findall(
                    r'href="(/Download/[^"]+?\.pdf)"',
                    content.decode("utf-8", "ignore"), re.IGNORECASE)
                picked = self._pick_pdf_link(url, pdf_links)
                if picked:
                    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                    fetched = self.download(base + picked)
                    if fetched and "pdf" in fetched[1].lower():
                        url = base + picked
                        pdf_bytes = fetched[0]
                        text = self._pdf_to_text(pdf_bytes)

        # OCR fallback — PDF scan tanpa text-layer. Probe halaman awal
        # dulu: hanya dokumen berbentuk UU (blok NOMOR/TAHUN terbaca) yang
        # layak menjalani OCR penuh — hemat menit CPU untuk kandidat salah.
        if (pdf_bytes and settings.alcd_ocr_enabled
                and len(self._split_articles(text or "")) < 5):
            probe = " ".join(self._ocr_probe(pdf_bytes).split())
            if _LAW_NUMBERED_RE.search(probe):
                logger.info("PDF scan — OCR penuh %s", url)
                ocr_text = self._ocr_full(pdf_bytes)
                if len(ocr_text) > len(text or ""):
                    text = ocr_text

        if not text or len(text) < 200:
            return None

        articles = self._split_articles(text)
        if not articles:
            return None

        # Identitas UU hanya dari blok judul — bagian "Mengingat" merujuk
        # UU LAIN dan mengecoh ekstraksi nomor/tahun. Judul PDF sering
        # terbelah antar-baris → normalisasi whitespace dulu.
        header_end = re.search(
            r"(?i)\b(mengingat|menimbang|dengan rahmat)", text[:6000])
        header = " ".join(
            (text[: header_end.start()] if header_end else text[:2000])
            .split())
        law_match = (
            _LAW_NUMBERED_RE.search(header)
            or _LAW_NAME_RE.search(header)
        )
        law_name = (
            " ".join(law_match.group(0).split()) if law_match else "Unknown Law"
        )
        law_number = law_year = None
        if law_match:
            idm = _LAW_ID_RE.search(law_match.group(0))
            if idm and idm.group(1).isdigit():
                law_number, law_year = idm.group(1), idm.group(2)
        subj_match = _LAW_SUBJECT_RE.search(header)
        law_subject = (
            " ".join(subj_match.group(1).split()) if subj_match else None
        )
        chapters = len(_BAB_RE.findall(text))
        return {
            "law_name": law_name,
            "law_number": law_number,
            "law_year": law_year,
            "law_subject": law_subject,
            "articles": articles,
            "chapter_count": chapters,
            "source_url": url,
            **meta,
        }
