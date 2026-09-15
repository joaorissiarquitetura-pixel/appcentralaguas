from pydantic import BaseModel


class ProductPublic(BaseModel):
    id: int | str | None = None
    external_id: str | None = None
    source: str = "local"
    slug: str | None = None
    name: str
    description: str | None = None
    category: str | None = None
    pickup_price: float | None = None
    delivery_price: float | None = None
    promo_pickup_price: float | None = None
    promo_delivery_price: float | None = None
    badge: str | None = None
    image_url: str | None = None
    stock_status: str | None = None
    active: bool = True
    featured: bool = False
    display_order: int = 0
