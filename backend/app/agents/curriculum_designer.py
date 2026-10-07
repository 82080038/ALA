"""
Autonomous Legal Curriculum Designer (ALCD) — Agent 0.

Membangun basis pengetahuan hukum dari NOL DATA sebelum query pengguna
diproses. Pipeline: ontologi → akuisisi (discover → download → parse →
verify) → ingest (chunk → embed → ChromaDB GLOBAL) → graph (Neo4j GLOBAL)
→ evaluasi diri → registrasi.

Seluruh output pengetahuan berada di namespace GLOBAL — dibagikan ke
SEMUA institusi (tanpa institution_id).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.agents.alcd.document_parser import DocumentParser
from app.agents.alcd.ontology_generator import CORE_OBJECTIVE, generate_ontology
from app.agents.alcd.source_discoverer import SourceDiscoverer
from app.config import get_llm_reasoning, settings

logger = logging.getLogger("ala.agents.alcd")

_MAX_SOURCES_PER_NODE = 3      # batas dokumen per node ontologi
_MAX_BOOTSTRAP_NODES = 10      # batas node per siklus bootstrap


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

def check_readiness(db) -> dict:
    """Hitung skor kesiapan pengetahuan dari ontology_nodes + registry."""
    from app.models.operational import KnowledgeRegistry, OntologyNode

    total_nodes = db.scalar(select(func.count(OntologyNode.id))) or 0
    laws_done = db.scalar(
        select(func.count(KnowledgeRegistry.id)).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
    ) or 0
    avg_score = db.scalar(select(func.avg(OntologyNode.knowledge_score))) or 0.0

    if total_nodes == 0:
        score = 0.0
    else:
        score = min(1.0, (avg_score * 0.6) + (min(laws_done, 8) / 8 * 0.4))

    return {
        "knowledge_ready": score >= settings.alcd_min_readiness_score,
        "knowledge_score": round(score, 3),
        "ontology_nodes": total_nodes,
        "laws_ingested": laws_done,
    }


# ---------------------------------------------------------------------------
# Fase akuisisi per node
# ---------------------------------------------------------------------------

def _acquire_node(node: dict, discoverer: SourceDiscoverer,
                  parser: DocumentParser, db) -> dict:
    """Temukan → unduh → parse → ingest → graph untuk satu node ontologi."""
    from app.agents.alcd.autonomous_ingestor import (
        ingest_parsed_document,
        register_knowledge,
    )
    from app.agents.alcd.graph_builder import build_graph_for_document

    topic = node.get("subcategory") or node.get("category", "")
    law_category = (
        "formil" if "formil" in (node.get("category") or "").lower()
        else "yurisprudensi" if "yurisprudensi" in (node.get("category") or "").lower()
        else "regulasi" if "regulasi" in (node.get("category") or "").lower()
        else "materiil"
    )
    result = {"topic": topic, "parsed": [], "chunks": 0, "articles": 0}

    sources = discoverer.discover(node)
    parsed_docs: list[dict] = []
    for src in sources[:_MAX_SOURCES_PER_NODE * 2]:  # ambil ekstra utk verifikasi
        parsed = parser.parse(src["url"])
        if parsed:
            parsed["trusted"] = src.get("trusted", False)
            parsed_docs.append(parsed)
        if len(parsed_docs) >= _MAX_SOURCES_PER_NODE:
            break

    if not parsed_docs:
        return result

    # Verifikasi: ≥2 sumber berhasil diparse untuk topik yang sama
    verified = len(parsed_docs) >= 2

    for parsed in parsed_docs[:_MAX_SOURCES_PER_NODE]:
        try:
            res = ingest_parsed_document(parsed, law_category, verified)
            register_knowledge(db, parsed, res, law_category, verified)
            build_graph_for_document(res["law_name"], parsed["articles"])
            result["chunks"] += res["chunks"]
            result["articles"] += res["articles"]
            result["parsed"].append(res["law_name"])
        except Exception as exc:
            logger.warning("Ingest gagal %s: %s", parsed["source_url"], exc)
    return result


# ---------------------------------------------------------------------------
# Bootstrap penuh
# ---------------------------------------------------------------------------

def run_bootstrap(db, progress_cb=None) -> dict:
    """Jalankan pipeline ALCD lengkap: ontologi → akuisisi → evaluasi diri.

    Args:
        db: SQLAlchemy session.
        progress_cb: opsional callable(stage: str, detail: dict).

    Returns:
        {"knowledge_score", "coverage": {topic: {...}}, "nodes": int}
    """
    from app.agents.evaluator import evaluate_node
    from app.models.operational import OntologyNode

    def _progress(stage: str, detail: dict) -> None:
        logger.info("[ALCD] %s — %s", stage, detail)
        if progress_cb:
            progress_cb(stage, detail)

    llm = get_llm_reasoning()

    # ── Fase 1: Ontologi ────────────────────────────────────────────
    _progress("ontology", {"objective": CORE_OBJECTIVE})
    nodes = generate_ontology(llm)[:_MAX_BOOTSTRAP_NODES]

    # Simpan node ontologi (skip duplikat category+subcategory)
    from sqlalchemy import select as _select
    for n in nodes:
        exists = db.scalar(
            _select(OntologyNode.id).where(
                OntologyNode.category == n["category"],
                OntologyNode.subcategory == n.get("subcategory"),
            )
        )
        if not exists:
            db.add(OntologyNode(
                category=n["category"],
                subcategory=n.get("subcategory"),
                description=n.get("description", ""),
                priority=int(n.get("priority", 3)),
                status="pending",
            ))
    db.commit()

    db_nodes = db.scalars(
        _select(OntologyNode).order_by(OntologyNode.priority)
    ).all()

    # ── Fase 2: Akuisisi ────────────────────────────────────────────
    discoverer = SourceDiscoverer()
    parser = DocumentParser()
    coverage: dict = {}

    for node in db_nodes:
        topic = node.subcategory or node.category
        _progress("acquire", {"topic": topic})
        try:
            res = _acquire_node(
                {"id": node.id, "category": node.category,
                 "subcategory": node.subcategory},
                discoverer, parser, db,
            )
        except Exception as exc:
            logger.warning("Akuisisi %s gagal: %s", topic, exc)
            res = {"chunks": 0, "articles": 0, "parsed": []}

        node.laws_ingested = len(res["parsed"])
        node.status = "in_progress" if res["parsed"] else "gap_detected"
        db.commit()
        coverage[topic] = {
            "laws_ingested": len(res["parsed"]),
            "chunks": res["chunks"],
            "score": 0.0,
        }

    # ── Fase 3: Evaluasi diri ───────────────────────────────────────
    from app.database.chroma import get_chroma_client, get_laws_collection

    def _rag_answer(question: str) -> str:
        collection = get_laws_collection(get_chroma_client())
        hits = collection.query(query_texts=[question], n_results=5)
        ctx = "\n".join(hits.get("documents", [[]])[0])
        resp = llm.invoke(
            f"Berdasarkan konteks hukum berikut, jawab pertanyaan.\n\n"
            f"Konteks:\n{ctx}\n\nPertanyaan: {question}\nJawaban:"
        )
        return resp.content if hasattr(resp, "content") else str(resp)

    for node in db_nodes:
        topic = node.subcategory or node.category
        _progress("self_eval", {"topic": topic})
        try:
            ev = evaluate_node(
                llm,
                {"id": node.id, "category": node.category,
                 "subcategory": node.subcategory},
                _rag_answer, db,
            )
            node.knowledge_score = ev["score"]
            node.status = (
                "completed" if ev["score"] >= settings.alcd_self_eval_threshold
                else "gap_detected"
            )
            db.commit()
            coverage.setdefault(topic, {})["score"] = ev["score"]
        except Exception as exc:
            logger.warning("Self-eval %s gagal: %s", topic, exc)

    readiness = check_readiness(db)
    _progress("done", readiness)
    return {
        "knowledge_score": readiness["knowledge_score"],
        "knowledge_ready": readiness["knowledge_ready"],
        "coverage": coverage,
        "nodes": len(db_nodes),
    }


# ---------------------------------------------------------------------------
# LangGraph node — Agent 0
# ---------------------------------------------------------------------------

def alcd_agent(state) -> dict:
    """Node LangGraph: cek kesiapan; bootstrap jika belum siap."""
    from app.database.postgres import SessionLocal

    audit = {
        "agent": "alcd",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    updates: dict = {"audit_trail": [audit]}

    if not settings.alcd_enabled:
        audit.update(status="skipped", note="ALCD_ENABLED=false")
        updates["knowledge_ready"] = True
        return updates

    try:
        with SessionLocal() as db:
            readiness = check_readiness(db)
            if readiness["knowledge_ready"]:
                audit.update(
                    status="success",
                    note="Knowledge base siap; bootstrap dilewati",
                )
            else:
                result = run_bootstrap(db)
                readiness = check_readiness(db)
                audit.update(
                    status="success",
                    note=f"Bootstrap: {result['nodes']} node diproses",
                )
    except Exception as exc:
        logger.exception("ALCD agent error")
        audit.update(status="error", error=str(exc))
        updates["errors"] = [f"ALCD Agent error: {exc}"]
        updates["knowledge_ready"] = False
        updates["knowledge_score"] = 0.0
        return updates

    updates["knowledge_ready"] = readiness["knowledge_ready"]
    updates["knowledge_score"] = readiness["knowledge_score"]
    updates["ontology_coverage"] = {
        "ontology_nodes": readiness["ontology_nodes"],
        "laws_ingested": readiness["laws_ingested"],
    }
    return updates
