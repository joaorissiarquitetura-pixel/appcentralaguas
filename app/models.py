from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Date, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, date
from .database import Base

class Customer(Base):
    __tablename__ = "customers"

    # Usando style Column (Legacy) conforme seu código
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    phone = Column(String, unique=True, index=True)
    
    # --- A LINHA QUE VOCÊ ADICIONOU (AGORA FUNCIONA) ---
    points = Column(Integer, default=0) 
    # ---------------------------------------------------

    # Usando style Mapped (Moderno)
    pin_hash: Mapped[str] = mapped_column(String(255))
    must_change_password = Column(Boolean, default=False, nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Indicação
    referral_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    card_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    referred_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id"), nullable=True)
    referred_by = relationship("Customer", remote_side=[id], backref="referrals")
    referral_bonus_awarded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Consumo
    people_in_home: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_purchase_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_purchase_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Endereço
    cep: Mapped[str | None] = mapped_column(String(10), nullable=True)
    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    complement: Mapped[str | None] = mapped_column(String(120), nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Entrega/Retira
    buy_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Vinculo manual com o sistema Central Aguas
    central_customer_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    central_linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Coordenadas
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_attendant_id: Mapped[int | None] = mapped_column(ForeignKey("attendants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivery_channel: Mapped[str] = mapped_column(String(20), default="manual")
    destination_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    customer = relationship("Customer")

class Attendant(Base):
    __tablename__ = "attendants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="attendant")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    points_per_unit: Mapped[int] = mapped_column(Integer, default=1)
    pickup_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    promo_pickup_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    promo_delivery_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    promo_badge: Mapped[str | None] = mapped_column(String(80), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(40), default="disponivel")
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    featured_on_home: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Coupon(Base):
    __tablename__ = "coupons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str] = mapped_column(String(20), default="fixed")
    discount_value: Mapped[float] = mapped_column(Float, default=0)
    min_order_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AppDevice(Base):
    __tablename__ = "app_devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_permission: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location_permission: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fcm_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    fcm_token_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[str | None] = mapped_column(String(180), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")

class LocationAccessLog(Base):
    __tablename__ = "location_access_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    permission_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")

class AppNotification(Base):
    __tablename__ = "app_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(String(30), default="all")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_attendant_id: Mapped[int | None] = mapped_column(ForeignKey("attendants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by = relationship("Attendant")

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    attendant_id: Mapped[int] = mapped_column(ForeignKey("attendants.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    channel: Mapped[str] = mapped_column(String(20), default="delivery")
    points: Mapped[int] = mapped_column(Integer, default=0)
    # Campo extra para facilitar a visualização no recibo (opcional no banco, mas útil no código)
    # Se você quiser salvar no banco, descomente a linha abaixo:
    # quantity: Mapped[int] = mapped_column(Integer, default=1)

    customer = relationship("Customer")
    attendant = relationship("Attendant")
    items = relationship("TransactionItem", cascade="all, delete-orphan", back_populates="transaction")

class TransactionItem(Base):
    __tablename__ = "transaction_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)

    transaction = relationship("Transaction", back_populates="items")
    product = relationship("Product")

class Redemption(Base):
    __tablename__ = "redemptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    attendant_id: Mapped[int] = mapped_column(ForeignKey("attendants.id"))
    points_spent: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class LoyaltyLedger(Base):
    __tablename__ = "loyalty_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    redemption_id: Mapped[int | None] = mapped_column(ForeignKey("redemptions.id"), nullable=True)
    delta_points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer = relationship("Customer")
