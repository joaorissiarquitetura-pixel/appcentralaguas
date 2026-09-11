import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import SessionLocal
from app.init_db import create_tables
from app.models import Attendant
from app.schema_updates import ensure_runtime_schema_updates
from app.security import hash_password, verify_password


def main() -> None:
    create_tables()
    ensure_runtime_schema_updates()
    db = SessionLocal()
    try:
        admin = db.query(Attendant).filter(Attendant.email == settings.SEED_ADMIN_EMAIL).first()
        if not admin:
            admin = Attendant(
                name=settings.SEED_ADMIN_NAME,
                email=settings.SEED_ADMIN_EMAIL,
                password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
                role="admin",
                is_active=True,
            )
            db.add(admin)
        else:
            admin.password_hash = hash_password(settings.SEED_ADMIN_PASSWORD)
            admin.role = "admin"
            admin.is_active = True
        db.commit()
        ok = verify_password(settings.SEED_ADMIN_PASSWORD, admin.password_hash)
        print(f"{admin.email} role={admin.role} active={admin.is_active} password_ok={ok}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
