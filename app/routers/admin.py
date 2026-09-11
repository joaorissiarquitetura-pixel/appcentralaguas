import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request, Form, Depends, File, UploadFile
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, func, extract, desc, text
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import time as _time
import json

from ..database import get_db
from ..models import AppDevice, AppNotification, Attendant, Coupon, Customer, LocationAccessLog, Product, PushSubscription, Transaction, LoyaltyLedger, Alert, Redemption, TransactionItem
from ..auth import get_current_attendant_id, is_admin
from ..security import hash_password
from ..config import settings
from ..services.address import geocode_structured
from ..services.push import fcm_configured, push_configured, send_notification_to_app_devices, send_notification_to_subscriptions

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/admin")

UPLOAD_DIR = Path("app/static/uploads/products")

# --- FUNÇÃO DE SEGURANÇA ---
def require_admin(request: Request, db: Session) -> Attendant | None:
    aid = get_current_attendant_id(request)
    if not aid:
        return None
    admin = db.scalar(select(Attendant).where(Attendant.id == int(aid)))
    if not admin or not is_admin(admin):
        return None
    return admin


def _parse_optional_float(value: str | float | None) -> float | None:
    if value is None:
        return None
    text_value = str(value).strip().replace(",", ".")
    if not text_value:
        return None
    return float(text_value)


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _coupon_available(coupon: Coupon, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if not coupon.active:
        return False
    if coupon.valid_from and coupon.valid_from > now:
        return False
    if coupon.valid_until and coupon.valid_until < now:
        return False
    return True


def _save_product_image(image_file: UploadFile | None) -> str | None:
    if not image_file or not image_file.filename:
        return None
    ext = Path(image_file.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.utcnow():%Y%m%d%H%M%S}_{uuid4().hex[:8]}{ext}"
    target = UPLOAD_DIR / filename
    with target.open("wb") as output:
        output.write(image_file.file.read())
    return f"/static/uploads/products/{filename}"

# --- DASHBOARD / HOME ---
@router.get("", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    total_customers = db.scalar(select(func.count(Customer.id)))
    customers_with_purchases = db.scalar(select(func.count(Customer.id)).where(Customer.first_purchase_at.is_not(None)))
    total_tx = db.scalar(select(func.count(Transaction.id)))
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.resolved_at.is_(None)))
    without_geo = db.scalar(select(func.count(Customer.id)).where(Customer.lat.is_(None)))
    top_customers = db.execute(select(Customer).order_by(Customer.points.desc()).limit(8)).scalars().all()

    products = db.execute(select(Product).order_by(Product.name)).scalars().all()
    attendants = db.execute(select(Attendant).order_by(Attendant.name)).scalars().all()
    open_shop_orders = 0
    subscriber_total = 0
    conversion_percent = int(((customers_with_purchases or 0) / total_customers) * 100) if total_customers else 0

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "admin": admin,
            "business_name": settings.BUSINESS_NAME,
            "total_customers": total_customers or 0,
            "customers_with_purchases": customers_with_purchases or 0,
            "total_tx": total_tx or 0,
            "open_alerts": open_alerts or 0,
            "open_shop_orders": open_shop_orders,
            "subscriber_total": subscriber_total,
            "conversion_percent": conversion_percent,
            "without_geo": without_geo or 0,
            "top_customers": top_customers,
            "target": settings.CARD_TARGET_POINTS,
            "double_weekday": settings.DOUBLE_POINTS_WEEKDAY,
            "ref_bonus": settings.REFERRAL_BONUS_POINTS,
            "products": products,
            "attendants": attendants
        }
    )

