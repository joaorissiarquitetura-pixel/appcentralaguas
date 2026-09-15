from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product
from ..services.grj_catalog import GRJCatalogUnavailable, fetch_grj_products, product_to_public_dict


def _slug_from_text(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _catalog_image_for_name(name: str) -> str | None:
    name_lower = name.lower()
    if "510" in name_lower or "500" in name_lower or "fardo" in name_lower:
        return "/static/img/510.png"
    if "20" in name_lower:
        return "/static/img/20.png"
    if "10" in name_lower:
        return "/static/img/10.png"
    return None


def product_category(name: str, description: str = "") -> str:
    text = f"{name} {description}".lower()
    if "fardo" in text:
        return "fardos"
    if "gas" in text or "gás" in text:
        return "gas"
    if any(term in text for term in ("garrafao", "garrafão", "galao", "galão", "20l", "10l")):
        return "galoes"
    return "outros"


def local_product_to_api(product: Product) -> dict:
    description = product.description or "Agua mineral Central Aguas."
    pickup_price = product.promo_pickup_price or product.pickup_price or 0
    delivery_price = product.promo_delivery_price or product.delivery_price or pickup_price
    image_url = product.image_url or _catalog_image_for_name(product.name)
    return {
        "id": product.id,
        "external_id": str(product.id),
        "source": "local",
        "slug": _slug_from_text(product.name) or f"produto-{product.id}",
        "name": product.name,
        "description": description,
        "category": product_category(product.name, description),
        "pickup_price": pickup_price,
        "delivery_price": delivery_price,
        "promo_pickup_price": product.promo_pickup_price,
        "promo_delivery_price": product.promo_delivery_price,
        "badge": product.promo_badge,
        "image_url": image_url,
        "stock_status": product.stock_status or "disponivel",
        "active": bool(product.active),
        "featured": bool(product.featured_on_home),
        "display_order": product.display_order or 0,
    }


def list_products_for_api(db: Session, *, include_inactive: bool = False, limit: int = 100) -> tuple[list[dict], str]:
    try:
        grj_products = fetch_grj_products(limit=limit)
    except GRJCatalogUnavailable:
        grj_products = []

    if grj_products:
        return [product_to_public_dict(product) for product in grj_products[:limit]], "grj"

    stmt = select(Product).order_by(Product.display_order.asc(), Product.name.asc()).limit(limit)
    if not include_inactive:
        stmt = stmt.where(Product.active == True)
    products = db.execute(stmt).scalars().all()
    return [local_product_to_api(product) for product in products], "local"
