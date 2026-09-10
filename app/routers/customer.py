from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_customer_id
from ..database import get_db
from ..models import Customer
from ..services.customer_portal import build_customer_dashboard_context
from ..services.qr import qr_png_response

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


def render_customer_dashboard(request: Request, db: Session, birth_date_error: str = ""):
    cid = get_current_customer_id(request)
    if not cid:
        return RedirectResponse("/login", status_code=303)

    customer = db.scalar(select(Customer).where(Customer.id == int(cid)))
    if not customer:
        return RedirectResponse("/logout", status_code=303)
    if getattr(customer, "must_change_password", False):
        return RedirectResponse("/alterar-senha-obrigatoria", status_code=303)

    context = build_customer_dashboard_context(request=request, db=db, customer=customer)
    context["birth_date_error"] = bool(birth_date_error)
    context["hide_chrome"] = True
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context,
    )


@router.get("/meu-cartao", response_class=HTMLResponse)
def my_card(request: Request, birth_date_error: str = "", db: Session = Depends(get_db)):
    return render_customer_dashboard(request, db, birth_date_error=birth_date_error)


@router.get("/cliente", response_class=HTMLResponse)
def cliente_dashboard(request: Request, birth_date_error: str = "", db: Session = Depends(get_db)):
    return render_customer_dashboard(request, db, birth_date_error=birth_date_error)


@router.post("/meu-cartao/data-nascimento")
def update_birth_date(request: Request, birth_date: str = Form(...), db: Session = Depends(get_db)):
    cid = get_current_customer_id(request)
    if not cid:
        return RedirectResponse("/login", status_code=303)

    customer = db.scalar(select(Customer).where(Customer.id == int(cid)))
    if not customer:
        return RedirectResponse("/logout", status_code=303)

    try:
        customer.birth_date = date.fromisoformat(birth_date)
    except ValueError:
        return RedirectResponse("/meu-cartao?birth_date_error=1", status_code=303)

    db.commit()
    return RedirectResponse("/meu-cartao", status_code=303)


@router.get("/qr", response_class=HTMLResponse)
def generate_my_qr(request: Request, db: Session = Depends(get_db)):
    cid = get_current_customer_id(request)
    if not cid:
        return RedirectResponse("/login", status_code=303)
    customer = db.scalar(select(Customer).where(Customer.id == int(cid)))
    if not customer:
        return RedirectResponse("/logout", status_code=303)
    return qr_png_response(customer.card_token)
