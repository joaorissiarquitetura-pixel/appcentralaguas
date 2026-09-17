from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_customer_id
from ..config import settings
from ..database import get_db
from ..models import AppBanner, AppBannerEvent, AppDevice, AppNotification, AppNotificationEvent, AppPromotion, LocationAccessLog, PushSubscription
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


class FcmDiagnosticPayload(BaseModel):
    device_id: str
    status: str
    detail: str = ""
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


class DeviceEventPayload(BaseModel):
    device_id: str = ""


def _grj_app_status_url() -> str:
    orders_url = settings.CENTRAL_AGUAS_ORDERS_API_URL.strip()
    if orders_url.endswith("/orders"):
        return f"{orders_url}/app-status"
    return urllib.parse.urljoin(orders_url.rstrip("/") + "/", "app-status")


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


def _get_or_create_device(db: Session, device_id: str) -> AppDevice | None:
    normalized = (device_id or "").strip()
    if not normalized:
        return None
    device = db.scalar(select(AppDevice).where(AppDevice.device_id == normalized))
    if not device:
        device = AppDevice(device_id=normalized)
        db.add(device)
    return device


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


@router.get("/banners")
def app_banners(request: Request, device_id: str = "", db: Session = Depends(get_db)):
    customer_id = _current_customer_id(request)
    normalized_device_id = (device_id or "").strip()
    dismissed_banner_ids = set()
    if normalized_device_id:
        dismissed_banner_ids = {
            row[0]
            for row in db.execute(
                select(AppBannerEvent.banner_id).where(
                    AppBannerEvent.device_id == normalized_device_id,
                    AppBannerEvent.event_type.in_(("closed", "clicked")),
                )
            ).all()
        }
    query = select(AppBanner).where(AppBanner.active == True).order_by(AppBanner.display_order.asc(), AppBanner.created_at.desc())
    if customer_id:
        query = query.where(AppBanner.target.in_(("all", "customers")))
    else:
        query = query.where(AppBanner.target == "all")
    banners = [
        banner
        for banner in db.execute(query).scalars().all()
        if banner.id not in dismissed_banner_ids
    ]
    return {
        "ok": True,
        "banners": [
            {
                "id": banner.id,
                "title": banner.title,
                "body": banner.body or "",
                "image_url": banner.image_url,
                "link_url": banner.link_url or "",
            }
            for banner in banners[:1]
        ],
    }


@router.get("/promotions")
def app_promotions(request: Request, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    query = (
        select(AppPromotion)
        .where(AppPromotion.active == True)
        .order_by(AppPromotion.display_order.asc(), AppPromotion.created_at.desc())
    )
    promotions = [
        promotion
        for promotion in db.execute(query).scalars().all()
        if (not promotion.valid_from or promotion.valid_from <= now)
        and (not promotion.valid_until or promotion.valid_until >= now)
    ]
    return {
        "ok": True,
        "promotions": [
            {
                "id": promotion.id,
                "title": promotion.title,
                "description": promotion.description or "",
                "rule_type": promotion.rule_type,
                "rule_config": promotion.rule_config or "",
            }
            for promotion in promotions[:20]
        ],
    }


def _record_banner_event(db: Session, banner_id: int, payload: DeviceEventPayload, request: Request, event_type: str):
    banner = db.get(AppBanner, banner_id)
    if not banner:
        return {"ok": False, "error": "banner_not_found"}
    device_id = payload.device_id.strip()
    customer_id = _current_customer_id(request)
    if device_id:
        _get_or_create_device(db, device_id)
        existing = db.scalar(
            select(AppBannerEvent).where(
                AppBannerEvent.banner_id == banner_id,
                AppBannerEvent.device_id == device_id,
                AppBannerEvent.event_type == event_type,
            )
        )
        if existing:
            return {"ok": True, "duplicate": True}
    db.add(AppBannerEvent(banner_id=banner_id, device_id=device_id or None, customer_id=customer_id, event_type=event_type))
    if event_type == "seen":
        banner.seen_count = (banner.seen_count or 0) + 1
    elif event_type in {"closed", "clicked"}:
        banner.closed_count = (banner.closed_count or 0) + 1
    db.commit()
    return {"ok": True}


@router.post("/banners/{banner_id}/seen")
def mark_banner_seen(banner_id: int, payload: DeviceEventPayload, request: Request, db: Session = Depends(get_db)):
    return _record_banner_event(db, banner_id, payload, request, "seen")


@router.post("/banners/{banner_id}/closed")
def mark_banner_closed(banner_id: int, payload: DeviceEventPayload, request: Request, db: Session = Depends(get_db)):
    return _record_banner_event(db, banner_id, payload, request, "closed")


@router.post("/banners/{banner_id}/clicked")
def mark_banner_clicked(banner_id: int, payload: DeviceEventPayload, request: Request, db: Session = Depends(get_db)):
    return _record_banner_event(db, banner_id, payload, request, "clicked")


@router.post("/notifications/{notification_id}/opened")
def mark_notification_opened(notification_id: int, payload: DeviceEventPayload, request: Request, db: Session = Depends(get_db)):
    notification = db.get(AppNotification, notification_id)
    if not notification:
        return {"ok": False, "error": "notification_not_found"}
    device_id = payload.device_id.strip()
    customer_id = _current_customer_id(request)
    if device_id:
        _get_or_create_device(db, device_id)
        existing = db.scalar(
            select(AppNotificationEvent).where(
                AppNotificationEvent.notification_id == notification_id,
                AppNotificationEvent.device_id == device_id,
                AppNotificationEvent.event_type == "opened",
            )
        )
        if existing:
            return {"ok": True, "duplicate": True}
    db.add(
        AppNotificationEvent(
            notification_id=notification_id,
            device_id=device_id or None,
            customer_id=customer_id,
            event_type="opened",
        )
    )
    notification.opened_count = (notification.opened_count or 0) + 1
    db.commit()
    return {"ok": True}


@router.get("/orders/status")
def app_order_status(response: Response, client_order_ids: str = "", grj_order_ids: str = ""):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    references = [
        item.strip()
        for item in client_order_ids.replace(";", ",").split(",")
        if item.strip()
    ][:50]
    grj_ids = [
        item.strip()
        for item in grj_order_ids.replace(";", ",").split(",")
        if item.strip().isdigit()
    ][:50]
    if not references and not grj_ids:
        return {"ok": True, "orders": []}
    token = settings.CENTRAL_AGUAS_APP_TOKEN.strip()
    if not token:
        return {"ok": False, "error": "grj_token_missing", "orders": []}
    url = f"{_grj_app_status_url()}?{urllib.parse.urlencode({'client_order_ids': ','.join(references), 'grj_order_ids': ','.join(grj_ids)})}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "orders": []}
    return {"ok": payload.get("status") == "ok", "orders": payload.get("data") or []}


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


@router.post("/fcm-diagnostic")
def save_fcm_diagnostic(payload: FcmDiagnosticPayload, request: Request, db: Session = Depends(get_db)):
    device_id = payload.device_id.strip()
    if not device_id:
        return {"ok": False, "error": "device_id_required"}

    device = db.scalar(select(AppDevice).where(AppDevice.device_id == device_id))
    if not device:
        device = AppDevice(device_id=device_id)
        db.add(device)

    device.platform = payload.platform[:40]
    device.notification_permission = payload.status[:20]
    device.user_agent = f"{request.headers.get('user-agent', '')} | fcm={payload.detail[:240]}"
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
