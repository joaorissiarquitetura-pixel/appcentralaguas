from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Customer, LoyaltyLedger
from ..services.integration import get_subscription_snapshot_for_customer, get_unified_offers
from ..services.loyalty import card_progress, cards_completed, points_balance
from ..services.whatsapp import build_whatsapp_redeem_link


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 6:
        return phone
    return phone[:-4].replace(phone[:-4], "*" * (len(phone) - 4)) + phone[-4:]


def build_customer_dashboard_context(*, request, db: Session, customer: Customer) -> dict:
    balance = points_balance(db, customer.id)
    progress = card_progress(balance)
    completed = cards_completed(balance)
    current_savings = completed * 10.00

    lifetime_points = db.scalar(
        select(func.sum(LoyaltyLedger.delta_points)).where(
            LoyaltyLedger.customer_id == customer.id,
            LoyaltyLedger.delta_points > 0,
        )
    ) or 0
    lifetime_completed_cards = int(lifetime_points // settings.CARD_TARGET_POINTS)
    total_savings = lifetime_completed_cards * 10.00

    redeem_link = None
    if balance >= settings.CARD_TARGET_POINTS:
        redeem_link = build_whatsapp_redeem_link(customer.name, customer.phone, completed)

    referral_link = str(request.base_url).rstrip("/") + f"/cadastrar?ref={customer.referral_code}"

    ledger = db.execute(
        select(LoyaltyLedger).where(LoyaltyLedger.customer_id == customer.id).order_by(LoyaltyLedger.created_at.desc()).limit(15)
    ).scalars().all()

    referrals = db.execute(
        select(Customer).where(Customer.referred_by_id == customer.id).order_by(Customer.created_at.desc()).limit(50)
    ).scalars().all()

    referral_rows = []
    for referral in referrals:
        status = "Fez o cadastro"
        if referral.first_purchase_at:
            status = "Fez a primeira compra"
        bonus = "Pendente"
        if referral.referral_bonus_awarded:
            bonus = f"Voce ganhou +{settings.REFERRAL_BONUS_POINTS}"
        referral_rows.append(
            {
                "name": referral.name,
                "phone_mask": mask_phone(referral.phone),
                "created_at": referral.created_at,
                "first_purchase_at": referral.first_purchase_at,
                "status": status,
                "bonus": bonus,
            }
        )

    subscription = get_subscription_snapshot_for_customer(customer)
    offers = get_unified_offers(customer, subscription)

    return {
        "business_name": settings.BUSINESS_NAME,
        "customer": customer,
        "balance": balance,
        "progress": progress,
        "target": settings.CARD_TARGET_POINTS,
        "completed": completed,
        "current_savings": current_savings,
        "total_savings": total_savings,
        "lifetime_completed_cards": lifetime_completed_cards,
        "redeem_link": redeem_link,
        "referral_link": referral_link,
        "double_weekday": settings.DOUBLE_POINTS_WEEKDAY,
        "ledger": ledger,
        "referral_rows": referral_rows,
        "ref_bonus": settings.REFERRAL_BONUS_POINTS,
        "subscription": subscription,
        "subscription_offers": offers,
        "feature_banners": settings.ENABLE_SIGNATURE_BANNERS,
    }
