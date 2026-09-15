from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas.common import api_success
from ...services.catalog_service import list_products_for_api

router = APIRouter()


@router.get("")
def list_products(
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    products, source = list_products_for_api(db, include_inactive=include_inactive, limit=limit)
    return api_success(products, meta={"source": source, "count": len(products), "limit": limit})
