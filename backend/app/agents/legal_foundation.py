"""
Legal Foundation Agent — Agent 1 (Law-First).

Pencarian pertama SELALU di basis pengetahuan hukum GLOBAL: ChromaDB
`indonesian_laws` untuk RAG pasal + Neo4j `LegalArticle` untuk
referensi silang. Query pengguna tidak pernah langsung masuk ke web
scraper atau code generator.
"""
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger("ala.agents.legal_foundation")

_XREF_QUERY = """
MATCH (a:LegalArticle)
WHERE a.law_name CONTAINS $q OR a.content CONTAINS $q
OPTIONAL MATCH (a)-[r:CROSS_REFERENCES]->(b:LegalArticle)
RETURN a.law_name AS law, a.article_number AS article,
       collect(DISTINCT {law: b.law_name, article: b.article_number})[0..5] AS refs
LIMIT $limit
"""


def _rag_retrieve(query: str, n_results: int = 8) -> list[dict]:
    """Cari artikel relevan di ChromaDB GLOBAL (tanpa filter tenant)."""
    from app.database.chroma import get_chroma_client, get_laws_collection

    try:
        collection = get_laws_collection(get_chroma_client())
        hits = collection.query(
            query_texts=[query],
            n_results=n_results,
        )
    except Exception as exc:
        logger.warning("ChromaDB query gagal: %s", exc)
        return []

    articles = []
    docs = hits.get("documents", [[]])[0]
    metas = hits.get("metadatas", [[]])[0]
    dists = hits.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        articles.append({
            "law_name": meta.get("law_name", "Unknown"),
            "article_number": meta.get("article_number", ""),
            "content": doc,
            "relevance_score": round(max(0.0, 1.0 - float(dist)), 3),
            "source_url": meta.get("source_url", ""),
            "topic": meta.get("topic", ""),
        })
    return articles


def _graph_xrefs(query: str, limit: int = 5) -> list[dict]:
    """Ambil referensi silang dari Neo4j GLOBAL."""
    from app.database.neo4j import get_neo4j_driver

    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j tidak tersedia: %s", exc)
        return []
    try:
        with driver.session() as session:
            rows = session.run(
                _XREF_QUERY,
                q=_extract_law_hint(query), limit=limit,
            ).data()
        return [
            {
                "from_law": r["law"],
                "from_article": r["article"],
                "to": r["refs"],
            }
            for r in rows if r["refs"]
        ]
    except Exception as exc:
        logger.warning("Neo4j xref query gagal: %s", exc)
        return []
    finally:
        driver.close()


def _extract_law_hint(query: str) -> str:
    """Ambil nomor UU/pasal dari query sebagai petunjuk pencarian."""
    m = re.search(r"(UU\s*\d+|Pasal\s*\d+|KUHP|KUHAP|ITE|Tipikor|Narkotika)",
                  query, re.IGNORECASE)
    return m.group(0) if m else query[:60]


def _dedup_articles(articles: list[dict], token_budget: int) -> list[dict]:
    """Dedup (law_name, article_number) lalu pangkas sesuai token budget."""
    seen, unique = set(), []
    for art in articles:
        key = (art["law_name"], art["article_number"])
        if key not in seen:
            seen.add(key)
            unique.append(art)
    # Perkiraan 1 token ≈ 4 karakter; alokasi 50% budget untuk konteks hukum
    char_cap = int(token_budget * 0.5 * 4)
    out, used = [], 0
    for art in unique:
        size = len(art["content"])
        if used + size > char_cap:
            art["content"] = art["content"][: max(0, char_cap - used)]
            out.append(art)
            break
        out.append(art)
        used += size
    return out


_SUMMARY_PROMPT = """Berdasarkan pasal-pasal hukum berikut, tulis
ringkasan landasan hukum untuk query pengguna dalam Bahasa Indonesia
(maks 2 paragraf). Sebutkan UU dan pasal kunci.

QUERY: {query}

PASAL RELEVAN:
{articles}

Ringkasan landasan hukum:"""


def _summarize_legal(query: str, articles: list[dict]) -> str:
    """Ringkas landasan hukum via LLM penalaran (GPU 0)."""
    if not articles:
        return ""
    art_text = "\n".join(
        f"- {a['law_name']} {a['article_number']}: {a['content'][:200]}"
        for a in articles[:8]
    )
    try:
        from app.config import get_llm_reasoning

        llm = get_llm_reasoning()
        resp = llm.invoke(_SUMMARY_PROMPT.format(
            query=query, articles=art_text[:4000]))
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        logger.warning("Ringkasan hukum gagal: %s", exc)
        return f"{len(articles)} pasal relevan ditemukan."


def legal_foundation_agent(state) -> dict:
    """Node LangGraph: retrieval hukum dari basis pengetahuan GLOBAL."""
    audit = {
        "agent": "legal_foundation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    updates: dict = {"audit_trail": [audit]}
    query = state.get("query", "")
    budget = state.get("context_token_budget") or 2048

    try:
        articles = _rag_retrieve(query)
        xrefs = _graph_xrefs(query)
        articles = _dedup_articles(articles, budget)
        summary = _summarize_legal(query, articles)
    except Exception as exc:
        logger.exception("Legal Foundation error")
        audit.update(status="error", error=str(exc))
        updates["errors"] = [f"Legal Foundation Agent error: {exc}"]
        updates["legal_articles"] = []
        updates["legal_cross_references"] = []
        updates["legal_summary"] = ""
        return updates

    updates["legal_articles"] = articles
    updates["legal_cross_references"] = xrefs
    updates["legal_summary"] = summary
    audit.update(
        status="success",
        articles_found=len(articles),
        cross_references=len(xrefs),
        token_budget=budget,
    )
    return updates