# --- LISTA DE CLIENTES ---
@router.get("/customers", response_class=HTMLResponse)
def list_customers(request: Request, q: str = "", db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    query = select(Customer).order_by(Customer.name.asc())
    if q:
        query = query.where(Customer.name.ilike(f"%{q}%") | Customer.phone.ilike(f"%{q}%"))
    all_customers = db.execute(query).scalars().all()
    linked_customers = sum(1 for c in all_customers if c.central_customer_code)

    current_month = datetime.now().month
    birthdays = db.execute(
        select(Customer)
        .where(extract('month', Customer.birth_date) == current_month)
        .order_by(extract('day', Customer.birth_date))
    ).scalars().all()

    ranking = db.execute(
        select(Customer)
        .order_by(Customer.points.desc())
        .limit(20)
    ).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin_customers.html",
        context={
            "customers": all_customers,
            "linked_customers": linked_customers,
            "unlinked_customers": len(all_customers) - linked_customers,
            "birthdays": birthdays,
            "ranking": ranking,
            "q": q,
            "business_name": settings.BUSINESS_NAME,
            "admin": admin
        }
    )

# --- MAPA DE CLIENTES ---
@router.get("/map", response_class=HTMLResponse)
def map_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    total = db.scalar(select(func.count(Customer.id)))
    with_coords = db.scalar(select(func.count(Customer.id)).where(Customer.lat.is_not(None)))
    customers_db = db.execute(select(Customer).where(Customer.lat.is_not(None))).scalars().all()
    
    customers_list = [{"name": c.name, "lat": c.lat, "lon": c.lon, "neighborhood": c.neighborhood, "city": c.city} for c in customers_db]
    customers_json = json.dumps(customers_list)

    return templates.TemplateResponse(
        request=request,
        name="admin_map.html",
        context={
            "business_name": settings.BUSINESS_NAME,
            "admin": admin,
            "total": int(total or 0),
            "with_coords": int(with_coords or 0),
            "missing": int((total or 0) - (with_coords or 0)),
            "customers_json": customers_json
        }
    )

# --- ALERTAS INTELIGENTES ---
@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    alerts_db = db.execute(
        select(Alert).where(Alert.resolved_at.is_(None)).order_by(Alert.created_at.desc()).limit(200)
    ).scalars().all()
    
    alerts_display = []
    for alert in alerts_db:
        last_txs = db.execute(
            select(Transaction.created_at).where(Transaction.customer_id == alert.customer_id).order_by(Transaction.created_at.desc()).limit(5)
        ).scalars().all()
        
        avg_days, last_date_str, next_date_str = 0, "N/A", "N/A"
        if last_txs:
            last_tx_date = last_txs[0]
            last_date_str = last_tx_date.strftime("%d/%m/%Y")
            if len(last_txs) >= 2:
                intervals = [max(1, (last_txs[i] - last_txs[i+1]).days) for i in range(len(last_txs)-1)]
                avg_days = int(sum(intervals) / len(intervals))
                next_date_str = (last_tx_date + timedelta(days=avg_days)).strftime("%d/%m/%Y")
        
        alerts_display.append({
            "customer": alert.customer,
            "avg": avg_days,
            "last_date": last_date_str,
            "next_date": next_date_str,
            "status": "critico" if alert.type == "overdue" else "aviso",
            "msg": "Atrasado!" if alert.type == "overdue" else "Próximo do fim"
        })

    return templates.TemplateResponse(
        request=request, 
        name="admin_alerts.html", 
        context={"admin": admin, "alerts": alerts_display}
    )

# --- ADMIN DA FRENTE DIGITAL ---

