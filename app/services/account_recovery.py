from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Customer, PasswordResetToken
from ..security import hash_password, hash_token, generate_secure_token
from ..utils.time import utcnow_naive

logger = logging.getLogger(__name__)


def issue_password_reset_token(
    db: Session,
    *,
    customer: Customer,
    created_by_attendant_id: int | None = None,
) -> str:
    now = utcnow_naive()
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.customer_id == customer.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    plain_token = generate_secure_token(24)
    db.add(
        PasswordResetToken(
            customer_id=customer.id,
            token_hash=hash_token(plain_token),
            created_by_attendant_id=created_by_attendant_id,
            expires_at=now + timedelta(minutes=settings.RESET_TOKEN_TTL_MINUTES),
        )
    )
    logger.info("Issued password reset token for customer_id=%s", customer.id)
    return plain_token


def get_valid_reset_token(db: Session, token: str) -> PasswordResetToken | None:
    token_hash = hash_token(token)
    candidate = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if not candidate:
        return None
    if candidate.used_at is not None:
        return None
    if candidate.expires_at < utcnow_naive():
        return None
    return candidate


def reset_customer_password_with_token(
    db: Session,
    *,
    token: str,
    new_password: str,
) -> Customer:
    reset_token = get_valid_reset_token(db, token)
    if not reset_token:
        raise ValueError("invalid_or_expired_token")

    customer = db.get(Customer, reset_token.customer_id)
    if not customer:
        raise ValueError("customer_not_found")

    customer.pin_hash = hash_password(new_password)
    reset_token.used_at = utcnow_naive()
    db.add(customer)
    db.add(reset_token)
    logger.info("Customer password reset completed for customer_id=%s", customer.id)
    return customer
