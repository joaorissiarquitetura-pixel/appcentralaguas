import os
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, func, extract, desc, text
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import time as _time
import json

from ..database import get_db
from ..models import Attendant, Customer, Product, Transaction, LoyaltyLedger, Alert, Redemption, TransactionItem
from ..auth import get_current_attendant_id, is_admin
from ..security import hash_password
from ..config import settings
from ..services.address import geocode_structured

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/admin")

# --- FUNÇÃO DE SEGURANÇA ---
def require_admin(request: Request, db: Session) -> Attendant | None:
    aid = get_current_attendant_id(request)
    if not aid:
        return None
    admin = db.scalar(select(Attendant).where(Attendant.id == int(aid)))
    if not admin or not is_admin(admin):
        return None
    return admin

# --- DASHBOARD / HOME ---
@router.get("", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    total_customers = db.scalar(select(func.count(Customer.id)))
    customers_with_purchases = db.scalar(select(func.count(Customer.id)).where(Customer.first_purchase_at.is_not(None)))
    total_tx = db.scalar(select(func.count(Transaction.id)))
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.resolved_at.is_(None)))

    products = db.execute(select(Product).order_by(Product.name)).scalars().all()
    attendants = db.execute(select(Attendant).order_by(Attendant.name)).scalars().all()

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
def create_or_update_product(request: Request, product_id: int = Form(0), name: str = Form(...), points_per_unit: int = Form(1), active: str = Form("off"), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    is_active = (active == "on")
    if product_id > 0:
        p = db.get(Product, product_id)
        if p: p.name, p.points_per_unit, p.active = name.strip(), int(points_per_unit), is_active
    else: db.add(Product(name=name.strip(), points_per_unit=int(points_per_unit), active=is_active))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

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
