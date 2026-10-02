from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..services.whatsapp_webhook import process_whatsapp_webhook

router = APIRouter(prefix="/webhooks/whatsapp", tags=["WhatsApp Webhook"])
logger = logging.getLogger(__name__)


@router.get("")
def verify_whatsapp_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    expected = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN.strip()

    if mode == "subscribe" and expected and token == expected and challenge:
        return PlainTextResponse(challenge)
    logger.warning("WhatsApp webhook verification failed mode=%s token_present=%s", mode, bool(token))
    return PlainTextResponse("forbidden", status_code=403)


@router.post("")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        logger.warning("WhatsApp webhook received invalid JSON")
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)

    try:
        stats = process_whatsapp_webhook(db, payload)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("WhatsApp webhook processing failed: %s", exc)
        return JSONResponse({"ok": False}, status_code=500)

    return JSONResponse({"ok": True, **stats})
