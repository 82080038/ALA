"""
Internet Crawler Agent — Agent 2.

Mencari tren kejahatan dari SEMUA kategori (pidana umum, korupsi,
narkotika, TPPU, siber, transnasional, finansial) di internet publik,
berdasarkan konteks hukum yang dibangun Legal Foundation Agent.
Hanya domain publik — tidak ada dark web.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import get_llm_reasoning, settings

logger = logging.getLogger("ala.agents.internet_crawler")

_UA = "Mozilla/5.0 (compatible; ALA-TrendCrawler/1.0)"
_TIMEOUT = 10  # timeout keras per halaman (detik)
_RATE_LIMIT = 1  # maks 1 request/detik per domain
_MAX_QUERIES = 4
_MAX_PAGES = 5
_MAX_RESULTS_PER_QUERY = 10

# Domain berita/otoritatif yang diprioritaskan
_PREFERRED_HINTS = (
    "jdih.", "peraturan.go.id", "kpk.go.id", "bnn.go.id", "polri.go.id",
    "kejaksaan.go.id", "mahkamahagung.go.id", "putusan",
    "kompas.com", "detik.com", "tempo.co", "antaranews.com",
    "cnnindonesia.com", "liputan6.com",
)

_SUMMARY_PROMPT = """Berdasarkan sumber-sumber berita berikut, tulis
ringkasan tren kejahatan dalam Bahasa Indonesia (maks 3 paragraf).
Hubungkan dengan konteks hukum jika relevan.

Konteks hukum: {legal_summary}

Sumber:
{sources}

Ringkasan:"""

_last_domain_hit: dict[str, float] = {}


def _throttle(url: str) -> None:
    domain = urlparse(url).netloc
    last = _last_domain_hit.get(domain, 0.0)
    wait = (1.0 / _RATE_LIMIT) - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    _last_domain_hit[domain] = time.monotonic()


def _is_allowed_domain(url: str) -> bool:
    """Tolak domain gelap/tidak diperbolehkan — hanya internet publik."""
    host = urlparse(url).netloc.lower()
    blocked = (".onion", ".i2p", "darknet", "telegram.", "t.me")
    return not any(b in host for b in blocked)


def _formulate_queries(query: str, legal_summary: str) -> list[str]:
    """Query asli + variasi kontekstual dari landasan hukum."""
    queries = [f"{query} Indonesia", f"{query} modus operandi terbaru"]
    if legal_summary:
        queries.append(f"{query} kasus 2025 2026")
        queries.append(f"{query} penegakan hukum putusan")
    return queries[:_MAX_QUERIES]


def _google_cse_search(query: str) -> list[dict]:
    """Cari via Google Custom Search API. Returns list hasil."""
    if not (settings.google_cse_id and settings.google_cse_api_key):
        return []
    try:
        resp = httpx.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": settings.google_cse_api_key,
                "cx": settings.google_cse_id,
                "q": query,
                "num": _MAX_RESULTS_PER_QUERY,
                "lr": "lang_id",
                "gl": "ID",
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        return [
            {
                "title": it.get("title", ""),
                "url": it.get("link", ""),
                "snippet": it.get("snippet", ""),
                "published_date": (
                    it.get("pagemap", {}).get("metatags", [{}])[0]
                    .get("article:published_time")
                ),
            }
            for it in resp.json().get("items", [])
        ]
    except Exception as exc:
        logger.warning("CSE search gagal untuk '%s': %s", query, exc)
        return []


_NEWS_RSS = "https://news.google.com/rss/search"


def _google_news_search(query: str) -> list[dict]:
    """Fallback tanpa API key — Google News RSS (publik, bahasa ID).

    Mesin pencari umum sering diblokir ISP; RSS ini menyediakan judul +
    tautan + tanggal untuk tren kejahatan secara andal.
    """
    try:
        resp = httpx.get(
            _NEWS_RSS,
            params={"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"},
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.text)
        items = []
        for item in root.findall(".//item")[:_MAX_RESULTS_PER_QUERY]:
            items.append({
                "title": (item.findtext("title") or "").strip(),
                "url": (item.findtext("link") or "").strip(),
                "snippet": (item.findtext("description") or "")[:500],
                "published_date": item.findtext("pubDate"),
            })
        return [i for i in items if i["url"]]
    except Exception as exc:
        logger.warning("Google News RSS gagal: %s", exc)
        return []


async def _fetch_page_playwright(url: str) -> str | None:
    """Fetch halaman via Playwright headless (untuk situs JS-heavy)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = await browser.new_page(user_agent=_UA)
                await page.goto(
                    url, wait_until="domcontentloaded",
                    timeout=_TIMEOUT * 1000,
                )
                return await page.content()
            finally:
                await browser.close()
    except Exception as exc:
        logger.debug("Playwright gagal %s: %s", url, exc)
        return None


