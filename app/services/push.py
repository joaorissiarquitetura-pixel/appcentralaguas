from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from ..config import settings
from ..models import AppDevice, AppNotification, PushSubscription

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:
    firebase_admin = None
    credentials = None
    messaging = None


def push_configured() -> bool:
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)


def fcm_configured() -> bool:
    return bool(firebase_admin and messaging and (settings.FIREBASE_SERVICE_ACCOUNT_JSON or settings.FIREBASE_SERVICE_ACCOUNT_FILE))


def ensure_firebase_app() -> bool:
    if not firebase_admin or not credentials:
        return False
    if firebase_admin._apps:
        return True
    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        service_account = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        firebase_admin.initialize_app(credentials.Certificate(service_account))
        return True
    if settings.FIREBASE_SERVICE_ACCOUNT_FILE:
        firebase_admin.initialize_app(credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_FILE))
        return True
    return False


def vapid_private_key() -> str:
    return settings.VAPID_PRIVATE_KEY.replace("\\n", "\n")


def send_web_push(subscription: PushSubscription, title: str, body: str, url: str = "/app") -> bool:
    if not push_configured():
        return False
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return False

    payload = json.dumps(
        {
            "title": title,
            "body": body,
            "url": url or "/app",
            "icon": "/static/icons/icon-192.png",
        }
    )
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=payload,
            vapid_private_key=vapid_private_key(),
            vapid_claims={"sub": settings.VAPID_SUBJECT},
        )
        return True
    except WebPushException:
        return False


def send_fcm(device: AppDevice, title: str, body: str, url: str = "/app") -> bool:
    if not device.fcm_token or not ensure_firebase_app() or not messaging:
        return False
    try:
        message = messaging.Message(
            token=device.fcm_token,
            notification=messaging.Notification(title=title, body=body),
            data={"url": url or "/app"},
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="central_aguas_alerts",
                    icon="ic_launcher",
                ),
            ),
        )
        messaging.send(message)
        return True
    except Exception:
        return False


def send_notification_to_subscriptions(
    db: Session,
    notification: AppNotification,
    subscriptions: Iterable[PushSubscription],
) -> AppNotification:
    sent = 0
    failed = 0
    for subscription in subscriptions:
        ok = send_web_push(subscription, notification.title, notification.body, notification.url or "/app")
        if ok:
            sent += 1
            subscription.last_sent_at = datetime.utcnow()
            subscription.fail_count = 0
        else:
            failed += 1
            subscription.fail_count = (subscription.fail_count or 0) + 1
            if subscription.fail_count >= 5:
                subscription.active = False
    notification.sent_count = sent
    notification.failed_count = failed
    notification.status = "sent" if sent else "queued_without_push_config" if not push_configured() else "failed"
    notification.sent_at = datetime.utcnow()
    db.commit()
    return notification


def send_notification_to_app_devices(
    db: Session,
    notification: AppNotification,
    devices: Iterable[AppDevice],
) -> AppNotification:
    sent = 0
    failed = 0
    for device in devices:
        ok = send_fcm(device, notification.title, notification.body, notification.url or "/app")
        if ok:
            sent += 1
            device.last_seen_at = datetime.utcnow()
        else:
            failed += 1
    notification.sent_count = (notification.sent_count or 0) + sent
    notification.failed_count = (notification.failed_count or 0) + failed
    if sent:
        notification.status = "sent"
    elif not fcm_configured() and notification.status == "queued":
        notification.status = "queued_without_fcm_config"
    elif notification.status == "queued":
        notification.status = "failed"
    notification.sent_at = datetime.utcnow()
    db.commit()
    return notification
