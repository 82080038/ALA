"""
Endpoint API inti — analyze, approval workflow, cases, audit, ALCD.

Isolasi tenant: semua query data operasional (cases, ai_audit_logs)
memfilter `institution_id` dari TenantContext DAN meng-set GUC
`app.tenant_id` agar RLS PostgreSQL juga menegakkan batas tenant.
Pengetahuan hukum (ChromaDB, Neo4j LegalArticle) tetap GLOBAL.
"""
import asyncio
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.config import settings
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
    mode: str = Field("full", pattern="^(full|legal)$")


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


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)


# ---------------------------------------------------------------------------
# Auth — login lokal (JWT HS256), tanpa layanan eksternal
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Verifikasi email+password → JWT Bearer (dipakai di Authorization)."""
    from app.auth import create_token, verify_password
    from app.models.tenant import User

    user = db.scalar(
        select(User).where(
            func.lower(User.email) == body.email.lower(),
            User.is_active.is_(True))
    )
    if not user or not verify_password(body.password, user.password_hash):
        # Pesan generik — tidak bocorkan email mana yang terdaftar
        raise HTTPException(401, "Email atau password salah.")
    token = create_token(
        user.id, user.institution_id, user.role, user.tier_level or "free")
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in_hours": settings.jwt_expiry_hours,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "role": user.role,
            "tier": user.tier_level,
            "institution_id": str(user.institution_id),
        },
    }


# Helpers
# ---------------------------------------------------------------------------

_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def _tenant_db(tenant: TenantContext, db: Session) -> Session:
    """Set GUC app.tenant_id agar RLS PostgreSQL aktif untuk sesi ini.

    Non-super-admin TANPA institution_id mendapat GUC nil-UUID — RLS
    menolak semua baris tenant (tidak ada kebocoran lintas-institusi).
    """
    if not tenant.is_super_admin:
        db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant.institution_id or _NIL_UUID)},
        )
    return db


def _tenant_filter(tenant: TenantContext) -> uuid.UUID:
    """institution_id efektif untuk filter query — nil-UUID jika anon."""
    return tenant.institution_id or uuid.UUID(_NIL_UUID)


def _require_auth(tenant: TenantContext) -> None:
    if not tenant.is_authenticated:
        raise HTTPException(401, "Autentikasi diperlukan.")


# Referensi kuat ke task background — asyncio.create_task hanya menyimpan
# weak-ref; tanpa ini job bisa dibatalkan GC di tengah jalan.
_BG_TASKS: "set[asyncio.Task]" = set()


def _spawn(coro) -> asyncio.Task:
    """Jalankan coroutine background dengan referensi kuat + log exception."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BG_TASKS.discard(t)
        if not t.cancelled() and t.exception():
            logger.error("Background task gagal: %s", t.exception())

    task.add_done_callback(_done)
    return task


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


@router.get("/institutions")
async def list_institutions(db: Session = Depends(get_db)):
    """Daftar institusi aktif (id + nama) untuk pemilih identitas.

    Fase header-auth: dipakai frontend agar pengguna memilih tenant yang
    benar-benar ada, bukan mengetik UUID bebas.
    """
    from app.models.tenant import Institution

    try:
        rows = db.scalars(
            select(Institution)
            .where(Institution.is_active.is_(True))
            .order_by(Institution.name)
        ).all()
        return {"institutions": [
            {"id": str(i.id), "name": i.name, "type": i.type}
            for i in rows]}
    except Exception as exc:
        logger.warning("List institutions gagal: %s", exc)
        return {"institutions": []}