@router.get("/site", response_class=HTMLResponse)
def admin_site(
    request: Request,
    edit_product_id: int = 0,
    edit_coupon_id: int = 0,
    err: str = "",
    success: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    products = db.execute(select(Product).order_by(Product.display_order.asc(), Product.name.asc())).scalars().all()
    coupons = db.execute(select(Coupon).order_by(Coupon.display_order.asc(), Coupon.created_at.desc())).scalars().all()
    editing_product = db.get(Product, edit_product_id) if edit_product_id else None
    editing_coupon = db.get(Coupon, edit_coupon_id) if edit_coupon_id else None
    coupon_available_count = sum(1 for coupon in coupons if _coupon_available(coupon))
    device_count = db.scalar(select(func.count(AppDevice.id)))
    push_count = db.scalar(select(func.count(PushSubscription.id)).where(PushSubscription.active == True))
    latest_notifications = db.execute(select(AppNotification).order_by(AppNotification.created_at.desc()).limit(8)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin_site.html",
        context={
            "admin": admin,
            "business_name": settings.BUSINESS_NAME,
            "products": products,
            "coupons": coupons,
            "editing_product": editing_product,
            "editing_coupon": editing_coupon,
            "coupon_available_count": coupon_available_count,
            "device_count": device_count or 0,
            "push_count": push_count or 0,
            "push_configured": push_configured(),
            "fcm_configured": fcm_configured(),
            "latest_notifications": latest_notifications,
            "open_shop_orders": 0,
            "latest_shop_orders": [],
            "attendants": db.execute(select(Attendant).order_by(Attendant.name)).scalars().all(),
            "err": err,
            "success": success,
            "temp_password": "",
            "temp_email": "",
        },
    )


@router.get("/app", response_class=HTMLResponse)
def admin_app_backend(
    request: Request,
    err: str = "",
    success: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    since_24h = datetime.utcnow() - timedelta(hours=24)
    blocked_device_ids = {
        row[0]
        for row in db.execute(select(AppDevice.device_id).where(AppDevice.is_blocked == True)).all()
    }
    devices = db.execute(select(AppDevice).order_by(AppDevice.last_seen_at.desc()).limit(80)).scalars().all()
    subscriptions = db.execute(select(PushSubscription).order_by(PushSubscription.updated_at.desc()).limit(80)).scalars().all()
    location_logs = db.execute(select(LocationAccessLog).order_by(LocationAccessLog.created_at.desc()).limit(60)).scalars().all()
    latest_notifications = db.execute(select(AppNotification).order_by(AppNotification.created_at.desc()).limit(12)).scalars().all()

    push_active_count = sum(1 for subscription in subscriptions if subscription.active and subscription.device_id not in blocked_device_ids)
    location_allowed_count = db.scalar(select(func.count(LocationAccessLog.id)).where(LocationAccessLog.allowed == True)) or 0
    location_denied_count = db.scalar(select(func.count(LocationAccessLog.id)).where(LocationAccessLog.allowed == False)) or 0

    return templates.TemplateResponse(
        request=request,
        name="admin_app_backend.html",
        context={
            "admin": admin,
            "business_name": settings.BUSINESS_NAME,
            "devices": devices,
            "subscriptions": subscriptions,
            "location_logs": location_logs,
            "latest_notifications": latest_notifications,
            "device_count": db.scalar(select(func.count(AppDevice.id))) or 0,
            "active_24h_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.last_seen_at >= since_24h)) or 0,
            "blocked_device_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.is_blocked == True)) or 0,
            "fcm_device_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.fcm_token.is_not(None), AppDevice.is_blocked.is_not(True))) or 0,
            "push_active_count": push_active_count,
            "location_allowed_count": location_allowed_count,
            "location_denied_count": location_denied_count,
            "push_configured": push_configured(),
            "fcm_configured": fcm_configured(),
            "service_area": {
                "city": settings.SERVICE_AREA_CITY,
                "state": settings.SERVICE_AREA_STATE,
                "min_lat": settings.SERVICE_AREA_MIN_LAT,
                "max_lat": settings.SERVICE_AREA_MAX_LAT,
                "min_lon": settings.SERVICE_AREA_MIN_LON,
                "max_lon": settings.SERVICE_AREA_MAX_LON,
            },
            "err": err,
            "success": success,
        },
    )


@router.get("/app/status", response_class=JSONResponse)
def admin_app_status(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    since_24h = datetime.utcnow() - timedelta(hours=24)
    return {
        "ok": True,
        "push": {"web_push": push_configured(), "firebase_fcm": fcm_configured()},
        "devices": {
            "total": db.scalar(select(func.count(AppDevice.id))) or 0,
            "active_24h": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.last_seen_at >= since_24h)) or 0,
            "blocked": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.is_blocked == True)) or 0,
            "with_fcm": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.fcm_token.is_not(None), AppDevice.is_blocked.is_not(True))) or 0,
        },
        "location": {
            "allowed": db.scalar(select(func.count(LocationAccessLog.id)).where(LocationAccessLog.allowed == True)) or 0,
            "denied": db.scalar(select(func.count(LocationAccessLog.id)).where(LocationAccessLog.allowed == False)) or 0,
        },
    }


