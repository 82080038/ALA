"""
Endpoint API inti — analyze, approval workflow, cases, audit, ALCD.

Isolasi tenant: semua query data operasional (cases, ai_audit_logs)
memfilter `institution_id` dari TenantContext DAN meng-set GUC
`app.tenant_id` agar RLS PostgreSQL juga menegakkan batas tenant.
Pengetahuan hukum (ChromaDB, Neo4j LegalArticle) tetap GLOBAL.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.postgres import get_db
from app.middleware.tenant import TenantContext, get_tenant

logger = logging.getLogger("ala.api")

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=4000)
    case_id: Optional[str] = None


class ApproveRequest(BaseModel):
    request_id: str
    approved: bool
    approved_by: Optional[str] = None


class CaseCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    description: Optional[str] = None
    case_number: Optional[str] = None
    crime_type: Optional[str] = None
    priority: str = "medium"


class GraphQueryRequest(BaseModel):
    cypher: str = Field(..., min_length=3, max_length=2000)
    parameters: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tenant_db(tenant: TenantContext, db: Session) -> Session:
    """Set GUC app.tenant_id agar RLS PostgreSQL aktif untuk sesi ini."""
    if tenant.institution_id and not tenant.is_super_admin:
        db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant.institution_id)},
        )
    return db


def _require_auth(tenant: TenantContext) -> None:
    if not tenant.is_authenticated:
        raise HTTPException(401, "Autentikasi diperlukan.")


# ---------------------------------------------------------------------------
# Status & pipeline
# ---------------------------------------------------------------------------

@router.get("/status")
async def system_status(db: Session = Depends(get_db)):
    """Status sistem termasuk kesiapan pengetahuan ALCD (GLOBAL)."""
    from app.agents.curriculum_designer import check_readiness

    try:
        readiness = check_readiness(db)
    except Exception:
        readiness = {"knowledge_ready": False, "knowledge_score": 0.0,
                     "ontology_nodes": 0, "laws_ingested": 0}
    return {"api": "online", **readiness}


@router.post("/analyze-trend")
async def analyze_trend(
    body: AnalyzeRequest,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Jalankan pipeline 4-agen untuk satu query investigasi.

    Konteks token dibatasi `context_token_budget` dari tier pengguna
    (free=2048, L1=8192, L2=16384 — diklamp ceiling hardware).
    """
    _require_auth(tenant)
    from app.agents.legal_orchestrator import run_pipeline
    from app.models.operational import AiAuditLog

    request_id = uuid.uuid4()
    try:
        state = run_pipeline(
            query=body.query,
            institution_id=str(tenant.institution_id or ""),
            tier_level=tenant.tier_level,
            context_token_budget=tenant.context_token_budget,
        )
    except Exception as exc:
        logger.exception("Pipeline gagal")
        raise HTTPException(500, f"Pipeline error: {exc}")

    # Immutable audit log (append-only, tenant-scoped)
    try:
        _tenant_db(tenant, db)
        db.add(AiAuditLog(
            institution_id=tenant.institution_id,
            request_id=request_id,
            action="analyze",
            user_id=tenant.user_id,
            case_id=uuid.UUID(body.case_id) if body.case_id else None,
            query_input=body.query,
            action_taken="pipeline_4_agents",
            crime_trend={"summary": state.get("crime_summary", ""),
                         "sources": state.get("crime_data", [])[:10]},
            legal_articles=[{
                "law": a.get("law_name"),
                "article": a.get("article_number"),
                "score": a.get("relevance_score"),
            } for a in (state.get("legal_articles") or [])[:15]],
            code_generated=(state.get("generated_output") or {}).get("code"),
            metadata_={
                "knowledge_score": state.get("knowledge_score"),
                "token_budget": tenant.context_token_budget,
                "audit_trail": state.get("audit_trail", []),
            },
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Audit log gagal disimpan: %s", exc)

    return {
        "request_id": str(request_id),
        "knowledge_ready": state.get("knowledge_ready"),
        "knowledge_score": state.get("knowledge_score"),
        "legal_summary": state.get("legal_summary", ""),
        "legal_articles": state.get("legal_articles", []),
        "cross_references": state.get("legal_cross_references", []),
        "crime_summary": state.get("crime_summary", ""),
        "crime_data": state.get("crime_data", []),
        "synthesis": state.get("synthesis", {}),
        "generated_output": state.get("generated_output", {}),
        "errors": state.get("errors", []),
        "requires_approval": True,
    }


@router.post("/approve-workflow")
async def approve_workflow(
    body: ApproveRequest,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Persetujuan manusia → eksekusi kode AI di sandbox terkunci.

    Hanya boleh dieksekusi setelah approved=True eksplisit. Kode kembali
    dipindai guardrail (defense-in-depth) sebelum masuk sandbox.
    """
    _require_auth(tenant)
    from app.models.operational import AiAuditLog
    from app.sandbox.execution_env import run_in_sandbox

    try:
        req_uuid = uuid.UUID(body.request_id)
    except ValueError:
        raise HTTPException(400, "request_id bukan UUID valid.")

    _tenant_db(tenant, db)
    audit_row = db.scalar(
        select(AiAuditLog).where(AiAuditLog.request_id == req_uuid)
    )
    if not audit_row:
        raise HTTPException(404, "Request tidak ditemukan.")
    if not audit_row.code_generated:
        raise HTTPException(400, "Tidak ada kode untuk dieksekusi.")

    if not body.approved:
        db.add(AiAuditLog(
            institution_id=tenant.institution_id,
            request_id=req_uuid,
            action="reject",
            user_id=tenant.user_id,
            action_taken="workflow_ditolak_pengguna",
        ))
        db.commit()
        return {"request_id": body.request_id, "status": "rejected"}

    exec_result = run_in_sandbox(audit_row.code_generated)
    db.add(AiAuditLog(
        institution_id=tenant.institution_id,
        request_id=req_uuid,
        action="execute",
        user_id=tenant.user_id,
        action_taken="sandbox_execution",
        execution_result={
            "success": exec_result.success,
            "exit_code": exec_result.exit_code,
            "timed_out": exec_result.timed_out,
            "guardrail_violations": exec_result.guardrail_violations,
            "stdout_tail": exec_result.stdout[-2000:],
        },
        metadata_={"approved_by": body.approved_by},
    ))
    db.commit()

    return {
        "request_id": body.request_id,
        "status": "executed" if exec_result.success else "failed",
        "exit_code": exec_result.exit_code,
        "timed_out": exec_result.timed_out,
        "guardrail_violations": exec_result.guardrail_violations,
        "stdout": exec_result.stdout,
        "stderr": exec_result.stderr,
    }


# ---------------------------------------------------------------------------
# Cases (TENANT — RLS + filter institution_id)
# ---------------------------------------------------------------------------

@router.get("/cases")
async def list_cases(
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    _require_auth(tenant)
    from app.models.operational import Case

    _tenant_db(tenant, db)
    query = select(Case).order_by(Case.created_at.desc()).limit(100)
    if tenant.institution_id and not tenant.is_super_admin:
        query = query.where(Case.institution_id == tenant.institution_id)
    rows = db.scalars(query).all()
    return {"cases": [{
        "id": str(c.id), "title": c.title, "status": c.status,
        "case_number": c.case_number, "crime_type": c.crime_type,
        "priority": c.priority, "created_at": c.created_at.isoformat()
        if c.created_at else None,
    } for c in rows]}


@router.post("/cases", status_code=201)
async def create_case(
    body: CaseCreate,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    _require_auth(tenant)
    if not tenant.institution_id:
        raise HTTPException(400, "X-Institution-ID diperlukan.")
    from app.models.operational import Case

    _tenant_db(tenant, db)
    case = Case(
        institution_id=tenant.institution_id,
        title=body.title,
        description=body.description,
        case_number=body.case_number,
        crime_type=body.crime_type,
        priority=body.priority,
        assigned_to=tenant.user_id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return {"id": str(case.id), "status": case.status}


# ---------------------------------------------------------------------------
# Audit logs (TENANT — append-only)
# ---------------------------------------------------------------------------

@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 50,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    _require_auth(tenant)
    from app.models.operational import AiAuditLog

    _tenant_db(tenant, db)
    query = select(AiAuditLog).order_by(
        AiAuditLog.timestamp.desc()).limit(min(limit, 200))
    if tenant.institution_id and not tenant.is_super_admin:
        query = query.where(
            AiAuditLog.institution_id == tenant.institution_id)
    rows = db.scalars(query).all()
    return {"logs": [{
        "id": str(l.id), "timestamp": l.timestamp.isoformat()
        if l.timestamp else None,
        "action": l.action, "request_id": str(l.request_id),
        "query_input": (l.query_input or "")[:200],
        "evidence_sha256_before": l.evidence_sha256_before,
        "evidence_sha256_after": l.evidence_sha256_after,
    } for l in rows]}


# ---------------------------------------------------------------------------
# Neo4j graph query (GLOBAL — read-only Cypher)
# ---------------------------------------------------------------------------

@router.post("/graph/query")
async def graph_query(
    body: GraphQueryRequest,
    tenant: TenantContext = Depends(get_tenant),
):
    """Query Neo4j GLOBAL — hanya Cypher baca (MATCH/RETURN).

    Perintah tulis (CREATE/MERGE/DELETE/SET/DROP) ditolak keras.
    """
    _require_auth(tenant)
    forbidden = ("CREATE", "MERGE", "DELETE", "SET", "DROP", "CALL",
                 "LOAD", "REMOVE")
    upper = body.cypher.upper()
    if any(f" {kw} " in f" {upper} " or upper.startswith(kw)
           for kw in forbidden):
        raise HTTPException(400, "Hanya query baca yang diizinkan.")

    from app.database.neo4j import get_neo4j_driver

    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        raise HTTPException(503, f"Neo4j tidak tersedia: {exc}")
    try:
        with driver.session() as session:
            result = session.run(body.cypher, **body.parameters)
            return {"records": result.data()[:500]}
    except Exception as exc:
        raise HTTPException(400, f"Query gagal: {exc}")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# ALCD (GLOBAL)
# ---------------------------------------------------------------------------

@router.get("/alcd/status")
async def alcd_status(db: Session = Depends(get_db)):
    """Status basis pengetahuan ALCD — statistik GLOBAL."""
    from app.agents.curriculum_designer import check_readiness
    from app.models.operational import KnowledgeRegistry, SelfEvalLog

    readiness = check_readiness(db)
    total_chunks = db.scalar(
        select(func.coalesce(func.sum(KnowledgeRegistry.chunk_count), 0)))
    unresolved_gaps = db.scalar(
        select(func.count(SelfEvalLog.id)).where(
            SelfEvalLog.resolved.is_(False))) or 0
    return {
        **readiness,
        "total_chunks": int(total_chunks or 0),
        "unresolved_gaps": unresolved_gaps,
    }


@router.post("/alcd/trigger")
async def alcd_trigger(
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Picu bootstrap ALCD manual (butuh auth; proses berat)."""
    _require_auth(tenant)
    from app.agents.curriculum_designer import run_bootstrap

    try:
        return run_bootstrap(db)
    except Exception as exc:
        logger.exception("ALCD trigger gagal")
        raise HTTPException(500, f"ALCD error: {exc}")


@router.get("/alcd/ontology")
async def alcd_ontology(db: Session = Depends(get_db)):
    """Pohon ontologi pengetahuan yang dirumuskan ALCD — GLOBAL."""
    from app.models.operational import OntologyNode

    rows = db.scalars(
        select(OntologyNode).order_by(
            OntologyNode.priority, OntologyNode.category)
    ).all()
    return {"nodes": [{
        "id": str(n.id), "category": n.category,
        "subcategory": n.subcategory, "priority": n.priority,
        "status": n.status, "knowledge_score": n.knowledge_score,
        "laws_ingested": n.laws_ingested,
    } for n in rows]}


@router.get("/alcd/gaps")
async def alcd_gaps(db: Session = Depends(get_db)):
    """Gap pengetahuan yang diidentifikasi self-evaluation — GLOBAL."""
    from app.models.operational import SelfEvalLog

    rows = db.scalars(
        select(SelfEvalLog)
        .where(SelfEvalLog.resolved.is_(False))
        .order_by(SelfEvalLog.answer_quality)
        .limit(100)
    ).all()
    return {"gaps": [{
        "id": str(g.id), "question": g.question,
        "answer_quality": g.answer_quality,
        "gap_description": g.gap_description,
        "remediation_action": g.remediation_action,
    } for g in rows]}
