from fastapi import APIRouter

from . import app, auth, customers, health, products

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(app.router, prefix="/app", tags=["App"])
router.include_router(auth.router, prefix="/auth", tags=["Auth"])
router.include_router(customers.router, prefix="/customers", tags=["Customers"])
router.include_router(products.router, prefix="/products", tags=["Products"])