@router.post("/app/devices/{device_id}/toggle-block")
def toggle_app_device_block(
    device_id: int,
    request: Request,
    block_reason: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    device = db.get(AppDevice, device_id)
    if not device:
        return RedirectResponse("/admin/app?err=Dispositivo%20não%20encontrado", status_code=303)

    device.is_blocked = not bool(device.is_blocked)
    if device.is_blocked:
        device.block_reason = block_reason.strip()[:180] or "Bloqueado pelo administrador."
        device.blocked_at = datetime.utcnow()
        device.fcm_token = None
        for subscription in db.execute(select(PushSubscription).where(PushSubscription.device_id == device.device_id)).scalars().all():
            subscription.active = False
    else:
        device.block_reason = None
        device.blocked_at = None
    db.commit()
    message = "Dispositivo%20bloqueado" if device.is_blocked else "Dispositivo%20desbloqueado"
    return RedirectResponse(f"/admin/app?success={message}", status_code=303)


@router.post("/app/subscriptions/{subscription_id}/toggle")
def toggle_push_subscription(subscription_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    subscription = db.get(PushSubscription, subscription_id)
    if not subscription:
        return RedirectResponse("/admin/app?err=Inscrição%20push%20não%20encontrada", status_code=303)
    subscription.active = not bool(subscription.active)
    subscription.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/admin/app?success=Inscrição%20push%20atualizada", status_code=303)


@router.post("/coupons")
def create_or_update_coupon(
    request: Request,
    coupon_id: int = Form(0),
    code: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    discount_type: str = Form("fixed"),
    discount_value: str = Form("0"),
    min_order_value: str = Form(""),
    valid_from: str = Form(""),
    valid_until: str = Form(""),
    display_order: int = Form(0),
    active: str = Form("off"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    code_normalized = code.strip().upper()
    if not code_normalized:
        return RedirectResponse("/admin/site?err=Código%20obrigatório", status_code=303)

    existing = db.scalar(select(Coupon).where(Coupon.code == code_normalized, Coupon.id != coupon_id))
    if existing:
        return RedirectResponse("/admin/site?err=Código%20de%20cupom%20já%20existe", status_code=303)

    coupon = db.get(Coupon, coupon_id) if coupon_id else None
    if not coupon:
        coupon = Coupon(code=code_normalized, title=title.strip() or code_normalized)
        db.add(coupon)

    coupon.code = code_normalized
    coupon.title = title.strip() or code_normalized
    coupon.description = description.strip() or None
    coupon.discount_type = discount_type if discount_type in {"fixed", "percent"} else "fixed"
    coupon.discount_value = _parse_optional_float(discount_value) or 0
    coupon.min_order_value = _parse_optional_float(min_order_value)
    coupon.valid_from = _parse_optional_datetime(valid_from)
    coupon.valid_until = _parse_optional_datetime(valid_until)
    coupon.display_order = int(display_order or 0)
    coupon.active = active == "on"
    db.commit()

    return RedirectResponse("/admin/site?success=Cupom%20salvo", status_code=303)


@router.post("/coupons/{coupon_id}/toggle")
def toggle_coupon(coupon_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    coupon = db.get(Coupon, coupon_id)
    if coupon:
        coupon.active = not coupon.active
        db.commit()
    return RedirectResponse("/admin/site", status_code=303)


@router.post("/notifications/send")
def send_app_notification(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    target: str = Form("all"),
    url: str = Form("/app"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    notification = AppNotification(
        title=title.strip()[:120],
        body=body.strip(),
        target=target if target in {"all", "customers"} else "all",
        url=url.strip() or "/app",
        status="queued",
        created_by_attendant_id=admin.id,
    )
    db.add(notification)
    db.commit()

    query = select(PushSubscription).where(PushSubscription.active == True)
    if notification.target == "customers":
        query = query.where(PushSubscription.customer_id.is_not(None))
    blocked_device_ids = {
        row[0]
        for row in db.execute(select(AppDevice.device_id).where(AppDevice.is_blocked == True)).all()
    }
    subscriptions = [
        subscription
        for subscription in db.execute(query).scalars().all()
        if subscription.device_id not in blocked_device_ids
    ]
    send_notification_to_subscriptions(db, notification, subscriptions)

    device_query = select(AppDevice).where(AppDevice.fcm_token.is_not(None), AppDevice.is_blocked.is_not(True))
    if notification.target == "customers":
        device_query = device_query.where(AppDevice.customer_id.is_not(None))
    devices = db.execute(device_query).scalars().all()
    send_notification_to_app_devices(db, notification, devices)

    if not push_configured() and not fcm_configured():
        return RedirectResponse("/admin/site?success=Notificação%20registrada.%20Configure%20Firebase%20ou%20VAPID%20para%20envio%20push.", status_code=303)
    return RedirectResponse("/admin/site?success=Notificação%20enviada", status_code=303)


# --- ROTAS RESTANTES (LOGICA SEM TEMPLATE) ---

@router.post("/customers/{customer_id}/reset_password")
def reset_customer_password(customer_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    customer = db.get(Customer, customer_id)
    if customer:
        new_password = "0000"
        customer.pin_hash = hash_password(new_password)
        customer.must_change_password = True
        db.commit()
    return RedirectResponse("/admin/customers", status_code=303)

@router.post("/customers/{customer_id}/central_link")
def update_customer_central_link(
    customer_id: int,
    request: Request,
    central_customer_code: str = Form(""),
    clear: str = Form(""),
    db: Session = Depends(get_db)
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    customer = db.get(Customer, customer_id)
    if customer:
        code = central_customer_code.strip()
        if clear == "1" or not code:
            customer.central_customer_code = None
            customer.central_linked_at = None
        else:
            customer.central_customer_code = code
            customer.central_linked_at = datetime.utcnow()
        db.commit()

    return RedirectResponse("/admin/customers", status_code=303)

@router.post("/customers/{customer_id}/delete")
def delete_customer(customer_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    customer = db.get(Customer, customer_id)
    if customer:
        try:
            db.execute(text(f"DELETE FROM loyalty_ledger WHERE customer_id = {customer_id}"))
            db.execute(text(f"DELETE FROM redemptions WHERE customer_id = {customer_id}"))
            db.execute(text(f"DELETE FROM transaction_items WHERE transaction_id IN (SELECT id FROM transactions WHERE customer_id = {customer_id})"))
            db.execute(text(f"DELETE FROM transactions WHERE customer_id = {customer_id}"))
            db.execute(text(f"DELETE FROM alerts WHERE customer_id = {customer_id}"))
            db.delete(customer)
            db.commit()
        except Exception: db.rollback()
    return RedirectResponse("/admin/customers", status_code=303)

@router.post("/products")
def create_or_update_product(
    request: Request,
    product_id: int = Form(0),
    name: str = Form(...),
    description: str = Form(""),
    promo_badge: str = Form(""),
    pickup_price: str = Form(""),
    delivery_price: str = Form(""),
    promo_pickup_price: str = Form(""),
    promo_delivery_price: str = Form(""),
    stock_status: str = Form("disponivel"),
    display_order: int = Form(0),
    image_url: str = Form(""),
    points_per_unit: int = Form(1),
    featured_on_home: str = Form("off"),
    active: str = Form("off"),
    image_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    is_active = (active == "on")
    if product_id > 0:
        p = db.get(Product, product_id)
        if not p:
            return RedirectResponse("/admin/site?err=Produto%20não%20encontrado", status_code=303)
    else:
        p = Product(name=name.strip(), points_per_unit=int(points_per_unit), active=is_active)
        db.add(p)

    uploaded_url = _save_product_image(image_file)
    p.name = name.strip()
    p.description = description.strip() or None
    p.promo_badge = promo_badge.strip() or None
    p.pickup_price = _parse_optional_float(pickup_price)
    p.delivery_price = _parse_optional_float(delivery_price)
    p.promo_pickup_price = _parse_optional_float(promo_pickup_price)
    p.promo_delivery_price = _parse_optional_float(promo_delivery_price)
    p.stock_status = stock_status
    p.display_order = int(display_order or 0)
    p.image_url = uploaded_url or image_url.strip() or None
    p.points_per_unit = int(points_per_unit)
    p.featured_on_home = featured_on_home == "on"
    p.active = is_active
    db.commit()
    return RedirectResponse("/admin/site?success=Produto%20salvo", status_code=303)

@router.post("/attendants")
def create_attendant(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form("attendant"), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    email_n = email.strip().lower()
    if db.scalar(select(Attendant.id).where(Attendant.email == email_n)): return RedirectResponse("/admin?err=Email%20já%20existe", status_code=303)
    db.add(Attendant(name=name.strip(), email=email_n, password_hash=hash_password(password), role=role, is_active=True))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@router.post("/map/geocode")
def geocode_pending(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    pending = db.execute(select(Customer).where(Customer.lat.is_(None), Customer.street.is_not(None))).scalars().all()
    for c in pending:
        rua = c.street if c.street.lower().startswith(('rua', 'av', 'alameda')) else f"Rua {c.street}"
        resultado = geocode_structured(street=rua, city="Votuporanga", cep=c.cep)
        if resultado:
            c.lat, c.lon = resultado
            db.commit()
        _time.sleep(1.2)
    return RedirectResponse("/admin/map", status_code=303)

@router.post("/alerts/generate")
def generate_alerts_action(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    customers = db.execute(select(Customer)).scalars().all()
    for c in customers:
        last_txs = db.execute(select(Transaction).where(Transaction.customer_id == c.id).order_by(Transaction.created_at.desc()).limit(5)).scalars().all()
        if len(last_txs) < 2: continue
        intervals = [max(1, (last_txs[i].created_at - last_txs[i+1].created_at).days) for i in range(len(last_txs)-1)]
        avg_days = sum(intervals) / len(intervals)
        days_since = (datetime.utcnow() - last_txs[0].created_at).days
        threshold = avg_days + max(2, avg_days * 0.3)
        if days_since > threshold:
            if not db.scalar(select(Alert).where(Alert.customer_id == c.id, Alert.type == 'overdue', Alert.resolved_at.is_(None))):
                db.add(Alert(customer_id=c.id, type='overdue', severity='warn', message=f"Atrasado! {days_since} dias.", created_at=datetime.utcnow()))
    db.commit()
    return RedirectResponse("/admin/alerts", status_code=303)

@router.post("/maintenance/sync_points")
def sync_all_points(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    db.execute(text("UPDATE customers SET points = (SELECT COALESCE(SUM(delta_points), 0) FROM loyalty_ledger WHERE customer_id = customers.id)"))
    db.commit()
    return RedirectResponse("/admin/customers", status_code=303)

@router.get("/customers/{customer_id}/history", response_class=JSONResponse)
def get_customer_history(customer_id: int, request: Request, db: Session = Depends(get_db)):
    aid = request.session.get("attendant_id") 
    if not aid: return JSONResponse({"error": "Sessão expirada"}, status_code=401)
    admin = db.get(Attendant, int(aid))
    if not admin or admin.role != "admin": return JSONResponse({"error": "Acesso negado"}, status_code=403)
    customer = db.get(Customer, customer_id)
    if not customer: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    ledger = db.execute(select(LoyaltyLedger).where(LoyaltyLedger.customer_id == customer_id).order_by(LoyaltyLedger.created_at.desc()).limit(20)).scalars().all()
    history = [{"date": i.created_at.strftime("%d/%m/%Y %H:%M"), "points": f"+{i.delta_points}" if i.delta_points > 0 else str(i.delta_points), "reason": i.reason} for i in ledger]
    return {"name": customer.name, "total_points": customer.points or 0, "history": history}
