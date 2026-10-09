"""Unit test registry job pipeline (app/activity.py)."""
import uuid

from app import activity

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def setup_function():
    # Registry adalah singleton modul — bersihkan antar-test.
    activity._jobs.clear()


def test_job_lifecycle():
    job = activity.create_job("q", TENANT_A, None)
    rid = job["request_id"]
    assert activity.get_job(rid)["status"] == "queued"

    activity.set_stage(rid, "alcd")
    j = activity.get_job(rid)
    assert j["status"] == "running"
    assert j["stages_completed"] == ["alcd"]

    activity.complete_job(rid, {"x": 1})
    j = activity.get_job(rid)
    assert j["status"] == "done" and j["result"] == {"x": 1}
    assert j["finished_at"] is not None


def test_tenant_isolation():
    job = activity.create_job("q", TENANT_A, None)
    rid = job["request_id"]
    # Tenant lain tidak bisa melihat (bukan 403 — 404, anti-probe).
    assert activity.get_job(rid, str(TENANT_B)) is None
    assert activity.get_job(rid, str(TENANT_A)) is not None
    # Super admin (scope None) melihat semua.
    assert activity.get_job(rid, None) is not None


def test_nil_tenant_matches_none():
    """Job tanpa institution tetap terlihat pemanggil tanpa institution."""
    job = activity.create_job("q", None, None)
    rid = job["request_id"]
    nil = "00000000-0000-0000-0000-000000000000"
    assert activity.get_job(rid, nil) is not None


def test_list_jobs_tenant_scope_and_order():
    j1 = activity.create_job("running-a", TENANT_A, None)
    activity.create_job("done-b", TENANT_B, None)
    j3 = activity.create_job("done-a", TENANT_A, None)
    activity.complete_job(j3["request_id"], {})
    activity.set_stage(j1["request_id"], "alcd")

    rows = activity.list_jobs(str(TENANT_A))
    assert len(rows) == 2
    assert rows[0]["status"] == "running"      # running didahulukan
    assert {r["query"] for r in rows} == {"running-a", "done-a"}
    # institution_id & user_id tidak bocor ke output publik
    assert "institution_id" not in rows[0] and "user_id" not in rows[0]


def test_has_running():
    assert not activity.has_running("alcd_bootstrap")
    job = activity.create_job("x", TENANT_A, None, kind="alcd_bootstrap")
    assert activity.has_running("alcd_bootstrap")
    activity.fail_job(job["request_id"], "boom")
    assert not activity.has_running("alcd_bootstrap")
    j = activity.get_job(job["request_id"])
    assert j["status"] == "failed" and j["error"] == "boom"
