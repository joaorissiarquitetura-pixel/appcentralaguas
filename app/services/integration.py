from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.contrib.auth.hashers import check_password as django_check_password
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import engine
from ..models import Customer
from ..security import gen_card_token, gen_referral_code, hash_password, verify_password
from ..services.loyalty import points_balance

logger = logging.getLogger(__name__)


def normalize_phone(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


@dataclass
class UnifiedSubscriptionSnapshot:
    linked: bool = False
    has_subscription: bool = False
    legacy_customer_id: int | None = None
    customer_profile_id: int | None = None
    customer_name: str = ""
    phone: str = ""
    plan_name: str = ""
    subscription_status: str = ""
    subscription_price: float | None = None
    next_billing_at: str | None = None
    next_delivery_at: str | None = None
    payment_method: str = ""
    promotional_badge: str = "Clientes fidelidade têm condição especial"
    personalized_offer: str = "Assine e nunca fique sem água"


def _bridge_enabled() -> bool:
    return settings.ENABLE_SUBSCRIPTION_BRIDGE


def _query_one(sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    with engine.connect() as conn:
        try:
            row = conn.execute(text(sql), params).mappings().first()
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("Integration query failed: %s", exc)
            return None


def _execute(sql: str, params: dict[str, Any]) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def ensure_legacy_link(legacy_customer_id: int, profile_row: dict[str, Any] | None, phone: str, match_type: str = "phone") -> None:
    if not _bridge_enabled() or not profile_row:
        return

    exists = _query_one(
        """
        SELECT id
        FROM accounts_legacycustomerlink
        WHERE legacy_customer_id = :legacy_customer_id
        """,
        {"legacy_customer_id": legacy_customer_id},
    )
    if exists:
        return

    _execute(
        """
        INSERT INTO accounts_legacycustomerlink
        (created_at, updated_at, legacy_customer_id, user_id, customer_profile_id, phone_snapshot, match_type, notes, active)
        VALUES (NOW(), NOW(), :legacy_customer_id, :user_id, :customer_profile_id, :phone_snapshot, :match_type, :notes, TRUE)
        """,
        {
            "legacy_customer_id": legacy_customer_id,
            "user_id": profile_row.get("user_id"),
            "customer_profile_id": profile_row.get("customer_profile_id"),
            "phone_snapshot": phone,
            "match_type": match_type,
            "notes": "Vinculo criado automaticamente pela camada de integracao.",
        },
    )


def find_profile_by_phone(phone: str) -> dict[str, Any] | None:
    if not _bridge_enabled() or not phone:
        return None
    return _query_one(
        """
        SELECT
            cp.id AS customer_profile_id,
            cp.full_name,
            cp.whatsapp,
            cp.estimated_consumption,
            u.id AS user_id,
            u.email,
            u.phone
        FROM accounts_customerprofile cp
        JOIN accounts_user u ON u.id = cp.user_id
        WHERE regexp_replace(COALESCE(cp.whatsapp, u.phone, ''), '\\D', '', 'g') = :phone
        ORDER BY cp.id ASC
        LIMIT 1
        """,
        {"phone": phone},
    )


def get_subscription_snapshot_for_phone(phone: str) -> UnifiedSubscriptionSnapshot:
    if not _bridge_enabled() or not phone:
        return UnifiedSubscriptionSnapshot(phone=phone or "")

    row = _query_one(
        """
        SELECT
            cp.id AS customer_profile_id,
            cp.full_name,
            COALESCE(cp.whatsapp, u.phone, '') AS phone,
            s.status AS subscription_status,
            s.price,
            s.next_billing_at,
            s.next_delivery_at,
            s.payment_method,
            p.name AS plan_name
        FROM accounts_customerprofile cp
        JOIN accounts_user u ON u.id = cp.user_id
        LEFT JOIN subscriptions_subscription s ON s.customer_id = cp.id
        LEFT JOIN catalog_subscriptionplan p ON p.id = s.plan_id
        WHERE regexp_replace(COALESCE(cp.whatsapp, u.phone, ''), '\\D', '', 'g') = :phone
        ORDER BY s.created_at DESC NULLS LAST, cp.id ASC
        LIMIT 1
        """,
        {"phone": phone},
    )

    if not row:
        return UnifiedSubscriptionSnapshot(phone=phone)

    has_subscription = bool(row.get("subscription_status"))
    payment_method = row.get("payment_method") or ""
    badge = "Clientes fidelidade têm condição especial" if not has_subscription else "Assinatura ativa"
    offer = (
        "Pague com cartão recorrente ou PIX programado e não fique sem água."
        if not has_subscription
        else "Sua assinatura está ativa. Precisa reforçar o pedido? Peça extra agora."
    )

    return UnifiedSubscriptionSnapshot(
        linked=True,
        has_subscription=has_subscription,
        customer_profile_id=row.get("customer_profile_id"),
        customer_name=row.get("full_name") or "",
        phone=normalize_phone(row.get("phone")),
        plan_name=row.get("plan_name") or "",
        subscription_status=row.get("subscription_status") or "",
        subscription_price=float(row.get("price")) if row.get("price") is not None else None,
        next_billing_at=str(row.get("next_billing_at")) if row.get("next_billing_at") else None,
        next_delivery_at=str(row.get("next_delivery_at")) if row.get("next_delivery_at") else None,
        payment_method=payment_method,
        promotional_badge=badge,
        personalized_offer=offer,
    )


def get_subscription_snapshot_for_customer(customer: Customer) -> UnifiedSubscriptionSnapshot:
    phone = normalize_phone(customer.phone)
    snapshot = get_subscription_snapshot_for_phone(phone)
    snapshot.legacy_customer_id = customer.id
    profile_row = find_profile_by_phone(phone)
    ensure_legacy_link(customer.id, profile_row, phone, "phone")
    return snapshot


def get_unified_offers(customer: Customer, snapshot: UnifiedSubscriptionSnapshot) -> list[dict[str, str]]:
    session = Session.object_session(customer)
    current_balance = points_balance(session, customer.id) if session else int(customer.points or 0)
    missing_points = max(settings.CARD_TARGET_POINTS - current_balance, 0)
    if snapshot.has_subscription:
        return [
            {
                "title": "Assinatura ativa",
                "description": "Pague com cartão ou PIX programado e acompanhe suas próximas entregas no mesmo painel.",
                "href": "/cliente",
                "cta": "Ver minha assinatura",
            },
            {
                "title": "Pedido extra",
                "description": "Seu consumo subiu? Complete sua rotina sem mexer no plano principal.",
                "href": "/checkout?extra=1",
                "cta": "Pedir extra",
            },
        ]

    suggested_units = 4 if (customer.people_in_home or 0) < 4 else 6
    return [
        {
            "title": "Assine e nunca fique sem água",
            "description": f"Clientes fidelidade podem migrar para um plano de {suggested_units} galões por mês com jornada mais previsível.",
            "href": "/assine",
            "cta": "Assinar agora",
        },
        {
            "title": "Pague com cartão ou PIX programado",
            "description": "Escolha recorrência no cartão ou fluxo assistido de PIX programado com acompanhamento interno.",
            "href": "/assine#pagamentos",
            "cta": "Ver formas de pagamento",
        },
        {
            "title": "Condição especial para fidelidade",
            "description": f"Faltam {missing_points} selos para seu próximo cartão. Assine e continue comprando com vantagem comercial.",
            "href": "/assine#comparador",
            "cta": "Simular economia",
        },
    ]


def authenticate_unified_customer(db: Session, identifier: str, password: str) -> Customer | None:
    identifier_clean = identifier.strip()
    phone = normalize_phone(identifier_clean)

    legacy_customer = None
    if phone:
        legacy_customer = db.query(Customer).filter(Customer.phone == phone).first()
    if legacy_customer and verify_password(password, legacy_customer.pin_hash):
        snapshot = get_subscription_snapshot_for_customer(legacy_customer)
        profile_row = find_profile_by_phone(phone)
        ensure_legacy_link(legacy_customer.id, profile_row, phone, "phone")
        return legacy_customer

    if not _bridge_enabled():
        return None

    row = _query_one(
        """
        SELECT
            u.id AS user_id,
            u.password,
            u.email,
            u.phone,
            cp.id AS customer_profile_id,
            cp.full_name,
            cp.whatsapp,
            a.street,
            a.number,
            a.neighborhood,
            a.city,
            a.state,
            a.zipcode
        FROM accounts_user u
        LEFT JOIN accounts_customerprofile cp ON cp.user_id = u.id
        LEFT JOIN accounts_address a ON a.customer_id = cp.id AND a.is_default = TRUE
        WHERE lower(u.email) = lower(:identifier)
           OR regexp_replace(COALESCE(u.phone, cp.whatsapp, ''), '\\D', '', 'g') = :phone
        ORDER BY cp.id ASC
        LIMIT 1
        """,
        {"identifier": identifier_clean, "phone": phone},
    )
    if not row or not django_check_password(password, row["password"]):
        return None

    bridge_phone = phone or normalize_phone(row.get("phone")) or normalize_phone(row.get("whatsapp"))
    existing_legacy = db.query(Customer).filter(Customer.phone == bridge_phone).first() if bridge_phone else None
    if existing_legacy:
        ensure_legacy_link(existing_legacy.id, row, bridge_phone, "phone")
        return existing_legacy

    provisioned = Customer(
        name=row.get("full_name") or row.get("email") or "Cliente Central Aguas",
        phone=bridge_phone or f"novo-{row['user_id']}",
        points=0,
        pin_hash=hash_password(password),
        referral_code=gen_referral_code(),
        card_token=gen_card_token(),
        cep=row.get("zipcode"),
        street=row.get("street"),
        number=row.get("number"),
        neighborhood=row.get("neighborhood"),
        city=row.get("city"),
        state=row.get("state"),
    )
    db.add(provisioned)
    db.commit()
    db.refresh(provisioned)
    ensure_legacy_link(provisioned.id, row, bridge_phone, "provisioned")
    return provisioned


def get_public_subscription_content() -> dict[str, Any]:
    def serialize_plan_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": row.get("name") or "",
            "description": row.get("description") or "",
            "monthly_units": int(row.get("monthly_units") or 0),
            "price": float(row.get("price") or 0),
            "highlight": row.get("highlight") or "none",
        }

    featured_plans = []
    with engine.connect() as conn:
        try:
            rows = conn.execute(
                text(
                    """
                    SELECT name, description, monthly_units, price, highlight
                    FROM catalog_subscriptionplan
                    WHERE active = TRUE
                    ORDER BY price ASC
                    LIMIT 3
                    """
                )
            ).mappings().all()
            featured_plans = [serialize_plan_row(dict(row)) for row in rows]
        except Exception as exc:
            logger.warning("Subscription catalog fallback activated: %s", exc)

    if featured_plans:
        return {"plans": featured_plans}

    fallback_plans = [
        serialize_plan_row({"name": "Plano Essencial", "description": "2 galoes por mes", "monthly_units": 2, "price": 44.90, "highlight": "recommended"}),
        serialize_plan_row({"name": "Plano Familia", "description": "4 galoes por mes", "monthly_units": 4, "price": 84.90, "highlight": "best_value"}),
        serialize_plan_row({"name": "Plano Empresa", "description": "6 galoes por mes", "monthly_units": 6, "price": 119.90, "highlight": "none"}),
    ]
    return {"plans": fallback_plans}

    return {
        "plans": [
            {"name": "Plano Essencial", "description": "2 galões por mês", "monthly_units": 2, "price": 44.90, "highlight": "recommended"},
            {"name": "Plano Família", "description": "4 galões por mês", "monthly_units": 4, "price": 84.90, "highlight": "best_value"},
            {"name": "Plano Empresa", "description": "6 galões por mês", "monthly_units": 6, "price": 119.90, "highlight": "none"},
        ]
    }


def get_commercial_map_data(db: Session) -> dict[str, Any]:
    customers = db.query(Customer).all()
    by_neighborhood: dict[str, dict[str, Any]] = {}
    markers = []

    for customer in customers:
        neighborhood = customer.neighborhood or "Sem bairro"
        bucket = by_neighborhood.setdefault(
            neighborhood,
            {
                "neighborhood": neighborhood,
                "city": customer.city or "Sem cidade",
                "customers": 0,
                "with_coordinates": 0,
                "loyalty_points": 0,
            },
        )
        bucket["customers"] += 1
        bucket["loyalty_points"] += customer.points or 0
        if customer.lat is not None and customer.lon is not None:
            bucket["with_coordinates"] += 1
            markers.append(
                {
                    "name": customer.name,
                    "lat": customer.lat,
                    "lon": customer.lon,
                    "neighborhood": neighborhood,
                    "city": customer.city,
                    "points": customer.points or 0,
                }
            )

    ranked = sorted(by_neighborhood.values(), key=lambda item: (item["customers"], item["with_coordinates"]), reverse=True)
    campaign_zones = []
    for row in ranked[:5]:
        campaign_zones.append(
            {
                "neighborhood": row["neighborhood"],
                "city": row["city"],
                "customers": row["customers"],
                "signal": "forte" if row["customers"] >= 10 else "media" if row["customers"] >= 5 else "teste",
                "reason": "Alta concentração para impulsionamento regional." if row["customers"] >= 5 else "Base pequena, boa para campanha de validação.",
            }
        )

    total_subscribers = _query_one("SELECT COUNT(*) AS total FROM subscriptions_subscription", {}) or {"total": 0}
    linked_conversion = 0
    if customers and total_subscribers["total"]:
        linked_conversion = round((total_subscribers["total"] / max(len(customers), 1)) * 100, 2)

    return {
        "customers_by_neighborhood": ranked,
        "markers": markers,
        "campaign_zones": campaign_zones,
        "summary": {
            "total_customers": len(customers),
            "with_coordinates": len(markers),
            "without_coordinates": max(len(customers) - len(markers), 0),
            "total_subscribers": total_subscribers["total"],
            "conversion_percent": linked_conversion,
        },
    }
