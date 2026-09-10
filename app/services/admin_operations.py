from __future__ import annotations

import json
import logging
import time as _time
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, Attendant, Customer, LoyaltyLedger, Product, Redemption, Transaction, TransactionItem
from ..services.account_recovery import issue_password_reset_token
from ..services.address import geocode_structured
from ..services.audit import log_admin_action
from ..services.loyalty import points_balance, recalculate_all_points
from ..utils.time import utcnow_naive

logger = logging.getLogger(__name__)


def issue_customer_reset_link(db: Session, *, customer: Customer, actor_attendant_id: int) -> str:
    token = issue_password_reset_token(
        db,
        customer=customer,
        created_by_attendant_id=actor_attendant_id,
    )
    log_admin_action(
        db,
        action="customer_password_reset_issued",
        actor_attendant_id=actor_attendant_id,
        entity_type="customer",
        entity_id=customer.id,
        details={"token_ttl_minutes": settings.RESET_TOKEN_TTL_MINUTES},
    )
    return f"/redefinir-senha?token={token}"


def delete_customer_safely(db: Session, *, customer: Customer, actor_attendant_id: int) -> None:
    db.execute(
        delete(TransactionItem).where(
            TransactionItem.transaction_id.in_(
                select(Transaction.id).where(Transaction.customer_id == customer.id)
            )
        )
    )
    db.execute(delete(LoyaltyLedger).where(LoyaltyLedger.customer_id == customer.id))
    db.execute(delete(Redemption).where(Redemption.customer_id == customer.id))
    db.execute(delete(Transaction).where(Transaction.customer_id == customer.id))
    db.execute(delete(Alert).where(Alert.customer_id == customer.id))
    db.delete(customer)
    log_admin_action(
        db,
        action="customer_deleted",
        actor_attendant_id=actor_attendant_id,
        entity_type="customer",
        entity_id=customer.id,
        details={"customer_name": customer.name},
    )
    logger.warning("Customer deleted by admin actor=%s customer_id=%s", actor_attendant_id, customer.id)


def generate_alerts(db: Session, *, actor_attendant_id: int | None = None) -> int:
    generated = 0
    customers = db.execute(select(Customer)).scalars().all()
    for customer in customers:
        last_txs = db.execute(
            select(Transaction)
            .where(Transaction.customer_id == customer.id)
            .order_by(Transaction.created_at.desc())
            .limit(5)
        ).scalars().all()
        if len(last_txs) < 2:
            continue

        intervals = [
            max(1, (last_txs[i].created_at - last_txs[i + 1].created_at).days)
            for i in range(len(last_txs) - 1)
        ]
        avg_days = sum(intervals) / len(intervals)
        days_since = (utcnow_naive() - last_txs[0].created_at).days
        threshold = avg_days + max(2, avg_days * 0.3)
        if days_since > threshold:
            exists = db.scalar(
                select(Alert).where(
                    Alert.customer_id == customer.id,
                    Alert.type == "overdue",
                    Alert.resolved_at.is_(None),
                )
            )
            if not exists:
                db.add(
                    Alert(
                        customer_id=customer.id,
                        type="overdue",
                        severity="warn",
                        message=f"Atrasado! {days_since} dias.",
                        created_at=utcnow_naive(),
                    )
                )
                generated += 1

    if actor_attendant_id is not None:
        log_admin_action(
            db,
            action="alerts_generated",
            actor_attendant_id=actor_attendant_id,
            details={"generated": generated},
        )
    return generated


def sync_points_cache(db: Session, *, actor_attendant_id: int | None = None) -> int:
    total = recalculate_all_points(db)
    if actor_attendant_id is not None:
        log_admin_action(
            db,
            action="loyalty_cache_recalculated",
            actor_attendant_id=actor_attendant_id,
            details={"customers": total},
        )
    return total


def geocode_pending_customers(db: Session, *, actor_attendant_id: int | None = None) -> int:
    pending = db.execute(
        select(Customer).where(Customer.lat.is_(None), Customer.street.is_not(None))
    ).scalars().all()
    updated = 0
    for customer in pending:
        rua = customer.street
        if rua and not rua.lower().startswith(("rua", "av", "alameda", "travessa", "praca", "praça")):
            rua = f"Rua {rua}"
        result = geocode_structured(street=rua, city=customer.city or "Votuporanga", cep=customer.cep)
        if result:
            customer.lat, customer.lon = result
            db.add(customer)
            updated += 1
        _time.sleep(1.2)

    if actor_attendant_id is not None:
        log_admin_action(
            db,
            action="customers_geocoded",
            actor_attendant_id=actor_attendant_id,
            details={"updated": updated},
        )
    return updated


def customer_history_payload(db: Session, *, customer: Customer) -> dict:
    ledger = db.execute(
        select(LoyaltyLedger)
        .where(LoyaltyLedger.customer_id == customer.id)
        .order_by(LoyaltyLedger.created_at.desc())
        .limit(20)
    ).scalars().all()
    return {
        "name": customer.name,
        "phone": customer.phone,
        "total_points": points_balance(db, customer.id),
        "history": [
            {
                "date": entry.created_at.strftime("%d/%m/%Y %H:%M"),
                "points": f"+{entry.delta_points}" if entry.delta_points > 0 else str(entry.delta_points),
                "reason": entry.reason,
            }
            for entry in ledger
        ],
    }
