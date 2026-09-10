import os
import tempfile
from pathlib import Path

TEST_DB_PATH = Path(tempfile.gettempdir()) / "central_aguas_test_app.db"

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-32-characters!!")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH.as_posix()}")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
os.environ.setdefault("ALLOW_AUTO_SEED_IN_PRODUCTION", "false")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "test-admin-password")
os.environ["CENTRAL_AGUAS_APP_TOKEN"] = ""

from app.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402


def reset_database():
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()
