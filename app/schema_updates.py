from __future__ import annotations

from sqlalchemy import inspect, text

from .database import engine


PRODUCT_COLUMN_SPECS = {
    "description": "TEXT",
    "pickup_price": "FLOAT",
    "delivery_price": "FLOAT",
    "promo_pickup_price": "FLOAT",
    "promo_delivery_price": "FLOAT",
    "promo_badge": "VARCHAR(80)",
    "image_url": "VARCHAR(500)",
    "stock_status": "VARCHAR(40) DEFAULT 'disponivel'",
    "display_order": "INTEGER DEFAULT 0",
    "featured_on_home": "BOOLEAN DEFAULT FALSE",
}


def ensure_runtime_schema_updates() -> None:
    inspector = inspect(engine)
    if "products" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("products")}

    with engine.begin() as conn:
        for column_name, sql_type in PRODUCT_COLUMN_SPECS.items():
            if column_name in existing_columns:
                continue
            conn.execute(text(f"ALTER TABLE products ADD COLUMN {column_name} {sql_type}"))
