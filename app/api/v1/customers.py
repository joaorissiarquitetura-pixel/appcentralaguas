from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth import get_current_customer_id
from ...database import get_db
from ...models import Customer, LoyaltyLedger
from ...schemas.common import api_error, api_success
from ...services.loyalty import card_progress, cards_completed, points_balance

router = APIRouter()


def _require_customer(request: Request, db: Session) -> Customer | None:
    customer_id = get_current_customer_id(request)
    if not customer_id:
        return None
    return db.get(Customer, int(customer_id))


@router.get("/me")
def customer_me(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if not customer:
        return api_error("NOT_AUTHENTICATED", "Cliente nao autenticado.", status_code=401)

    balance = points_balance(db, customer.id)
    return api_success(
        {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "birth_date": customer.birth_date.isoformat() if customer.birth_date else None,
            "address": {
                "cep": customer.cep,
                "street": customer.street,
                "number": customer.number,
                "complement": customer.complement,
                "neighborhood": customer.neighborhood,
                "city": customer.city,
                "state": customer.state,
                "lat": customer.lat,
                "lon": customer.lon,
            },
            "loyalty": {
                "balance": balance,
                "card_progress": card_progress(balance),
                "cards_completed": cards_completed(balance),
            },
            "preferences": {
                "buy_mode": customer.buy_mode,
                "people_in_home": customer.people_in_home,
            },
        }
    )


@router.get("/me/loyalty")
def customer_loyalty(request: Request, db: Session = Depends(get_db)):
    customer = _require_customer(request, db)
    if not customer:
        return api_error("NOT_AUTHENTICATED", "Cliente nao autenticado.", status_code=401)

    balance = points_balance(db, customer.id)
    ledger = db.execute(
        select(LoyaltyLedger)
        .where(LoyaltyLedger.customer_id == customer.id)
        .order_by(LoyaltyLedger.created_at.desc())
        .limit(30)
    ).scalars().all()
    return api_success(
        {
            "balance": balance,
            "card_progress": card_progress(balance),
            "cards_completed": cards_completed(balance),
            "statement": [
                {
                    "id": item.id,
                    "delta_points": item.delta_points,
                    "reason": item.reason,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "transaction_id": item.transaction_id,
                    "redemption_id": item.redemption_id,
                }
                for item in ledger
            ],
        }
    )
