"""Hash-chain untuk ai_audit_logs — tamper-evident append-only log.

Setiap entri menyimpan:
- prev_hash:  SHA-256 entry_hash baris sebelumnya (urutan insert terakhir)
- entry_hash: SHA-256(prev_hash | request_id | action | action_taken |
              institution_id | user_id | timestamp)

Mengubah/menghapus/menyisipkan baris memutus rantai — terdeteksi oleh
`verify_audit_chain`. Tidak menggantikan backup/WORM storage, tapi
membuat manipulasi diam-diam menjadi terlihat.
"""
import hashlib
import logging
import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import AiAuditLog

logger = logging.getLogger("ala.audit")

_GENESIS = "0" * 64


def _entry_digest(row: AiAuditLog, prev_hash: str) -> str:
    # Normalisasi ke UTC — timestamptz dibaca kembali dengan offset sesi
    # DB (+07:00), sementara digest ditulis dari +00:00; instannya sama,
    # string isoformat-nya beda → rantai putus palsu.
    ts = row.timestamp
    if ts is not None:
        ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(
            tzinfo=timezone.utc)
    parts = [
        prev_hash,
        str(row.request_id),
        row.action or "",
        row.action_taken or "",
        str(row.institution_id or ""),
        str(row.user_id or ""),
        ts.isoformat() if ts else "",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def append_audit(db: Session, **fields) -> AiAuditLog:
    """Tulis entri audit dengan rantai hash. Commit ditangani pemanggil."""
    prev = db.scalar(
        select(AiAuditLog).order_by(AiAuditLog.timestamp.desc()).limit(1)
    )
    prev_hash = prev.entry_hash if prev and prev.entry_hash else _GENESIS
    row = AiAuditLog(timestamp=datetime.now(timezone.utc), **fields)
    row.prev_hash = prev_hash
    row.entry_hash = _entry_digest(row, prev_hash)
    db.add(row)
    return row


def verify_audit_chain(db: Session, limit: int = 10_000) -> dict:
    """Verifikasi rantai dari awal → akhir. Kembalikan status + titik putus."""
    rows = db.scalars(
        select(AiAuditLog).order_by(AiAuditLog.timestamp).limit(limit)
    ).all()
    prev_hash, checked, broken_at = _GENESIS, 0, None
    for row in rows:
        if not row.entry_hash:      # era pra-chain — lewati, catat
            continue
        if row.prev_hash != prev_hash or _entry_digest(row, prev_hash) != row.entry_hash:
            broken_at = str(row.id)
            break
        prev_hash = row.entry_hash
        checked += 1
    return {
        "valid": broken_at is None,
        "entries_checked": checked,
        "broken_at": broken_at,
    }
