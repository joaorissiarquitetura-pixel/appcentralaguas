import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import engine
from .models import Attendant, Base, Product
from .security import hash_password

logger = logging.getLogger(__name__)

DEFAULT_PRODUCTS = [
    ("Galão 20L", 1),
]


def create_tables():
    Base.metadata.create_all(bind=engine)


def seed_if_needed(db: Session):
    if settings.is_production and not settings.ALLOW_AUTO_SEED_IN_PRODUCTION:
        logger.info("Skipping auto seed in production environment.")
        return

    has_product = db.scalar(select(Product.id).limit(1))
    if not has_product:
        for name, pts in DEFAULT_PRODUCTS:
            db.add(
                Product(
                    name=name,
                    description="Água mineral para retirada ou entrega.",
                    points_per_unit=pts,
                    pickup_price=14.0,
                    delivery_price=16.0,
                    promo_pickup_price=8.99,
                    promo_delivery_price=11.99,
                    promo_badge="Oferta do site",
                    stock_status="disponivel",
                    display_order=0,
                    featured_on_home=True,
                    active=True,
                )
            )

    admin = db.scalar(select(Attendant).where(Attendant.email == settings.SEED_ADMIN_EMAIL))
    if not admin:
        logger.warning("Creating seed admin attendant for %s", settings.SEED_ADMIN_EMAIL)
        db.add(
            Attendant(
                name=settings.SEED_ADMIN_NAME,
                email=settings.SEED_ADMIN_EMAIL,
                password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
                role="admin",
                is_active=True,
            )
        )

    db.commit()
