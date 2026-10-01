from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Customer, PasswordResetToken
from ..security import hash_password, hash_token, generate_secure_token
from ..utils.time import utcnow_naive
from .whatsapp import normalize_brazilian_phone

logger = logging.getLogger(__name__)
GENERIC_RESET_MESSAGE = "Se o WhatsApp informado estiver cadastrado, enviaremos um codigo para redefinir sua senha."
_RECOVERY_REQUESTS_BY_PHONE: dict[str, list] = {}
_RECOVERY_REQUESTS_BY_IP: dict[str, list] = {}


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
            delivery_channel="manual_link",
            destination_phone=customer.phone,
        )
    )
    logger.info("Issued password reset token for customer_id=%s", customer.id)
    return plain_token


def issue_password_reset_code(
    db: Session,
    *,
    customer: Customer,
    created_by_attendant_id: int | None = None,
    request_ip: str | None = None,
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

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    db.add(
        PasswordResetToken(
            customer_id=customer.id,
            token_hash=hash_token(code),
            created_by_attendant_id=created_by_attendant_id,
            expires_at=now + timedelta(minutes=settings.RESET_CODE_TTL_MINUTES),
            delivery_channel="phone_code",
            destination_phone=customer.phone,
            request_ip=(request_ip or "")[:80] or None,
        )
    )
    logger.info("Issued password reset code for customer_id=%s", customer.id)
    return code


def normalize_recovery_phone(phone: str | None) -> str | None:
    return normalize_brazilian_phone(phone)


def find_customer_by_recovery_phone(db: Session, phone: str | None) -> Customer | None:
    normalized = normalize_recovery_phone(phone)
    if not normalized:
        return None

    candidates = db.execute(select(Customer)).scalars().all()
    for customer in candidates:
        if normalize_recovery_phone(customer.phone) == normalized:
            return customer
    return None


def _has_recent_request_limit(
    db: Session,
    *,
    customer: Customer | None,
    phone: str | None,
    request_ip: str | None,
) -> bool:
    now = utcnow_naive()
    window_start = now - timedelta(minutes=settings.RESET_REQUEST_WINDOW_MINUTES)
    normalized = normalize_recovery_phone(phone)

    if normalized and settings.RESET_REQUEST_LIMIT_PER_PHONE > 0:
        phone_key = hash_token(normalized)
        phone_hits = [hit for hit in _RECOVERY_REQUESTS_BY_PHONE.get(phone_key, []) if hit >= window_start]
        if len(phone_hits) >= settings.RESET_REQUEST_LIMIT_PER_PHONE:
            _RECOVERY_REQUESTS_BY_PHONE[phone_key] = phone_hits
            return True
        phone_hits.append(now)
        _RECOVERY_REQUESTS_BY_PHONE[phone_key] = phone_hits

    if request_ip and settings.RESET_REQUEST_LIMIT_PER_IP > 0:
        ip_key = hash_token(request_ip[:80])
        ip_hits = [hit for hit in _RECOVERY_REQUESTS_BY_IP.get(ip_key, []) if hit >= window_start]
        if len(ip_hits) >= settings.RESET_REQUEST_LIMIT_PER_IP:
            _RECOVERY_REQUESTS_BY_IP[ip_key] = ip_hits
            return True
        ip_hits.append(now)
        _RECOVERY_REQUESTS_BY_IP[ip_key] = ip_hits

    if customer and settings.RESET_REQUEST_LIMIT_PER_PHONE > 0:
        phone_count = db.scalar(
            select(func.count(PasswordResetToken.id)).where(
                PasswordResetToken.customer_id == customer.id,
                PasswordResetToken.delivery_channel == "phone_code",
                PasswordResetToken.created_at >= window_start,
            )
        ) or 0
        if phone_count >= settings.RESET_REQUEST_LIMIT_PER_PHONE:
            return True

    if request_ip and settings.RESET_REQUEST_LIMIT_PER_IP > 0:
        ip_count = db.scalar(
            select(func.count(PasswordResetToken.id)).where(
                PasswordResetToken.request_ip == request_ip[:80],
                PasswordResetToken.delivery_channel == "phone_code",
                PasswordResetToken.created_at >= window_start,
            )
        ) or 0
        if ip_count >= settings.RESET_REQUEST_LIMIT_PER_IP:
            return True

    if not customer and normalized:
        logger.info("Password reset requested for non-matching phone ending=%s", normalized[-4:])
    return False


def request_password_reset_code(
    db: Session,
    *,
    phone: str,
    request_ip: str | None = None,
) -> tuple[Customer | None, str | None, str]:
    customer = find_customer_by_recovery_phone(db, phone)
    if _has_recent_request_limit(db, customer=customer, phone=phone, request_ip=request_ip):
        logger.info(
            "Password reset request rate limited customer_id=%s ip_present=%s",
            getattr(customer, "id", None),
            bool(request_ip),
        )
        return None, None, "rate_limited"

    if not customer:
        return None, None, "not_found"

    code = issue_password_reset_code(db, customer=customer, request_ip=request_ip)
    return customer, code, "issued"


def verify_password_reset_code(
    db: Session,
    *,
    phone: str,
    code: str,
) -> str:
    customer = find_customer_by_recovery_phone(db, phone)
    if not customer:
        raise ValueError("invalid_or_expired_code")

    clean_code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(clean_code) != 6:
        raise ValueError("invalid_or_expired_code")

    now = utcnow_naive()
    candidate = db.scalar(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.customer_id == customer.id,
            PasswordResetToken.delivery_channel == "phone_code",
            PasswordResetToken.used_at.is_(None),
        )
        .order_by(PasswordResetToken.created_at.desc(), PasswordResetToken.id.desc())
    )
    if not candidate or candidate.expires_at < now:
        raise ValueError("invalid_or_expired_code")

    if int(candidate.attempt_count or 0) >= settings.RESET_CODE_MAX_ATTEMPTS:
        candidate.used_at = now
        db.add(candidate)
        raise ValueError("too_many_attempts")

    if hash_token(clean_code) != candidate.token_hash:
        candidate.attempt_count = int(candidate.attempt_count or 0) + 1
        if candidate.attempt_count >= settings.RESET_CODE_MAX_ATTEMPTS:
            candidate.used_at = now
        db.add(candidate)
        raise ValueError("invalid_or_expired_code")

    reset_token = generate_secure_token(24)
    candidate.verified_at = now
    candidate.reset_token_hash = hash_token(reset_token)
    candidate.expires_at = now + timedelta(minutes=settings.RESET_TOKEN_TTL_MINUTES)
    db.add(candidate)
    logger.info("Password reset code verified for customer_id=%s", customer.id)
    return reset_token


def get_valid_reset_token(db: Session, token: str) -> PasswordResetToken | None:
    token_hash = hash_token(token)
    candidate = db.scalar(
        select(PasswordResetToken).where(
            (PasswordResetToken.reset_token_hash == token_hash)
            | (
                (PasswordResetToken.reset_token_hash.is_(None))
                & (PasswordResetToken.delivery_channel == "manual_link")
                & (PasswordResetToken.token_hash == token_hash)
            )
        )
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
    customer.must_change_password = False
    reset_token.used_at = utcnow_naive()
    db.add(customer)
    db.add(reset_token)
    logger.info("Customer password reset completed for customer_id=%s", customer.id)
    return customer
