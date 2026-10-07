"""
Graph Builder — ALCD Fase 2d.

Membangun node `LegalArticle` (scope GLOBAL — tanpa institution_id) di
Neo4j beserta relasi `CROSS_REFERENCES`, `SUPERSEDES`, `CONTRADICTS`
lintas undang-undang yang diidentifikasi via regex + opsional LLM.
"""
import logging
import re

logger = logging.getLogger("ala.alcd.graph")

# Pola referensi pasal lintas-UU dalam teks Indonesia, misal:
#   "Pasal 55 ayat (1) KUHP" / "sebagaimana dimaksud dalam Pasal 30 UU ITE"
_XREF_RE = re.compile(
    r"Pasal\s+(\d+[A-Za-z]?)\s+(?:ayat\s*\(\d+\)\s+)?"
    r"(KUHP|KUHAP|UU\s+(?:Nomor\s+|No\.?\s*)?[\w./\-]{1,40}"
    r"|Undang[-\s]Undang\s+(?:Nomor\s+|No\.?\s*)?[\w./\-]{1,40})",
    re.IGNORECASE,
)


def upsert_legal_articles(driver, law_name: str, articles: list[dict]) -> int:
    """Buat/update node LegalArticle (GLOBAL). Returns jumlah node."""
    query = """
    UNWIND $articles AS art
    MERGE (a:LegalArticle {law_name: $law_name,
                           article_number: art.article_number})
    SET a.content = art.content,
        a.title = coalesce(art.title, ''),
        a.scope = 'GLOBAL',
        a.updated_at = datetime()
    RETURN count(a) AS n
    """
    with driver.session() as session:
        result = session.run(
            query, law_name=law_name,
            articles=[{"article_number": a["article_number"],
                       "content": a["content"][:4000],
                       "title": a.get("title", "")} for a in articles],
        )
        return result.single()["n"]


def extract_cross_references(articles: list[dict], law_name: str) -> list[dict]:
    """Ekstrak referensi silang antar pasal dari isi teks (regex)."""
    refs = []
    for art in articles:
        for m in _XREF_RE.finditer(art.get("content", "")):
            target_article = f"Pasal {m.group(1)}"
            target_law = " ".join((m.group(2) or "").split()) or law_name
            if target_article == art["article_number"]:
                continue
            refs.append({
                "from_law": law_name,
                "from_article": art["article_number"],
                "to_law": target_law,
                "to_article": target_article,
            })
    # Deduplikasi
    seen, unique = set(), []
    for r in refs:
        key = (r["from_article"], r["to_law"], r["to_article"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def build_cross_references(driver, refs: list[dict]) -> int:
    """MERGE relasi CROSS_REFERENCES antar LegalArticle (GLOBAL)."""
    if not refs:
        return 0
    query = """
    UNWIND $refs AS r
    MATCH (a:LegalArticle {law_name: r.from_law,
                           article_number: r.from_article})
    MERGE (b:LegalArticle {law_name: r.to_law,
                           article_number: r.to_article})
    ON CREATE SET b.scope = 'GLOBAL', b.content = '', b.title = ''
    MERGE (a)-[:CROSS_REFERENCES]->(b)
    RETURN count(*) AS n
    """
    with driver.session() as session:
        result = session.run(query, refs=refs)
        return result.single()["n"]


def build_graph_for_document(law_name: str, articles: list[dict]) -> dict:
    """Pipeline penuh: node + cross-references untuk satu dokumen.

    Returns `{"nodes": int, "edges": int}` — 0 jika Neo4j tidak tersedia.
    """
    from app.database.neo4j import get_neo4j_driver

    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j tidak tersedia: %s", exc)
        return {"nodes": 0, "edges": 0}
    try:
        nodes = upsert_legal_articles(driver, law_name, articles)
        refs = extract_cross_references(articles, law_name)
        edges = build_cross_references(driver, refs)
        logger.info("Graph %s: %d node, %d relasi", law_name, nodes, edges)
        return {"nodes": nodes, "edges": edges}
    finally:
        driver.close()