@router.post("/analyze-trend", status_code=202)
async def analyze_trend(
    body: AnalyzeRequest,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Antrekan pipeline 4-agen sebagai job background.

    Mengembalikan request_id SEKETIKA — progres tiap agen dapat dipantau
    real-time via GET /analyze-trend/{request_id} atau GET /activity.
    Konteks token dibatasi `context_token_budget` dari tier pengguna.
    """
    _require_auth(tenant)
    if not tenant.institution_id:
        # Baris audit harus milik tenant — insert institution_id NULL
        # ditolak policy RLS (chain-of-custody akan hilang diam-diam).
        raise HTTPException(400, "X-Institution-ID diperlukan.")
    from app import activity
    from app.models.operational import Case
    from app.models.tenant import Institution

    # Validasi case_id — UUID rusak akan membunuh insert audit log
    # secara diam-diam di worker background (audit hilang tanpa jejak),
    # dan case milik tenant lain tidak boleh tertaut ke audit institusi
    # ini (RLS menyaring db.get → 404 indistinguishable dari tidak ada).
    case_uuid = None
    if body.case_id:
        try:
            case_uuid = uuid.UUID(body.case_id)
        except ValueError:
            raise HTTPException(400, "case_id bukan UUID valid.")
        _tenant_db(tenant, db)
        if not db.get(Case, case_uuid):
            raise HTTPException(
                404, "Case tidak ditemukan untuk institusi ini.")

    # Validasi institution eksis — FK ai_audit_logs.institution_id akan
    # menolak baris untuk tenant fiktif (audit hilang diam-diam).
    if not db.scalar(
        select(Institution.id).where(
            Institution.id == tenant.institution_id)
    ):
        raise HTTPException(400, "Institution ID tidak terdaftar.")

    job = activity.create_job(
        query=body.query,
        institution_id=tenant.institution_id,
        user_id=tenant.user_id,
        kind="analyze",
        mode=body.mode,
    )
    _spawn(_run_analysis_job(
        job["request_id"], body, tenant, case_uuid))
    return {"request_id": job["request_id"], "status": "queued"}


async def _run_analysis_job(
    job_id: str, body: AnalyzeRequest, tenant: TenantContext,
    case_uuid: uuid.UUID | None,
) -> None:
    """Worker background: pipeline → audit log → registry job."""
    from app import activity
    from app.agents.legal_orchestrator import run_pipeline
    from app.database.postgres import SessionLocal
    from app.models.operational import AiAuditLog

    try:
        state = await run_in_threadpool(
            run_pipeline,
            query=body.query,
            institution_id=str(tenant.institution_id or ""),
            tier_level=tenant.tier_level,
            context_token_budget=tenant.context_token_budget,
            on_node=lambda node: activity.set_stage(job_id, node),
            mode=body.mode,
        )
    except Exception as exc:
        logger.exception("Pipeline gagal (job %s)", job_id)
        activity.fail_job(job_id, str(exc))
        return

    result = {
        "request_id": job_id,
        "knowledge_ready": state.get("knowledge_ready"),
        "knowledge_score": state.get("knowledge_score"),
        "legal_summary": state.get("legal_summary", ""),
        "legal_articles": state.get("legal_articles", []),
        "cross_references": state.get("cross_references", []),
        "crime_summary": state.get("crime_summary", ""),
        "crime_data": state.get("crime_data", []),
        "synthesis": state.get("synthesis", {}),
        "generated_output": state.get("generated_output", {}),
        "errors": state.get("errors", []),
        # Approval hanya relevan jika memang ada kode yang dihasilkan —
        # mode "legal" tidak menghasilkan kode sama sekali.
        "requires_approval": bool(
            (state.get("generated_output") or {}).get("code")),
    }

    # Immutable audit log — session baru (session request sudah ditutup).
    try:
        db = SessionLocal()
        try:
            _tenant_db(tenant, db)
            append_audit(
                db,
                institution_id=tenant.institution_id,
                request_id=uuid.UUID(job_id),
                action="analyze",
                user_id=tenant.user_id,
                case_id=case_uuid,
                query_input=body.query,
                action_taken="pipeline_4_agents",
                crime_trend={"summary": state.get("crime_summary", ""),
                             "sources": state.get("crime_data", [])[:10]},
                legal_articles=[{
                    "law": a.get("law_name"),
                    "article": a.get("article_number"),
                    "score": a.get("relevance_score"),
                } for a in (state.get("legal_articles") or [])[:15]],
                code_generated=(
                    state.get("generated_output") or {}).get("code"),
                metadata_={
                    "knowledge_score": state.get("knowledge_score"),
                    "token_budget": tenant.context_token_budget,
                    "audit_trail": state.get("audit_trail", []),
                },
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Audit log gagal disimpan: %s", exc)

    activity.complete_job(job_id, result)


@router.get("/analyze-trend/{request_id}")
async def analyze_status(
    request_id: str,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Status job pipeline — tahap agen aktif + hasil jika selesai."""
    _require_auth(tenant)
    from app import activity

    # Scope tenant: job milik institusi lain → 404 (tidak bisa di-probe).
    scope = None if tenant.is_super_admin else str(_tenant_filter(tenant))
    job = activity.get_job(request_id, scope)
    if job:
        return job

    # Job registry volatil (hilang saat restart API) — pulihkan status
    # dari audit log permanen agar hasil tetap bisa diambil pasca-restart.
    try:
        req_uuid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(404, "Job tidak ditemukan.")
    from app.models.operational import AiAuditLog
    _tenant_db(tenant, db)
    row = db.scalar(
        select(AiAuditLog).where(
            AiAuditLog.request_id == req_uuid,
            AiAuditLog.action == "analyze",
        ).limit(1)
    )
    if not row:
        raise HTTPException(404, "Job tidak ditemukan.")
    meta = row.metadata_ or {}
    return {
        "request_id": request_id,
        "kind": "analyze",
        "status": "done",
        "recovered_from_audit": True,
        "stage": None,
        "stages_completed": ["alcd", "legal_foundation",
                             "internet_crawler", "synthesis_developer"],
        "finished_at": row.timestamp.isoformat() if row.timestamp else None,
        "result": {
            "request_id": request_id,
            "legal_articles": row.legal_articles or [],
            "crime_trend": row.crime_trend or {},
            "code_generated": bool(row.code_generated),
            "requires_approval": bool(row.code_generated),
            "metadata": meta,
        },
    }


@router.get("/activity")
async def list_activity(tenant: TenantContext = Depends(get_tenant)):
    """Aktivitas pipeline real-time milik tenant ini (running dulu)."""
    _require_auth(tenant)
    from app import activity

    institution = (
        None if tenant.is_super_admin else str(_tenant_filter(tenant))
    )
    return {"jobs": activity.list_jobs(institution)}


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

    # Idempotensi keputusan: satu request hanya boleh diputuskan sekali.
    # Tanpa ini, approve ganda mengeksekusi kode berkali-kali, dan
    # reject→approve tetap mengeksekusi — keduanya melanggar jaminan
    # human-in-the-loop sekali-jalan.
    decided = db.scalar(
        select(AiAuditLog.action).where(
            AiAuditLog.request_id == req_uuid,
            AiAuditLog.action.in_(["execute", "reject"]),
        ).limit(1)
    )
    if decided:
        raise HTTPException(
            409, f"Request sudah diputuskan ({decided}).")

    if not body.approved:
        append_audit(
            db,
            institution_id=tenant.institution_id,
            request_id=req_uuid,
            action="reject",
            user_id=tenant.user_id,
            action_taken="workflow_ditolak_pengguna",
        )
        db.commit()
        return {"request_id": body.request_id, "status": "rejected"}

    exec_result = await run_in_threadpool(
        run_in_sandbox, audit_row.code_generated)
    append_audit(
        db,
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
    )
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
    if not tenant.is_super_admin:
        query = query.where(Case.institution_id == _tenant_filter(tenant))
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


@router.get("/cases/{case_id}")
async def case_detail(
    case_id: str,
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Detail kasus + riwayat analisis yang tertaut (dari audit log)."""
    _require_auth(tenant)
    from app.models.operational import AiAuditLog, Case
    from app.models.tenant import User

    try:
        c_uuid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(404, "ID bukan UUID yang valid.")

    _tenant_db(tenant, db)
    case = db.get(Case, c_uuid)  # RLS: kasus tenant lain → None (404)
    if not case:
        raise HTTPException(404, "Kasus tidak ditemukan.")

    assignee = db.get(User, case.assigned_to) if case.assigned_to else None
    history = db.scalars(
        select(AiAuditLog)
        .where(AiAuditLog.case_id == c_uuid,
               AiAuditLog.action == "analyze")
        .order_by(AiAuditLog.timestamp.desc())
        .limit(50)
    ).all()
    return {
        "id": str(case.id),
        "title": case.title,
        "description": case.description,
        "status": case.status,
        "case_number": case.case_number,
        "crime_type": case.crime_type,
        "priority": case.priority,
        "assigned_to": {
            "name": assignee.name,
            "badge_number": assignee.badge_number,
            "role": assignee.role,
        } if assignee else None,
        "analysis_history": [{
            "audit_id": str(a.id),
            "request_id": str(a.request_id),
            "query": (a.query_input or "")[:200],
            "timestamp": a.timestamp.isoformat() if a.timestamp else None,
        } for a in history],
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


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
    if not tenant.is_super_admin:
        query = query.where(
            AiAuditLog.institution_id == _tenant_filter(tenant))
    rows = db.scalars(query).all()
    return {"logs": [{
        "id": str(l.id), "timestamp": l.timestamp.isoformat()
        if l.timestamp else None,
        "action": l.action, "request_id": str(l.request_id),
        "query_input": (l.query_input or "")[:200],
        "evidence_sha256_before": l.evidence_sha256_before,
        "evidence_sha256_after": l.evidence_sha256_after,
        "entry_hash": l.entry_hash,
    } for l in rows]}


@router.get("/audit-logs/verify")
async def verify_audit(
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    """Verifikasi integritas hash-chain audit log (super_admin)."""
    _require_auth(tenant)
    if not tenant.is_super_admin:
        raise HTTPException(403, "Hanya super_admin.")
    from app.audit import verify_audit_chain

    return verify_audit_chain(db)


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
    import re

    # Buang komentar // ... lalu cek keyword tulis dengan word-boundary —
    # pemeriksaan berbasis spasi bisa dibypass via newline/tab.
    stripped = re.sub(r"//[^\n]*", " ", body.cypher)
    forbidden = ("CREATE", "MERGE", "DELETE", "SET", "DROP", "CALL",
                 "LOAD", "REMOVE", "DETACH")
    if re.search(rf"\b({'|'.join(forbidden)})\b", stripped.upper()):
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

    try:
        readiness = check_readiness(db)
        total_chunks = db.scalar(
            select(func.coalesce(func.sum(KnowledgeRegistry.chunk_count), 0)))
        unresolved_gaps = db.scalar(
            select(func.count(SelfEvalLog.id)).where(
                SelfEvalLog.resolved.is_(False))) or 0
    except Exception as exc:
        logger.warning("ALCD status gagal: %s", exc)
        return {"knowledge_ready": False, "knowledge_score": 0.0,
                "ontology_nodes": 0, "laws_ingested": 0,
                "total_chunks": 0, "unresolved_gaps": 0}
    return {
        **readiness,
        "total_chunks": int(total_chunks or 0),
        "unresolved_gaps": unresolved_gaps,
    }


@router.post("/alcd/trigger", status_code=202)
async def alcd_trigger(tenant: TenantContext = Depends(get_tenant)):
    """Antrekan bootstrap ALCD sebagai job background (proses berat,
    bisa bermenit-menit). Pantau via GET /activity atau
    /analyze-trend/{request_id}."""
    _require_auth(tenant)
    # Bootstrap mahal (jam, ratusan dokumen) — hanya admin yang boleh
    # memicunya; role operasional cukup mengonsumsi pengetahuan.
    if tenant.user_role not in ("super_admin", "admin_instansi"):
        raise HTTPException(
            403, "Trigger ALCD hanya untuk super_admin/admin_instansi.")
    from app import activity

    if activity.has_running("alcd_bootstrap"):
        raise HTTPException(409, "Bootstrap ALCD sedang berjalan.")
    job = activity.create_job(
        query="ALCD bootstrap",
        institution_id=tenant.institution_id,
        user_id=tenant.user_id,
        kind="alcd_bootstrap",
    )
    _spawn(_run_alcd_job(job["request_id"]))
    return {"request_id": job["request_id"], "status": "queued"}


async def _run_alcd_job(job_id: str) -> None:
    """Worker bootstrap ALCD — session DB baru (bukan milik request)."""
    from app import activity
    from app.agents.curriculum_designer import run_bootstrap
    from app.database.postgres import SessionLocal

    db = SessionLocal()
    try:
        activity.set_stage(job_id, "alcd")
        result = await run_in_threadpool(run_bootstrap, db)
        activity.complete_job(
            job_id,
            result if isinstance(result, dict) else {"detail": str(result)},
        )
    except Exception as exc:
        logger.exception("ALCD bootstrap gagal (job %s)", job_id)
        activity.fail_job(job_id, str(exc))
    finally:
        db.close()


# Cache pasal-per-UU dari ChromaDB — koleksi >100K chunk, fetch penuh
# tiap ~5s per klien terlalu mahal. TTL pendek agar dokumen baru tetap
# muncul cepat; paginasi wajib — coll.get(limit=N) saja diam-diam
# memotong pasal untuk dokumen di luar N pertama.
_ARTS_CACHE_TTL = 120  # detik
_ARTS_PAGE = 20000
_arts_cache: dict = {"ts": 0.0, "data": {}}


def _chroma_articles_by_law() -> dict[str, list[str]]:
    import time

    global _arts_cache
    now = time.monotonic()
    if now - _arts_cache["ts"] < _ARTS_CACHE_TTL and _arts_cache["data"]:
        return _arts_cache["data"]

    arts_by_law: dict[str, list[str]] = {}
    try:
        from app.database.chroma import (
            get_chroma_client,
            get_laws_collection,
        )

        coll = get_laws_collection(get_chroma_client())
        offset = 0
        while True:
            got = coll.get(
                include=["metadatas"], limit=_ARTS_PAGE, offset=offset)
            metas = got.get("metadatas") or []
            for m in metas:
                ln = m.get("law_name") or ""
                an = m.get("article_number") or ""
                if ln and an:
                    lst = arts_by_law.setdefault(ln, [])
                    if an not in lst:
                        lst.append(an)
            if len(metas) < _ARTS_PAGE:
                break
            offset += _ARTS_PAGE
        _arts_cache = {"ts": now, "data": arts_by_law}
    except Exception as exc:
        logger.warning("alcd/ontology: baca Chroma gagal: %s", exc)
    return arts_by_law


@router.get("/alcd/ontology")
async def alcd_ontology(db: Session = Depends(get_db)):
    """Pohon ontologi pengetahuan yang dirumuskan ALCD — GLOBAL.

    Tiap node membawa `laws` (UU teregistrasi yang cocok node) dan
    `articles` (pasal nyata yang tertanam di ChromaDB) — inilah "isi
    otak" yang divisualisasikan frontend."""
    import re as _re

    from app.agents.curriculum_designer import (
        _EXPECTED_LAW_IDS,
        _subject_match,
    )
    from app.models.operational import KnowledgeRegistry, OntologyNode

    rows = db.scalars(
        select(OntologyNode).order_by(
            OntologyNode.priority, OntologyNode.category)
    ).all()

    laws = db.scalars(
        select(KnowledgeRegistry).where(
            KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
    ).all()

    # Pasal nyata per UU — dari metadata chunk di ChromaDB.
    arts_by_law = _chroma_articles_by_law()

    # Petakan UU → node: identitas kanonik (nomor+tahun) lebih dulu,
    # lalu kecocokan subjek (klausa TENTANG) dengan topik node.
    node_laws: dict[int, list] = {i: [] for i in range(len(rows))}
    unassigned = []
    for r in laws:
        meta = r.metadata_ or {}
        num = (r.law_number or "").lstrip("0")
        year = str(meta.get("law_year") or "")
        if not year:
            m2 = _re.search(r"Tahun\s+(\d{4})", r.law_name or "")
            year = m2.group(1) if m2 else ""
        probe = {"law_subject": meta.get("law_subject") or "",
                 "law_name": r.law_name or ""}
        placed = False
        # Doktrin & yurisprudensi hanya boleh menempati node hint-nya —
        # subjek konsep ("Sejarah Hukum Pidana") akan salah menempel ke
        # node UU lewat _subject_match bila dibiarkan.
        if r.law_category in ("doktrin", "yurisprudensi"):
            from app.agents.curriculum_designer import _NODE_CATEGORY_HINT
            for i, n in enumerate(rows):
                k = (n.subcategory or n.category or "").strip().lower()
                if _NODE_CATEGORY_HINT.get(k) == r.law_category:
                    node_laws[i].append(r)
                    placed = True
                    break
            if not placed:
                unassigned.append(r.law_name)
            continue
        for i, n in enumerate(rows):
            key = (n.subcategory or n.category or "").strip().lower()
            exp = _EXPECTED_LAW_IDS.get(key)
            if exp is not None and (num, year) in exp:
                node_laws[i].append(r)
                placed = True
                break
        if placed:
            continue
        for i, n in enumerate(rows):
            if _subject_match(n.subcategory or n.category or "",
                              "", probe):
                node_laws[i].append(r)
                placed = True
                break
        if not placed:
            unassigned.append(r.law_name)

    nodes_out = []
    for i, n in enumerate(rows):
        lws = node_laws[i]
        articles: list[str] = []
        for r in lws:
            for a in arts_by_law.get(r.law_name, []):
                if a not in articles:
                    articles.append(a)
        law_rows = []
        for r in lws:
            # Registry lama bisa kehilangan law_number/law_year — ambil
            # dari law_name kanonik ("UU Nomor N Tahun Y …").
            num = r.law_number
            year = (r.metadata_ or {}).get("law_year")
            m2 = _re.search(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})",
                            r.law_name or "")
            if m2:
                num = num or m2.group(1)
                year = year or m2.group(2)
            law_rows.append({
                "law_name": r.law_name,
                "law_number": num,
                "law_year": year,
                "chunk_count": r.chunk_count,
                "article_count": r.article_count,
            })
        nodes_out.append({
            "id": str(n.id), "category": n.category,
            "subcategory": n.subcategory, "priority": n.priority,
            "status": n.status, "knowledge_score": n.knowledge_score,
            "laws_ingested": n.laws_ingested,
            "laws": law_rows,
            "articles": articles[:48],
        })
    # Relasi rujukan antar-pasal nyata (Neo4j CROSS_REFERENCES) — inilah
    # "alasan" sinaps tersambung pada visualisasi otak. Ujung relasi
    # di-resolve ke INDEX node ontologi ("undang-undang ini" → wilayah
    # sumber; "UU ITE." → node UU ITE via kata khas topik).
    from app.agents.curriculum_designer import (
        _CANONICAL_LAW_NAMES,
        _topic_keywords,
    )

    # law_name registry → index wilayah (sumber relasi = dokumen ingest).
    # Kunci dinormalisasi karena _region_of melowercase ref sebelum
    # lookup — nama registry ber-huruf besar (…Pemberantasan TPPU)
    # tanpa ini tak pernah cocok identitas.
    law_region = {
        (r.law_name or "").strip().lower(): i
        for i, lws in node_laws.items() for r in lws}
    topic_words = [
        _topic_keywords(
            _CANONICAL_LAW_NAMES.get(
                (n.subcategory or n.category or "").strip().lower(),
                n.subcategory or n.category or ""))
        for n in rows
    ]

    def _region_of(ref: str, src_region: int | None) -> int | None:
        ref = (ref or "").strip().rstrip(".").lower()
        if not ref:
            return None
        if "undang-undang ini" in ref or "uu ini" in ref:
            return src_region
        if ref in law_region:
            return law_region[ref]
        for i, nw in enumerate(topic_words):
            topic = (rows[i].subcategory or rows[i].category or "").lower()
            if topic and topic in ref:
                return i
            if nw and sum(1 for w in nw if w in ref) >= max(
                    1, math.ceil(len(nw) * 0.6)):
                return i
        return None

    links = []
    try:
        from app.database.neo4j import get_neo4j_driver

        driver = get_neo4j_driver()
        with driver.session() as s:
            # Kuota per tipe relasi — LIMIT tunggal arbitrer akan meneng-
            # gelamkan tipe minoritas (CITES putusan kalah oleh ribuan
            # CROSS_REFERENCES antar-pasal UU).
            for rec in s.run(
                # Maks 3 edge per pasangan (UU sumber → UU target) agar
                # sampel mewakili SEMUA UU yang terhubung — LIMIT
                # arbitrer pada edge mentah bias ke UU paling sering
                # disitasi (KUHP) dan menyembunyikan wilayah minoritas.
                "MATCH (a:LegalArticle)-[r:CROSS_REFERENCES]->"
                "(b:LegalArticle) "
                "WITH a.law_name AS fl, b.law_name AS tl, "
                "collect({fa: a.article_number, "
                "ta: b.article_number})[..3] AS items "
                "UNWIND items AS it "
                "RETURN fl, it.fa AS fa, tl, it.ta AS ta, "
                "'CROSS_REFERENCES' AS rel LIMIT 250 "
                "UNION "
                "MATCH (a:LegalArticle)-[r:CITES]->(b:LegalArticle) "
                "WITH a.law_name AS fl, b.law_name AS tl, "
                "collect({fa: a.article_number, "
                "ta: b.article_number})[..3] AS items "
                "UNWIND items AS it "
                "RETURN fl, it.fa AS fa, tl, it.ta AS ta, "
                "'CITES' AS rel LIMIT 250"
            ):
                fr = _region_of(rec["fl"], None)
                tr = _region_of(rec["tl"], fr)
                if fr is not None and tr is not None:
                    links.append({"fr": fr, "fa": rec["fa"],
                                  "tr": tr, "ta": rec["ta"],
                                  "rel": rec["rel"]})
        driver.close()
    except Exception as exc:
        logger.warning("alcd/ontology: baca Neo4j gagal: %s", exc)

    return {"nodes": nodes_out, "unassigned_laws": unassigned,
            "links": links[:200]}


@router.get("/alcd/progress")
async def alcd_progress(db: Session = Depends(get_db)):
    """Progres live bootstrap ALCD — wilayah & tahap yang SEDANG
    dikerjakan (untuk kamera otak dan neural.log), plus feed pengetahuan:

    - `recent`: dokumen terakhir yang BERHASIL ditanam (registry terbaru)
    - `queue`: node ontologi berikutnya dalam antrean (pending/gap) —
      "rencana belajar" yang masih hidup

    GLOBAL, publik."""
    from app.agents.curriculum_designer import current_progress
    from app.models.operational import KnowledgeRegistry, OntologyNode
    from sqlalchemy import desc

    prog = current_progress()
    recent = [
        {
            "name": r.law_name,
            "articles": r.article_count,
            "chunks": r.chunk_count,
            "cat": r.law_category,
            "ts": r.created_at.isoformat() if r.created_at else None,
        }
        for r in db.scalars(
            select(KnowledgeRegistry)
            .where(KnowledgeRegistry.ingestion_status.in_(
                ["completed", "verified"]))
            .order_by(desc(KnowledgeRegistry.created_at))
            .limit(5)
        ).all()
    ]
    queue = [
        {"topic": n.subcategory or n.category, "status": n.status,
         "score": round(n.knowledge_score or 0.0, 2)}
        for n in db.scalars(
            select(OntologyNode)
            .where(OntologyNode.status.in_(
                ["pending", "in_progress", "gap_detected"]))
            .order_by(OntologyNode.priority)
            .limit(6)
        ).all()
    ]
    return {**prog, "recent": recent, "queue": queue}


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
