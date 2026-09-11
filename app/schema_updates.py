from __future__ import annotations

from sqlalchemy import inspect, text

from .database import engine
from .models import AppDevice, AppNotification, Coupon, LocationAccessLog, PushSubscription


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

APP_DEVICE_COLUMN_SPECS = {
    "fcm_token": "TEXT",
    "fcm_token_updated_at": "DATETIME",
    "is_blocked": "BOOLEAN DEFAULT FALSE",
    "block_reason": "VARCHAR(180)",
    "blocked_at": "DATETIME",
}


def ensure_runtime_schema_updates() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    for table_model in (Coupon, AppDevice, PushSubscription, LocationAccessLog, AppNotification):
        table_model.__table__.create(bind=engine, checkfirst=True)

    if "products" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("products")}

    with engine.begin() as conn:
        for column_name, sql_type in PRODUCT_COLUMN_SPECS.items():
            if column_name in existing_columns:
                continue
            conn.execute(text(f"ALTER TABLE products ADD COLUMN {column_name} {sql_type}"))

    if "app_devices" not in inspector.get_table_names():
        return

    existing_device_columns = {column["name"] for column in inspector.get_columns("app_devices")}
    with engine.begin() as conn:
        for column_name, sql_type in APP_DEVICE_COLUMN_SPECS.items():
            if column_name in existing_device_columns:
                continue
            conn.execute(text(f"ALTER TABLE app_devices ADD COLUMN {column_name} {sql_type}"))
