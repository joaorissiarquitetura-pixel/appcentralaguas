from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.error
import urllib.request

from ..config import settings

logger = logging.getLogger(__name__)


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def whatsapp_cloud_configured() -> bool:
    return bool(
        settings.WHATSAPP_CLOUD_ACCESS_TOKEN.strip()
        and settings.WHATSAPP_CLOUD_PHONE_NUMBER_ID.strip()
        and settings.WHATSAPP_RESET_TEMPLATE_NAME.strip()
    )


def build_password_reset_message(reset_link: str) -> str:
    main_number = _digits_only(settings.BUSINESS_WHATSAPP_NUMBER)
    help_line = f"https://wa.me/{main_number}" if main_number and "X" not in main_number else "WhatsApp principal da Central Águas"
    return (
        "Central Águas: recebemos uma solicitação para redefinir sua senha do app.\n\n"
        f"Acesse este link para criar uma nova senha: {reset_link}\n\n"
        f"Este link expira em {settings.RESET_TOKEN_TTL_MINUTES} minutos. "
        f"Este número é automático; para atendimento ou pedidos, fale pelo {help_line}."
    )


def build_whatsapp_redeem_link(customer_name: str, customer_phone: str, completed_cards: int) -> str:
    number = _digits_only(settings.BUSINESS_WHATSAPP_NUMBER)
    msg = (
        f"Olá! Sou {customer_name} (tel: {customer_phone}). "
        f"Completei {completed_cards} cartão(ões) no {settings.BUSINESS_NAME} "
        "e gostaria de resgatar meus créditos. 😊"
    )
    return f"https://wa.me/{number}?text={urllib.parse.quote(msg)}"


def send_password_reset_whatsapp(*, to_phone: str, reset_link: str) -> tuple[bool, str]:
    if not whatsapp_cloud_configured():
        return False, "whatsapp_cloud_not_configured"

    phone = _digits_only(to_phone)
    if not phone.startswith("55"):
        phone = f"55{phone}"
    if len(phone) < 12:
        return False, "invalid_phone"

    phone_number_id = settings.WHATSAPP_CLOUD_PHONE_NUMBER_ID.strip()
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_RESET_TEMPLATE_NAME.strip(),
            "language": {"code": settings.WHATSAPP_RESET_TEMPLATE_LANGUAGE.strip() or "pt_BR"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": reset_link},
                        {"type": "text", "text": str(settings.RESET_TOKEN_TTL_MINUTES)},
                    ],
                }
            ],
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.WHATSAPP_CLOUD_ACCESS_TOKEN.strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status >= 400:
                return False, f"http_{response.status}"
        return True, "sent"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.warning("WhatsApp password reset send failed HTTP %s: %s", exc.code, body)
        return False, f"http_{exc.code}"
    except Exception as exc:
        logger.warning("WhatsApp password reset send failed: %s", exc)
        return False, "request_failed"
