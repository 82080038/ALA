"""Seed admin pertama — bootstrap akun super_admin bila tabel users kosong.

Zero-cost standalone: tidak perlu layanan eksternal. Password diambil dari
env ALA_ADMIN_PASSWORD; bila kosong, password acak digenerate dan dicetak
SEKALI ke stdout (tidak disimpan di mana pun selain hash bcrypt di DB).

Jalankan:  .venv/bin/python scripts/seed_admin.py
Idempotent: tidak melakukan apa pun bila sudah ada user.
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.database.postgres import SessionLocal  # noqa: E402
from app.models.tenant import Institution, User  # noqa: E402


def main() -> int:
    with SessionLocal() as db:
        n_users = db.scalar(select(func.count()).select_from(User))
        if n_users:
            print(f"users sudah berisi {n_users} baris — tidak ada yang diubah.")
            return 0

        # Pakai institusi pertama yang ada; buat tenant platform bila kosong
        inst = db.scalar(select(Institution).limit(1))
        if not inst:
            inst = Institution(name="ALA Platform", type="platform")
            db.add(inst)
            db.flush()

        password = os.environ.get("ALA_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
        email = os.environ.get("ALA_ADMIN_EMAIL", "admin@ala.local").lower()
        admin = User(
            institution_id=inst.id,
            name="Super Admin",
            email=email,
            password_hash=hash_password(password),
            role="super_admin",
            tier_level="premium_l2",
        )
        db.add(admin)
        db.commit()

        print(f"Institusi: {inst.name} ({inst.id})")
        print(f"Admin    : {email} (role=super_admin, tier=premium_l2)")
        if "ALA_ADMIN_PASSWORD" not in os.environ:
            print(f"Password : {password}")
            print("!! Simpan password ini — tidak ditampilkan lagi.")
        print("Login: POST /api/v1/auth/login {email, password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
