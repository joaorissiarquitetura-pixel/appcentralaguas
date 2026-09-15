from __future__ import annotations

from sqlalchemy import inspect, text

from .database import engine
from .models import AdminAuditLog, AppDevice, AppNotification, Coupon, LocationAccessLog, PushSubscription


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


def _compiled_column_type(column) -> str:
    return column.type.compile(dialect=engine.dialect)


def _ensure_missing_columns(table_name: str, column_specs: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    with engine.begin() as conn:
        for column_name, sql_type in column_specs.items():
            if column_name in existing_columns:
                continue
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"))


def _ensure_model_columns(table_model) -> None:
    column_specs = {
        column.name: _compiled_column_type(column)
        for column in table_model.__table__.columns
        if not column.primary_key
    }
    _ensure_missing_columns(table_model.__tablename__, column_specs)


def ensure_runtime_schema_updates() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    for table_model in (Coupon, AppDevice, PushSubscription, LocationAccessLog, AppNotification, AdminAuditLog):
        table_model.__table__.create(bind=engine, checkfirst=True)
        _ensure_model_columns(table_model)

    if "products" not in table_names:
        return

    _ensure_missing_columns("products", PRODUCT_COLUMN_SPECS)

    if "app_devices" not in inspector.get_table_names():
        return

    _ensure_missing_columns("app_devices", APP_DEVICE_COLUMN_SPECS)
