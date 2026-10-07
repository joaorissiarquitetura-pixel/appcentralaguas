from __future__ import annotations

import json
import hashlib
import hmac
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Customer, WhatsAppConversation, WhatsAppMessage, WhatsAppMessageStatus
from .whatsapp import normalize_brazilian_phone

logger = logging.getLogger(__name__)


def _timestamp_from_whatsapp(value: str | int | None) -> datetime:
    try:
        if value:
            return datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OSError):
        pass
    return datetime.utcnow()


def _customer_for_phone(db: Session, phone: str) -> Customer | None:
    normalized = normalize_brazilian_phone(phone)
    if not normalized:
        return None
    return db.scalar(select(Customer).where(Customer.phone == normalized))


def _message_text(message: dict) -> str:
    message_type = str(message.get("type") or "text")
    if message_type == "text":
        return str((message.get("text") or {}).get("body") or "")
    if message_type == "button":
        button = message.get("button") or {}
        return str(button.get("text") or button.get("payload") or "")
    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        button_reply = interactive.get("button_reply") or {}
        list_reply = interactive.get("list_reply") or {}
        return str(button_reply.get("title") or list_reply.get("title") or "")
    return ""


def get_or_create_whatsapp_conversation(db: Session, *, phone: str, customer: Customer | None) -> WhatsAppConversation:
    conversation = db.scalar(select(WhatsAppConversation).where(WhatsAppConversation.phone == phone))
    if conversation:
        if customer and not conversation.customer_id:
            conversation.customer_id = customer.id
            conversation.customer_name = customer.name
        return conversation

    conversation = WhatsAppConversation(
        phone=phone,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else None,
        status="open",
    )
    db.add(conversation)
    db.flush()
    return conversation


def verify_whatsapp_webhook_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def process_whatsapp_webhook(db: Session, payload: dict) -> dict[str, int]:
    stats = {"messages": 0, "statuses": 0, "duplicates": 0}
    entries = payload.get("entry") if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return stats

    for entry in entries:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for status in value.get("statuses") or []:
                if _store_status(db, status):
                    stats["statuses"] += 1
            contacts_by_wa_id = {
                str(contact.get("wa_id") or ""): contact
                for contact in value.get("contacts") or []
            }
            for message in value.get("messages") or []:
                result = _store_message(db, message, contacts_by_wa_id)
                if result == "stored":
                    stats["messages"] += 1
                elif result == "duplicate":
                    stats["duplicates"] += 1
    return stats


def _store_status(db: Session, status: dict) -> bool:
    wa_message_id = str(status.get("id") or "")
    status_value = str(status.get("status") or "")
    if not wa_message_id or not status_value:
        return False

    recipient_phone = normalize_brazilian_phone(status.get("recipient_id") or "") or str(status.get("recipient_id") or "")
    db.add(
        WhatsAppMessageStatus(
            wa_message_id=wa_message_id,
            recipient_phone=recipient_phone,
            status=status_value[:40],
            raw_payload=json.dumps(status, ensure_ascii=False),
            timestamp=_timestamp_from_whatsapp(status.get("timestamp")),
        )
    )
    message = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_message_id))
    if message:
        message.status = status_value[:40]
    return True


def _store_message(db: Session, message: dict, contacts_by_wa_id: dict[str, dict]) -> str:
    wa_message_id = str(message.get("id") or "")
    if wa_message_id and db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.wa_message_id == wa_message_id)):
        return "duplicate"

    from_phone = normalize_brazilian_phone(message.get("from") or "") or str(message.get("from") or "")
    if not from_phone:
        return "ignored"
    customer = _customer_for_phone(db, from_phone)
    contact = contacts_by_wa_id.get(str(message.get("from") or "")) or {}
    profile_name = ((contact.get("profile") or {}).get("name") or "").strip()
    conversation = get_or_create_whatsapp_conversation(db, phone=from_phone, customer=customer)
    if profile_name and not conversation.customer_name:
        conversation.customer_name = profile_name[:160]

    message_type = str(message.get("type") or "text")[:40]
    text = _message_text(message).strip()
    timestamp = _timestamp_from_whatsapp(message.get("timestamp"))
    lower_text = text.strip().lower()
    if lower_text in {"sair", "parar", "stop", "cancelar"}:
        conversation.opt_out = True

    db.add(
        WhatsAppMessage(
            conversation_id=conversation.id,
            customer_id=customer.id if customer else None,
            phone=from_phone,
            direction="inbound",
            wa_message_id=wa_message_id or None,
            message_type=message_type,
            text=text or None,
            raw_payload=json.dumps(message, ensure_ascii=False),
            timestamp=timestamp,
        )
    )
    conversation.last_message_at = timestamp
    conversation.last_inbound_at = timestamp
    conversation.updated_at = datetime.utcnow()
    conversation.unread_count = int(conversation.unread_count or 0) + 1
    conversation.status = "open"
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("Duplicate WhatsApp message ignored id=%s", wa_message_id)
        return "duplicate"
    return "stored"
