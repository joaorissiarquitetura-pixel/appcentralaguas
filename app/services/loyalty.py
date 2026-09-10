from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Customer, LoyaltyLedger, Transaction


def points_balance(db: Session, customer_id: int) -> int:
    stmt = select(func.coalesce(func.sum(LoyaltyLedger.delta_points), 0)).where(
        LoyaltyLedger.customer_id == customer_id
    )
    total = db.scalar(stmt)
    return int(total or 0)


def cards_completed(balance: int) -> int:
    if settings.CARD_TARGET_POINTS == 0:
        return 0
    return balance // settings.CARD_TARGET_POINTS


def card_progress(balance: int) -> int:
    if settings.CARD_TARGET_POINTS == 0:
        return 0
    return balance % settings.CARD_TARGET_POINTS


def weekday_multiplier(dt_utc_naive: datetime) -> int:
    return 1


def _birthday_for_year(birth_date: date, year: int) -> date:
    try:
        return birth_date.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def is_birthday_bonus_period(customer: Customer, dt_utc_naive: datetime) -> bool:
    if not customer.birth_date:
        return False

    if dt_utc_naive.tzinfo is None:
        dt_utc = dt_utc_naive.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc_naive.astimezone(timezone.utc)

    local_date = dt_utc.astimezone(ZoneInfo(settings.LOCAL_TZ)).date()
    birthday_dates = [
        _birthday_for_year(customer.birth_date, local_date.year - 1),
        _birthday_for_year(customer.birth_date, local_date.year),
        _birthday_for_year(customer.birth_date, local_date.year + 1),
    ]
    return any(abs((local_date - birthday).days) <= 3 for birthday in birthday_dates)


def award_transaction_points(db: Session, transaction: Transaction, quantity_purchased: int) -> int:
    mult = 2 if is_birthday_bonus_period(transaction.customer, transaction.created_at) else weekday_multiplier(
        transaction.created_at
    )
    total_points = quantity_purchased * mult

    if total_points == 0:
        return 0

    transaction.customer.points = (transaction.customer.points or 0) + total_points
    transaction.points = total_points

    reason_txt = "Compra - Semana do aniversario (pontos em dobro)" if mult == 2 else "Compra"

    ledger_entry = LoyaltyLedger(
        customer_id=transaction.customer.id,
        transaction_id=transaction.id,
        delta_points=total_points,
        reason=reason_txt,
        created_at=datetime.utcnow(),
    )
    db.add(ledger_entry)
    db.add(transaction)
    db.add(transaction.customer)
    db.commit()

    return total_points


def handle_first_purchase_and_referral(db: Session, customer: Customer, now_utc_naive: datetime):
    customer.last_purchase_at = now_utc_naive

    if customer.first_purchase_at is None:
        customer.first_purchase_at = now_utc_naive

        if customer.referred_by_id and not customer.referral_bonus_awarded:
            ledger_entry = LoyaltyLedger(
                customer_id=customer.referred_by_id,
                delta_points=settings.REFERRAL_BONUS_POINTS,
                reason=f"Bonus indicacao (+{settings.REFERRAL_BONUS_POINTS})",
                created_at=datetime.utcnow(),
            )
            db.add(ledger_entry)

            referrer = db.get(Customer, customer.referred_by_id)
            if referrer:
                referrer.points = (referrer.points or 0) + settings.REFERRAL_BONUS_POINTS
                db.add(referrer)

            customer.referral_bonus_awarded = True
            db.add(customer)
            db.commit()
