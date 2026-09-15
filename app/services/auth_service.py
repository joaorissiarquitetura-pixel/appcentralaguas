from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Customer
from ..security import gen_card_token, gen_referral_code, hash_password, verify_password


def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def authenticate_customer(db: Session, *, phone: str, password: str) -> Customer | None:
    phone_clean = normalize_phone(phone)
    if not phone_clean or not password:
        return None
    customer = db.scalar(select(Customer).where(Customer.phone == phone_clean))
    if not customer or not verify_password(password, customer.pin_hash):
        return None
    return customer


def parse_birth_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("BIRTH_DATE_INVALID") from exc


def validate_votuporanga_cep(zip_code: str) -> str:
    cep_clean = normalize_phone(zip_code)
    if len(cep_clean) != 8:
        raise ValueError("CEP_INVALID")
    cep_int = int(cep_clean)
    if not (15500000 <= cep_int <= 15599999):
        raise ValueError("CEP_OUT_OF_SERVICE_AREA")
    return cep_clean


def create_customer_account(
    db: Session,
    *,
    name: str,
    phone: str,
    password: str,
    birth_date: str | None = None,
    zip_code: str,
    street: str = "",
    number: str = "",
    neighborhood: str = "",
    ref_code: str | None = None,
) -> Customer:
    phone_clean = normalize_phone(phone)
    if not phone_clean:
        raise ValueError("PHONE_REQUIRED")
    if len(password) != 4 or not password.isdigit():
        raise ValueError("PASSWORD_MUST_BE_4_DIGITS")
    if db.scalar(select(Customer).where(Customer.phone == phone_clean)):
        raise ValueError("PHONE_ALREADY_REGISTERED")

    customer = Customer(
        name=name.strip(),
        phone=phone_clean,
        pin_hash=hash_password(password),
        birth_date=parse_birth_date(birth_date),
        cep=validate_votuporanga_cep(zip_code),
        street=street.strip(),
        number=number.strip(),
        neighborhood=neighborhood.strip(),
        city="Votuporanga",
        state="SP",
        card_token=gen_card_token(),
        referral_code=gen_referral_code(),
    )

    if ref_code:
        referrer = db.scalar(select(Customer).where(Customer.referral_code == ref_code.strip().upper()))
        if referrer:
            customer.referred_by_id = referrer.id

    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer
