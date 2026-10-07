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
            return "\n".join(
                (p.extract_text() or "") for p in reader.pages[:200]
            )
        except Exception as exc:
            logger.warning("PDF parse gagal: %s", exc)
            return ""

    def _split_articles(self, text: str) -> list[dict]:
        """Pisahkan teks menjadi daftar pasal via marker 'Pasal N'."""
        matches = list(_PASAL_RE.finditer(text))
        articles = []
        seen: dict[str, int] = {}
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if len(body) < 30:  # abaikan marker tanpa isi / entri TOC
                continue
            key = f"Pasal {m.group(1)}"
            # Duplikat nomor pasal (penjelasan di akhir dokumen) — simpan
            # versi yang lebih panjang (isi pasal, bukan penjelasan)
            if key in seen:
                idx = seen[key]
                if len(body) > len(articles[idx]["content"]):
                    articles[idx]["content"] = body[:8000]
                continue
            seen[key] = len(articles)
            articles.append({
                "article_number": key,
                "content": body[:8000],
            })
        return articles

    def parse(self, url: str) -> dict | None:
        """Unduh + parse dokumen jadi `{"law_name", "articles", "source_url"}`.

        Returns None jika dokumen tidak dapat diunduh atau tidak
        mengandung pasal sama sekali.
        """
        fetched = self.download(url)
        if not fetched:
            return None
        content, ctype = fetched

        if "pdf" in ctype or url.lower().endswith(".pdf"):
            text = self._pdf_to_text(content)
        else:
            text = self._html_to_text(content)
        if not text or len(text) < 200:
            return None

        articles = self._split_articles(text)
        if not articles:
            return None

        law_match = (
            _LAW_NUMBERED_RE.search(text[:4000])
            or _LAW_NAME_RE.search(text[:3000])
        )
        law_name = (
            " ".join(law_match.group(0).split()) if law_match else "Unknown Law"
        )
        chapters = len(_BAB_RE.findall(text))
        return {
            "law_name": law_name,
            "articles": articles,
            "chapter_count": chapters,
            "source_url": url,
        }
