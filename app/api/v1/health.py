from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...config import settings
from ...database import get_db
from ...schemas.common import api_error, api_success

router = APIRouter(tags=["Health"])


@router.get("/health")
def api_health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return api_error("DATABASE_UNAVAILABLE", "Banco de dados indisponivel.", status_code=503)

    return api_success(
        {
            "app": settings.BUSINESS_NAME,
            "environment": settings.APP_ENV,
            "database": "ok",
        }
    )
