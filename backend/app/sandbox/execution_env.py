"""
Isolated Docker runtime for AI-generated utility tools.

Spins up micro-containers with:
- network_mode: none (no network access)
- read_only filesystem (except /tmp via tmpfs)
- Memory limit: dynamic — max 25% of host RAM via HIRO
  (see app.config.get_sandbox_mem_limit; baseline 256MB)
- CPU limit: 0.5 cores
- 30-second execution timeout
- Non-root user (sandbox:1000)

Only utility-level programs run here — core agent frameworks are NEVER
touched. Setiap eksekusi memerlukan persetujuan manusia terlebih dahulu
(approve-workflow endpoint) — modul ini tidak mengecek approval sendiri;
itulah tanggung jawab lapisan API.
"""
import hashlib
import logging
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.sandbox.guardrails import scan_code

logger = logging.getLogger("ala.sandbox.exec")

SANDBOX_IMAGE = "ala-sandbox:latest"
_EXEC_TIMEOUT = 30  # detik
_CPU_QUOTA = 50000  # 0.5 CPU (cfs quota vs period 100000)
_CPU_PERIOD = 100000


@dataclass
class ExecutionResult:
    """Hasil satu eksekusi sandbox."""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    guardrail_violations: list[str] = field(default_factory=list)
    custody_verified: bool | None = None
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def _docker_client():
    import docker

    return docker.from_env()


def run_in_sandbox(
    code: str,
    filename: str = "utility.py",
    evidence_host_path: str | None = None,
) -> ExecutionResult:
    """Validasi lalu eksekusi kode AI di kontainer Docker terkunci.

    Args:
        code: source Python hasil generate.
        filename: nama file di dalam sandbox (/sandbox/).
        evidence_host_path: path host ke file bukti — dimount READ-ONLY
            ke /evidence/ jika diberikan.

    Returns:
        ExecutionResult — tidak pernah raise; error → success=False.
    """
    result = ExecutionResult()

    # ── Lapis 1: guardrail scan (wajib lolos) ───────────────────────
    scan = scan_code(code)
    if not scan.allowed:
        result.guardrail_violations = scan.violations
        result.stderr = scan.summary
        logger.warning("Eksekusi ditolak guardrail: %s",
                       "; ".join(scan.violations[:5]))
        return result
    result.custody_verified = "sha256" in code or None

    # ── Lapis 2: jalankan di kontainer terkunci ──────────────────────
    from app.config import get_sandbox_mem_limit

    mem_limit = get_sandbox_mem_limit()

    volumes = {}
    if evidence_host_path:
        volumes[evidence_host_path] = {
            "bind": "/evidence",
            "mode": "ro",  # KUHAP: bukti tidak pernah dimutasi
        }

    try:
        client = _docker_client()
    except Exception as exc:
        result.stderr = f"Docker tidak tersedia: {exc}"
        return result

    container_name = f"ala-exec-{result.execution_id}"
    container = None
    try:
        # Kode dikirim via base64 di command — put_archive ditolak
        # daemon pada container read_only. Kode ditulis ke tmpfs /tmp.
        import base64

        b64 = base64.b64encode(code.encode()).decode()
        inner = (
            f"echo {b64} | base64 -d > /tmp/u_{result.execution_id}.py "
            f"&& timeout {_EXEC_TIMEOUT} python /tmp/u_{result.execution_id}.py"
        )
        container = client.containers.run(
            image=SANDBOX_IMAGE,
            command=["sh", "-c", inner],
            name=container_name,
            detach=True,
            network_mode="none",
            read_only=True,
            tmpfs={"/tmp": "rw,nosuid,size=64m"},
            mem_limit=mem_limit,
            cpu_period=_CPU_PERIOD,
            cpu_quota=_CPU_QUOTA,
            pids_limit=64,
            user="sandbox_user",
            volumes=volumes,
            environment={},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
        )
        # Tunggu maks timeout + buffer; stop paksa jika bandel
        try:
            wait_res = container.wait(timeout=_EXEC_TIMEOUT + 15)
            result.exit_code = wait_res.get("StatusCode", -1)
        except Exception:
            container.stop(timeout=3)
            result.timed_out = True
            result.exit_code = 124

        result.stdout = container.logs(stdout=True, stderr=False).decode(
            errors="replace")[:8000]
        result.stderr = container.logs(stdout=False, stderr=True).decode(
            errors="replace")[:4000]
        result.timed_out = result.timed_out or result.exit_code == 124
        if result.timed_out:
            result.stderr += (
                f"\n[ALA] Eksekusi dihentikan — melebihi "
                f"{_EXEC_TIMEOUT}s."
            )
        result.success = result.exit_code == 0

    except Exception as exc:
        logger.exception("Eksekusi sandbox gagal")
        result.stderr = f"Sandbox error: {exc}"
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass

    return result


def verify_evidence_integrity(host_path: str) -> dict:
    """SHA-256 bukti host-side — cross-check dengan hash di dalam sandbox."""
    h = hashlib.sha256()
    with open(host_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return {
        "evidence_file": host_path,
        "sha256_host": h.hexdigest(),
    }