def _fetch_page_sync(url: str) -> str | None:
    """Jalankan fetch Playwright di thread terpisah — `asyncio.run`
    tidak bisa dipanggil dari dalam event loop yang sudah berjalan
    (LangGraph invoke berjalan dalam konteks async)."""
    import concurrent.futures

    def _run():
        return asyncio.run(_fetch_page_playwright(url))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run).result(timeout=_TIMEOUT * 2 + 10)
    except Exception as exc:
        logger.debug("Playwright thread gagal %s: %s", url, exc)
        return None


def _fetch_page_http(url: str) -> str | None:
    """Fetch halaman via httpx (fallback cepat untuk situs statis)."""
    try:
        resp = httpx.get(url, headers={"User-Agent": _UA},
                         timeout=_TIMEOUT, follow_redirects=True)
        if resp.status_code == 200 and "text/html" in resp.headers.get(
            "content-type", ""
        ):
            return resp.text
    except Exception as exc:
        logger.debug("HTTP fetch gagal %s: %s", url, exc)
    return None


def _extract_content(html: str, url: str) -> dict | None:
    """Ekstrak judul, tanggal, dan teks utama dari HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("meta", property="og:title")
    title = (
        title_tag["content"] if title_tag and title_tag.get("content")
        else (soup.title.string if soup.title else "")
    )
    date_tag = soup.find("meta", property="article:published_time") or \
        soup.find("meta", attrs={"name": "publishdate"})
    published = date_tag["content"] if date_tag and date_tag.get(
        "content") else None
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    body = " ".join(soup.get_text(" ").split())
    if len(body) < 200:
        return None
    return {
        "title": (title or "").strip(),
        "url": url,
        "snippet": body[:1200],
        "published_date": published,
    }


def _rank_sources(sources: list[dict]) -> list[dict]:
    """Prioritaskan domain tepercaya, dedup URL."""
    seen, out = set(), []
    for src in sources:
        url = src.get("url", "")
        if not url or url in seen or not _is_allowed_domain(url):
            continue
        seen.add(url)
        host = urlparse(url).netloc.lower()
        src["_score"] = (
            1 if any(h in host for h in _PREFERRED_HINTS) else 0
        )
        out.append(src)
    out.sort(key=lambda s: s["_score"], reverse=True)
    for s in out:
        s.pop("_score", None)
    return out[:_MAX_PAGES]


def _summarize(legal_summary: str, sources: list[dict]) -> str:
    """Ringkas tren kejahatan via LLM penalaran (GPU 0)."""
    if not sources:
        return ""
    src_text = "\n".join(
        f"- [{s['title']}]({s['url']}): {s['snippet'][:300]}"
        for s in sources
    )
    try:
        llm = get_llm_reasoning()
        resp = llm.invoke(_SUMMARY_PROMPT.format(
            legal_summary=legal_summary[:800],
            sources=src_text[:4000],
        ))
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        logger.warning("Ringkasan tren gagal: %s", exc)
        return f"{len(sources)} sumber relevan ditemukan."


def internet_crawler_agent(state) -> dict:
    """Node LangGraph: crawl tren kejahatan dari internet publik."""
    audit = {
        "agent": "internet_crawler",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    updates: dict = {"audit_trail": [audit]}
    query = state.get("query", "")
    legal_summary = state.get("legal_summary", "")

    try:
        candidates = []
        for q in _formulate_queries(query, legal_summary):
            hits = _google_cse_search(q) or _google_news_search(q)
            candidates.extend(hits)
        ranked = _rank_sources(candidates)

        crime_data = []
        for src in ranked:
            try:
                _throttle(src["url"])
                # Playwright dulu (JS-heavy), fallback httpx
                html = _fetch_page_sync(src["url"]) or \
                    _fetch_page_http(src["url"])
                if not html:
                    # tetap simpan snippet dari hasil pencarian
                    if src.get("snippet"):
                        crime_data.append(src)
                    continue
                extracted = _extract_content(html, src["url"])
                crime_data.append(extracted or src)
            except Exception as exc:
                logger.warning("Fetch %s gagal: %s", src["url"], exc)
                if src.get("snippet"):
                    crime_data.append(src)

        updates["crime_data"] = crime_data
        updates["crime_summary"] = _summarize(legal_summary, crime_data)
        audit.update(status="success", sources_found=len(crime_data),
                     candidates=len(candidates))
    except Exception as exc:
        logger.exception("Internet Crawler error")
        audit.update(status="error", error=str(exc))
        updates["errors"] = [f"Internet Crawler Agent error: {exc}"]
        # Pertahankan hasil parsial — jangan hapus crime_data
        updates.setdefault("crime_data", [])
        updates.setdefault("crime_summary", "")
    return updates
