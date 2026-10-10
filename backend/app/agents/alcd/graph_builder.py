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
        a.updated_at = datetime(),
        a.elements = coalesce(art.elements, a.elements)
    RETURN count(a) AS n
    """
    import json as _json
    from app.agents.alcd.element_parser import extract_elements

    with driver.session() as session:
        result = session.run(
            query, law_name=law_name,
            articles=[{"article_number": a["article_number"],
                       "content": a["content"][:4000],
                       "title": a.get("title", ""),
                       "elements": (
                           _json.dumps(extract_elements(a["content"]),
                                       ensure_ascii=False)
                           if extract_elements(a["content"]) else None)}
                      for a in articles],
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


# Sitasi dalam putusan: "Pasal 111 ayat (1) UU RI Nomor 35 Tahun 2009",
# "Pasal 3 UU No. 8 Tahun 2010", "Pasal 55 KUHP". Target di-resolve ke
# law_name KANONIK registry (bukan teks mentah sitasi — "UU Nomor 35
# Tahun 2009" ≠ node "UU Nomor 35 Tahun 2009 tentang Narkotika").
_CITE_UU_RE = re.compile(
    r"Pasal\s+(\d+[A-Za-z]?)\s+(?:ayat\s*\([^)]*\)\s*)*"
    r"(?:UU|Undang[-\s]?Undang)(?:\s+RI)?\s+"
    r"(?:No(?:mor)?\.?\s*)?(\d+)\s+Tahun\s+(\d{4})",
    re.IGNORECASE,
)
_CITE_ALIAS_RE = re.compile(
    r"Pasal\s+(\d+[A-Za-z]?)\s+(?:ayat\s*\([^)]*\)\s*)*"
    r"(KUHP|KUHAP)\b",
    re.IGNORECASE,
)
_ALIAS_LAW = {"KUHP": ("1", "1946"), "KUHAP": ("8", "1981")}

# Dasar hukum utuh tanpa pasal — "Mengingat: Undang-Undang Nomor 2
# Tahun 2002" pada konsiderans Perkap/Perja/Peraturan. Ditambatkan ke
# Pasal 1 UU target (jangkar kanonik; edge = "dokumen menyitasi UU").
_BARE_UU_RE = re.compile(
    r"(?:UU|Undang[-\s]?Undang)(?:\s+RI)?\s+"
    r"(?:No(?:mor)?\.?\s*)(\d+)\s+Tahun\s+(\d{4})",
    re.IGNORECASE,
)


def build_law_name_map(db) -> dict:
    """Peta (nomor, tahun) → law_name kanonik registry — resolver untuk
    sitasi putusan dan referensi silang."""
    from sqlalchemy import select

    from app.models.operational import KnowledgeRegistry

    out: dict[tuple[str, str], str] = {}
    rows = db.scalars(
        select(KnowledgeRegistry).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
    ).all()
    for r in rows:
        key = None
        yr = (r.metadata_ or {}).get("law_year") if r.metadata_ else None
        if r.law_number and yr:
            key = (r.law_number.lstrip("0"), str(yr))
        else:
            m = re.search(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})",
                          r.law_name or "")
            if m:
                key = (m.group(1).lstrip("0"), m.group(2))
        if key and key not in out:
            out[key] = r.law_name
    return out


def extract_putusan_citations(
    articles: list[dict], law_map: dict
) -> list[dict]:
    """Ekstrak sitasi pasal→UU dari teks putusan. Hanya sitasi yang
    targetnya ter-resolve ke dokumen registry (law_map) yang keluar."""
    refs = []
    for art in articles:
        src = art.get("article_number", "")
        content = art.get("content", "")
        for m in _CITE_UU_RE.finditer(content):
            tgt = law_map.get((m.group(2).lstrip("0"), m.group(3)))
            if tgt:
                refs.append({
                    "from_article": src,
                    "to_law": tgt,
                    "to_article": f"Pasal {m.group(1)}",
                })
        for m in _CITE_ALIAS_RE.finditer(content):
            key = _ALIAS_LAW.get(m.group(2).upper())
            tgt = law_map.get(key) if key else None
            if tgt:
                refs.append({
                    "from_article": src,
                    "to_law": tgt,
                    "to_article": f"Pasal {m.group(1)}",
                })
        # Sitasi UU utuh (tanpa pasal) — dasar hukum/konsiderans.
        cited_spans = [m.span() for m in _CITE_UU_RE.finditer(content)]
        cited_laws = {r["to_law"] for r in refs if r["from_article"] == src}
        for m in _BARE_UU_RE.finditer(content):
            if any(s <= m.start() < e for s, e in cited_spans):
                continue  # bagian dari sitasi ber-pasal
            tgt = law_map.get((m.group(1).lstrip("0"), m.group(2)))
            if tgt and tgt not in cited_laws:
                cited_laws.add(tgt)
                refs.append({
                    "from_article": src,
                    "to_law": tgt,
                    "to_article": "Pasal 1",
                })
    seen, unique = set(), []
    for r in refs:
        k = (r["from_article"], r["to_law"], r["to_article"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    return unique


def link_putusan_citations(
    driver, putusan_name: str, articles: list[dict], refs: list[dict]
) -> int:
    """Edge CITES putusan→pasal UU (GLOBAL). Sumber = seksi putusan yang
    menyitasi (node di-upsert); target harus pasal NYATA di graph —
    MATCH di kedua ujung, tidak membuat node stub untuk pasal fiktif."""
    if not refs:
        return 0
    citing = {r["from_article"] for r in refs}
    upsert_legal_articles(
        driver, putusan_name,
        [a for a in articles if a["article_number"] in citing])
    query = """
    UNWIND $refs AS r
    MATCH (a:LegalArticle {law_name: $pn, article_number: r.from_article})
    MATCH (b:LegalArticle {law_name: r.to_law, article_number: r.to_article})
    MERGE (a)-[:CITES]->(b)
    RETURN count(*) AS n
    """
    with driver.session() as session:
        return session.run(query, pn=putusan_name, refs=refs).single()["n"]


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


def link_law_relations(law_name: str, revokes: list[str],
                       amends: list[str],
                       amended_by: list[str] | None = None) -> int:
    """Bangun node LegalDoc tingkat-undang-undang + edge REVOKES/AMENDS
    (GLOBAL). Berbeda dengan CROSS_REFERENCES antar-pasal, relasi ini
    menghubungkan dokumen secara utuh — dipakai audit temporal/status.
    `amended_by` = UU lain yang mengubah DOKUMEN ini (arah terbalik)."""
    amended_by = amended_by or []
    if not revokes and not amends and not amended_by:
        return 0
    from app.database.neo4j import get_neo4j_driver

    query = """
    MERGE (a:LegalDoc {name: $law_name})
    ON CREATE SET a.scope = 'GLOBAL'
    WITH a
    UNWIND $revokes AS t
    MERGE (b:LegalDoc {name: t})
    ON CREATE SET b.scope = 'GLOBAL'
    MERGE (a)-[:REVOKES]->(b)
    WITH a
    UNWIND $amends AS t
    MERGE (c:LegalDoc {name: t})
    ON CREATE SET c.scope = 'GLOBAL'
    MERGE (a)-[:AMENDS]->(c)
    WITH a
    UNWIND $amended_by AS t
    MERGE (d:LegalDoc {name: t})
    ON CREATE SET d.scope = 'GLOBAL'
    MERGE (d)-[:AMENDS]->(a)
    RETURN size($revokes) + size($amends) + size($amended_by) AS n
    """
    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j tidak tersedia: %s", exc)
        return 0
    try:
        with driver.session() as session:
            return session.run(
                query, law_name=law_name,
                revokes=revokes, amends=amends,
                amended_by=amended_by).single()["n"]
    except Exception as exc:
        logger.warning("Relasi UU %s gagal: %s", law_name, exc)
        return 0
    finally:
        driver.close()


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
