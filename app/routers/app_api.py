from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_customer_id
from ..config import settings
from ..database import get_db
from ..models import AppDevice, LocationAccessLog, PushSubscription
from ..services.app_access import check_service_area
from ..services.push import push_configured

router = APIRouter(prefix="/api/app", tags=["App"])


class DeviceRegisterPayload(BaseModel):
    device_id: str
    platform: str = "web"
    app_version: str = ""
    notification_permission: str = ""
    location_permission: str = ""


class PushSubscriptionPayload(BaseModel):
    device_id: str
    endpoint: str
    p256dh: str
    auth: str


class FcmTokenPayload(BaseModel):
    device_id: str
    token: str
    notification_permission: str = "granted"
    platform: str = "android"


class LocationCheckPayload(BaseModel):
    device_id: str = ""
    lat: float | None = None
    lon: float | None = None
    accuracy: float | None = None
    permission_state: str = ""
    source: str = "browser"
    city: str = ""
    state: str = ""


def _current_customer_id(request: Request) -> int | None:
    cid = get_current_customer_id(request)
    return int(cid) if cid else None


def _blocked_response(device: AppDevice | None):
    if device and device.is_blocked:
        return {
            "ok": False,
            "blocked": True,
            "reason": device.block_reason or "Acesso bloqueado pelo administrador.",
        }
    return None


@router.get("/bootstrap")
def app_bootstrap():
    return {
        "push": {
            "configured": push_configured(),
            "public_key": settings.VAPID_PUBLIC_KEY,
        },
        "service_area": {
            "city": settings.SERVICE_AREA_CITY,
            "state": settings.SERVICE_AREA_STATE,
            "bounds": {
                "min_lat": settings.SERVICE_AREA_MIN_LAT,
                "max_lat": settings.SERVICE_AREA_MAX_LAT,
                "min_lon": settings.SERVICE_AREA_MIN_LON,
                "max_lon": settings.SERVICE_AREA_MAX_LON,
            },
        },
    }


@router.post("/device")
def register_device(payload: DeviceRegisterPayload, request: Request, db: Session = Depends(get_db)):
    device_id = payload.device_id.strip()
    if not device_id:
        return {"ok": False, "error": "device_id_required"}

    device = db.scalar(select(AppDevice).where(AppDevice.device_id == device_id))
    if not device:
        device = AppDevice(device_id=device_id)
        db.add(device)
    blocked = _blocked_response(device)
    if blocked:
        device.last_seen_at = datetime.utcnow()
        db.commit()
        return blocked

    device.customer_id = _current_customer_id(request)
    device.platform = payload.platform[:40]
    device.app_version = payload.app_version[:40] or None
    device.notification_permission = payload.notification_permission[:20] or None
    device.location_permission = payload.location_permission[:20] or None
    device.user_agent = request.headers.get("user-agent", "")
    device.last_seen_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "device_id": device.device_id, "blocked": False}


@router.post("/push-subscription")
def save_push_subscription(payload: PushSubscriptionPayload, request: Request, db: Session = Depends(get_db)):
    if not payload.device_id.strip() or not payload.endpoint.strip():
        return {"ok": False, "error": "invalid_subscription"}
    device = db.scalar(select(AppDevice).where(AppDevice.device_id == payload.device_id.strip()))
    blocked = _blocked_response(device)
    if blocked:
        return blocked

    subscription = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    if not subscription:
        subscription = PushSubscription(
            device_id=payload.device_id.strip(),
            endpoint=payload.endpoint.strip(),
            p256dh=payload.p256dh,
            auth=payload.auth,
        )
        db.add(subscription)

    subscription.device_id = payload.device_id.strip()
    subscription.customer_id = _current_customer_id(request)
    subscription.p256dh = payload.p256dh
    subscription.auth = payload.auth
    subscription.user_agent = request.headers.get("user-agent", "")
    subscription.active = True
    subscription.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "push_configured": push_configured()}


@router.post("/fcm-token")
def save_fcm_token(payload: FcmTokenPayload, request: Request, db: Session = Depends(get_db)):
    device_id = payload.device_id.strip()
    token = payload.token.strip()
    if not device_id or not token:
        return {"ok": False, "error": "invalid_fcm_token"}

    device = db.scalar(select(AppDevice).where(AppDevice.device_id == device_id))
    if not device:
        device = AppDevice(device_id=device_id)
        db.add(device)
    blocked = _blocked_response(device)
    if blocked:
        return blocked

    device.customer_id = _current_customer_id(request)
    device.platform = payload.platform[:40]
    device.notification_permission = payload.notification_permission[:20]
    device.fcm_token = token
    device.fcm_token_updated_at = datetime.utcnow()
    device.user_agent = request.headers.get("user-agent", "")
    device.last_seen_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/location/check")
def check_location(payload: LocationCheckPayload, request: Request, db: Session = Depends(get_db)):
    result = check_service_area(payload.lat, payload.lon, payload.city, payload.state)
    customer_id = _current_customer_id(request)
    device = None
    device_id = payload.device_id.strip()
    if device_id:
        device = db.scalar(select(AppDevice).where(AppDevice.device_id == device_id))
    blocked = _blocked_response(device)

    db.add(
        LocationAccessLog(
            device_id=device_id or None,
            customer_id=customer_id,
            lat=payload.lat,
            lon=payload.lon,
            accuracy=payload.accuracy,
            permission_state=payload.permission_state[:20] or None,
            source=payload.source[:40] or "browser",
            allowed=False if blocked else result.allowed,
            reason=blocked["reason"] if blocked else result.reason,
        )
    )

    if not blocked and customer_id and payload.lat is not None and payload.lon is not None:
        from ..models import Customer

        customer = db.get(Customer, customer_id)
        if customer:
            customer.lat = payload.lat
            customer.lon = payload.lon

    if device:
        device.location_permission = payload.permission_state[:20] or None
        device.last_seen_at = datetime.utcnow()

    db.commit()
    if blocked:
        return blocked
    return {"ok": True, "allowed": result.allowed, "reason": result.reason}
