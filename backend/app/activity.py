"""Registrasi job pipeline in-memory — visibilitas aktivitas real-time.

Menyimpan status tiap request /analyze-trend (queued → running per-agen
→ done/failed) agar frontend bisa menampilkan apa yang sedang dikerjakan
aplikasi, bukan sekadar spinner. Sifatnya volatil (hilang saat restart);
jejak permanen tetap di ai_audit_logs.
"""
import threading
import time
import uuid
from typing import Optional

_lock = threading.Lock()
_jobs: "dict[str, dict]" = {}
_MAX_JOBS = 100

# Urutan node LangGraph — dipakai frontend untuk stepper progres.
PIPELINE_STAGES = [
    "alcd",
    "legal_foundation",
    "internet_crawler",
    "synthesis_developer",
]

STAGE_LABELS = {
    "alcd": "Agent 0 — ALCD: cek kesiapan basis pengetahuan",
    "legal_foundation": "Agent 1 — Legal Foundation: retrieval pasal (RAG)",
    "internet_crawler": "Agent 2 — Internet Crawler: tren kejahatan",
    "synthesis_developer": "Agent 3 — Synthesis & Developer: kode + ringkasan",
}


def create_job(
    query: str,
    institution_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    kind: str = "analyze",
    mode: str = "full",
) -> dict:
    """Daftarkan job baru, kembalikan dict-nya."""
    job = {
        "request_id": str(uuid.uuid4()),
        "kind": kind,                # analyze | alcd_bootstrap
        "mode": mode,                # full | legal
        "query": query[:200],
        "institution_id": str(institution_id) if institution_id else None,
        "user_id": str(user_id) if user_id else None,
        "status": "queued",          # queued | running | done | failed
        "stage": None,               # node aktif saat ini
        "stages_completed": [],      # node yang sudah selesai
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
        "result": None,
    }
    with _lock:
        _jobs[job["request_id"]] = job
        # Buang entri selesai tertua agar memori tidak membengkak.
        if len(_jobs) > _MAX_JOBS:
            done = [k for k, j in _jobs.items()
                    if j["status"] in ("done", "failed")]
            for k in sorted(done, key=lambda k: _jobs[k]["finished_at"] or 0)[
                : len(_jobs) - _MAX_JOBS
            ]:
                _jobs.pop(k, None)
    return job


def set_stage(request_id: str, node: str) -> None:
    """Dipanggil orchestrator tiap kali satu node LangGraph selesai."""
    with _lock:
        job = _jobs.get(request_id)
        if not job:
            return
        job["status"] = "running"
        if node not in job["stages_completed"]:
            job["stages_completed"].append(node)
        # Node berikutnya belum diketahui — stage menunjuk yang terakhir
        # diselesaikan; frontend menghitung node aktif dari urutan.
        job["stage"] = node


def has_running(kind: str) -> bool:
    """True jika ada job `kind` yang masih queued/running (anti double-run)."""
    with _lock:
        return any(
            j["kind"] == kind and j["status"] in ("queued", "running")
            for j in _jobs.values()
        )


def complete_job(request_id: str, result: dict) -> None:
    with _lock:
        job = _jobs.get(request_id)
        if job:
            job.update(status="done", stage=None,
                       finished_at=time.time(), result=result)


def fail_job(request_id: str, error: str) -> None:
    with _lock:
        job = _jobs.get(request_id)
        if job:
            job.update(status="failed", stage=None,
                       finished_at=time.time(), error=error)


def _public(job: dict, with_result: bool) -> dict:
    out = {k: v for k, v in job.items()
           if k != "result" and k != "institution_id" and k != "user_id"}
    out["stage_labels"] = STAGE_LABELS
    # Mode "legal" hanya menjalankan 2 node pertama.
    out["pipeline_stages"] = (
        PIPELINE_STAGES[:2] if job.get("mode") == "legal"
        else PIPELINE_STAGES
    )
    if with_result and job["status"] == "done":
        out["result"] = job["result"]
    return out


def get_job(
    request_id: str, institution_id: Optional[str] = None
) -> Optional[dict]:
    """Ambil job — None jika tak ada ATAU milik tenant lain (404, bukan 403,
    agar request_id tenant lain tidak bisa di-probe)."""
    with _lock:
        job = _jobs.get(request_id)
        if not job:
            return None
        # Samakan None ↔ nil-UUID (job tanpa tenant ↔ pemanggil tanpa
        # institution) agar tidak 404 untuk job milik sendiri.
        job_inst = job["institution_id"] or \
            "00000000-0000-0000-0000-000000000000"
        if institution_id is not None and job_inst != institution_id:
            return None
        return _public(job, with_result=True)


def list_jobs(institution_id: Optional[str], limit: int = 20) -> list:
    """Job milik satu tenant — running dulu, lalu terbaru."""
    with _lock:
        rows = [j for j in _jobs.values()
                if institution_id is None
                or j["institution_id"] == institution_id]
    rows.sort(key=lambda j: (
        j["status"] not in ("queued", "running"), -j["started_at"]))
    return [_public(j, with_result=False) for j in rows[:limit]]
