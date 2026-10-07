"""
Source Discoverer — ALCD Fase 2a.

Menemukan repositori hukum resmi via Google Custom Search Engine (CSE),
dengan prioritas domain terpercaya (JDIH, BPK, MA). Fallback ke
DuckDuckGo HTML search jika kunci CSE tidak dikonfigurasi.

Rate limit ketat: maks ALCD_CRAWL_RATE_LIMIT request/detik per domain.
"""
import logging
import time
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger("ala.alcd.discoverer")

_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"

# Domain resmi prioritas (selain yang di settings.alcd_trusted_domains)
_DEFAULT_TRUSTED = (
    "jdih.kemenkumham.go.id",
    "peraturan.bpk.go.id",
    "putusan3.mahkamahagung.go.id",
    "jdihn.go.id",
)


def _trusted_domains() -> tuple[str, ...]:
    extra = tuple(
        d.strip() for d in settings.alcd_trusted_domains.split(",") if d.strip()
    )
    return tuple(dict.fromkeys((*_DEFAULT_TRUSTED, *extra)))


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


class SourceDiscoverer:
    """Penemu sumber hukum otoritatif untuk node ontologi."""

    def __init__(self, rate_limit: int | None = None):
        self.rate_limit = rate_limit or settings.alcd_crawl_rate_limit or 1
        self._last_hit: dict[str, float] = {}
        self._ddg_dead = False  # circuit breaker — DDG sering diblokir ISP

    # ------------------------------------------------------------------
    # Rate limiting per domain
    # ------------------------------------------------------------------
    def _throttle(self, domain: str) -> None:
        last = self._last_hit.get(domain, 0.0)
        wait = (1.0 / self.rate_limit) - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_hit[domain] = time.monotonic()

    # ------------------------------------------------------------------
    # Query formulation
    # ------------------------------------------------------------------
    def build_queries(self, node: dict) -> list[str]:
        """Formulasikan search queries untuk satu node ontologi."""
        sub = node.get("subcategory") or node.get("category", "")
        queries = [
            f"{sub} undang-undang teks lengkap site:peraturan.bpk.go.id",
            f"{sub} pdf site:jdih.kemenkumham.go.id",
            f"download {sub} full text indonesia hukum",
        ]
        if "yurisprudensi" in (node.get("category") or "").lower():
            queries.append(f"{sub} site:putusan3.mahkamahagung.go.id")
        return queries

    # ------------------------------------------------------------------
    # Search backends
    # ------------------------------------------------------------------
    def _google_cse(self, query: str, num: int) -> list[dict]:
        """Google Custom Search API (butuh GOOGLE_CSE_ID + API_KEY)."""
        cse_id = getattr(settings, "google_cse_id", "") or ""
        api_key = getattr(settings, "google_cse_api_key", "") or ""
        if not cse_id or not api_key:
            return []
        self._throttle("googleapis.com")
        try:
            resp = httpx.get(
                _GOOGLE_CSE_URL,
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": min(num, 10),
                    "lr": "lang_id",
                    "gl": "id",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [
                {
                    "title": it.get("title", ""),
                    "url": it.get("link", ""),
                    "snippet": it.get("snippet", ""),
                }
                for it in items
            ]
        except Exception as exc:
            logger.warning("Google CSE gagal: %s", exc)
            return []

    def _duckduckgo(self, query: str, num: int) -> list[dict]:
        """Fallback gratis — DuckDuckGo HTML search."""
        if self._ddg_dead:
            return []
        self._throttle("duckduckgo.com")
        try:
            resp = httpx.post(
                _DDG_HTML_URL,
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (ALA Legal Bot)"},
                timeout=10.0,
                follow_redirects=True,
            )
            resp.raise_for_status()
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            for res in soup.select(".result")[:num]:
                a = res.select_one(".result__a")
                snip = res.select_one(".result__snippet")
                if a and a.get("href"):
                    results.append({
                        "title": a.get_text(strip=True),
                        "url": a["href"],
                        "snippet": snip.get_text(strip=True) if snip else "",
                    })
            return results
        except Exception as exc:
            logger.warning("DuckDuckGo search gagal: %s", exc)
            # SSL/DNS hijack (ISP) → matikan DDG untuk sisa sesi
            if "SSL" in str(exc) or "CERTIFICATE" in str(exc).upper():
                logger.warning("DDG tidak dapat dijangkau — dimatikan")
                self._ddg_dead = True
            return []

    def _bpk_search(self, query: str, num: int) -> list[dict]:
        """Fallback langsung portal resmi BPK — berguna saat mesin pencari
        (CSE/DDG) tidak tersedia/diblokir ISP. Mengembalikan link
        /Download/*.pdf dan /Details/* dari peraturan.bpk.go.id."""
        # Bersihkan operator pencarian (site:, filetype:, pdf dsb.) —
        # portal BPK hanya menerima kata kunci polos
        import re as _re
        keywords = _re.sub(r"\b(site|filetype|inurl):[^\s]+", "", query)
        keywords = _re.sub(r"\bpdf\b|\bdownload\b|\bfull text\b", "",
                           keywords, flags=_re.IGNORECASE).strip()
        self._throttle("peraturan.bpk.go.id")
        try:
            resp = None
            for attempt in range(3):
                resp = httpx.get(
                    "https://peraturan.bpk.go.id/Search",
                    params={"keywords": keywords},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "id-ID,id;q=0.9",
                    },
                    timeout=15.0,
                    follow_redirects=True,
                )
                if resp.status_code != 403:
                    break
                wait = 5 * (attempt + 1)
                logger.info("BPK 403 — backoff %ds (attempt %d)", wait, attempt + 1)
                time.sleep(wait)
            resp.raise_for_status()
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            seen_paths: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not (href.startswith("/Download/") or
                        href.startswith("/Details/")):
                    continue
                if href in seen_paths:
                    continue
                seen_paths.add(href)
                url = f"https://peraturan.bpk.go.id{href}"
                # Prioritaskan PDF /Download — langsung bisa diparse
                title = a.get_text(strip=True) or href.rsplit("/", 1)[-1]
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": "",
                    "_is_pdf": href.startswith("/Download/"),
                })
                if len(results) >= num * 2:
                    break
            # PDF dulu, lalu halaman detail
            results.sort(key=lambda r: not r["_is_pdf"])
            return results[:num]
        except Exception as exc:
            logger.warning("BPK search gagal: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def discover(self, node: dict, max_per_query: int = 5) -> list[dict]:
        """Temukan sumber untuk satu node ontologi, prioritas domain resmi.

        Returns:
            List `{"title", "url", "snippet", "domain", "trusted"}` —
            diurutkan: domain terpercaya dulu.
        """
        trusted = _trusted_domains()
        seen: set[str] = set()
        results: list[dict] = []

        for query in self.build_queries(node):
            hits = (
                self._google_cse(query, max_per_query)
                or self._duckduckgo(query, max_per_query)
                or self._bpk_search(query, max_per_query)
            )
            for hit in hits:
                url = hit["url"]
                if not url or url in seen:
                    continue
                seen.add(url)
                dom = _domain(url)
                hit["domain"] = dom
                hit["trusted"] = any(
                    dom == t or dom.endswith("." + t) for t in trusted
                )
                results.append(hit)

        # Domain terpercaya diurutkan lebih dulu
        results.sort(key=lambda h: (not h["trusted"], h["domain"]))
        return results
