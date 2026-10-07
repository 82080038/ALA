"""Uji integrasi sandbox Docker — dilewati otomatis bila daemon atau image
`ala-sandbox:latest` tidak tersedia (mis. di CI host tanpa socket)."""
import pytest

from app.sandbox.execution_env import run_in_sandbox


def _sandbox_ready() -> bool:
    try:
        import docker

        client = docker.from_env(timeout=10)
        client.ping()
        client.images.get("ala-sandbox:latest")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _sandbox_ready(),
    reason="Docker socket atau image ala-sandbox:latest tidak tersedia",
)


def test_safe_code_executes():
    r = run_in_sandbox("import json\nprint(json.dumps({'ok': True}))")
    assert r.success and r.exit_code == 0
    assert '"ok": true' in r.stdout.lower() or '"ok":true' in r.stdout.lower()


def test_malicious_code_blocked_before_exec():
    r = run_in_sandbox("import os\nos.system('id')")
    assert not r.success
    assert r.guardrail_violations  # pelanggaran tercatat


def test_infinite_loop_times_out():
    r = run_in_sandbox("while True: pass")
    assert not r.success
    assert r.timed_out
