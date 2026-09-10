import os
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_attendant_id, is_admin, login_attendant, logout_attendant
from ..config import settings
from ..database import get_db
from ..models import Attendant, Customer, LoyaltyLedger, Product, Redemption, Transaction, TransactionItem
from ..security import verify_password
from ..services.loyalty import award_transaction_points, handle_first_purchase_and_referral, points_balance

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("", response_class=HTMLResponse)
def attendant_home(
    request: Request,
    q: str | None = None,
    customer_id: int | None = None,
    err: str | None = None,
    success: str | None = None,
    db: Session = Depends(get_db),
):
    aid = get_current_attendant_id(request)
    if not aid:
        return RedirectResponse("/atendente/login", status_code=303)

    attendant = db.scalar(select(Attendant).where(Attendant.id == int(aid)))
    if not attendant or not attendant.is_active:
        logout_attendant(request)
        return RedirectResponse("/atendente/login", status_code=303)

    customers = []
    selected_customer = None
    selected_balance = 0

    if q:
        qq = q.strip()
        q_digits = "".join(ch for ch in qq if ch.isdigit())

        conds = []
        if q_digits:
            conds.append(Customer.phone.contains(q_digits))
        conds.append(Customer.name.ilike(f"%{qq}%"))

        customers = db.execute(
            select(Customer)
            .where(or_(*conds))
            .order_by(Customer.name.asc())
            .limit(20)
        ).scalars().all()

    if customer_id:
        selected_customer = db.get(Customer, int(customer_id))
        if selected_customer:
            selected_balance = points_balance(db, selected_customer.id)

    products = db.execute(select(Product).where(Product.active == True).order_by(Product.name.asc())).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="attendant_panel.html",
        context={
            "business_name": settings.BUSINESS_NAME,
            "attendant": attendant,
            "customers": customers,
            "success_message": success,
            "products": products,
            "q": q or "",
            "target": settings.CARD_TARGET_POINTS,
            "is_admin": is_admin(attendant),
            "selected_customer": selected_customer,
            "selected_balance": selected_balance,
            "err": err,
        },
    )


@router.get("/login", response_class=HTMLResponse)
def attendant_login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="attendant_login.html",
        context={
            "business_name": settings.BUSINESS_NAME,
        },
    )


@router.post("/login", response_class=HTMLResponse)
def attendant_login_action(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    attendant = db.scalar(select(Attendant).where(Attendant.email == email.strip().lower()))

    if not attendant or not attendant.is_active or not verify_password(password, attendant.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="attendant_login.html",
            context={
                "business_name": settings.BUSINESS_NAME,
                "error": "Credenciais inválidas.",
            },
            status_code=400,
        )

    login_attendant(request, attendant.id)
    after = request.session.pop("after_login", None)
    return RedirectResponse(after or "/atendente", status_code=303)


@router.get("/logout")
def attendant_logout(request: Request):
    logout_attendant(request)
    return RedirectResponse("/atendente/login", status_code=303)


@router.post("/lancar")
def launch_purchase(
    request: Request,
    customer_id: int = Form(...),
    product_id: int = Form(...),
    qty: int = Form(1),
    channel: str = Form("entrega"),
    db: Session = Depends(get_db),
):
    aid = get_current_attendant_id(request)
    if not aid:
        return RedirectResponse("/atendente/login", status_code=303)

    customer = db.get(Customer, customer_id)
    product = db.get(Product, product_id)

    if not customer or not product:
        return RedirectResponse("/atendente?err=Erro+ao+identificar+cliente+ou+produto", status_code=303)

    now = datetime.utcnow()
    tx = Transaction(customer_id=customer.id, attendant_id=int(aid), channel=channel, created_at=now)
    db.add(tx)
    db.flush()

    quantity = max(1, int(qty))
    item = TransactionItem(transaction_id=tx.id, product_id=product.id, qty=quantity)
    db.add(item)

    award_transaction_points(db, tx, quantity_purchased=quantity)
    handle_first_purchase_and_referral(db, customer, now)

    db.commit()
    return RedirectResponse(f"/atendente?customer_id={customer.id}&success=Venda lançada!", status_code=303)


@router.post("/resgatar")
def redeem_points(
    request: Request,
    customer_id: int = Form(...),
    cards: int = Form(1),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    aid = get_current_attendant_id(request)
    if not aid:
        return RedirectResponse("/atendente/login", status_code=303)

    customer = db.get(Customer, customer_id)
    if not customer:
        return RedirectResponse("/atendente?err=Cliente+nao+encontrado", status_code=303)

    points_needed = max(1, int(cards)) * settings.CARD_TARGET_POINTS
    current_balance = points_balance(db, customer.id)

    if current_balance < points_needed:
        return RedirectResponse(f"/atendente?customer_id={customer.id}&err=Saldo+insuficiente", status_code=303)

    redemption = Redemption(
        customer_id=customer.id,
        attendant_id=int(aid),
        points_spent=points_needed,
        notes=notes.strip() or None,
        created_at=datetime.utcnow(),
    )
    db.add(redemption)
    db.flush()

    db.add(
        LoyaltyLedger(
            customer_id=customer.id,
            redemption_id=redemption.id,
            delta_points=-points_needed,
            reason=f"Resgate de Bônus ({int(cards)} cartões)",
        )
    )

    db.commit()
    return RedirectResponse(f"/atendente?customer_id={customer.id}&success=Resgate realizado com sucesso!", status_code=303)
