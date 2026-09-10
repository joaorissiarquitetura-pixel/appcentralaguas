import json
import ssl
import urllib.parse
import urllib.request
from datetime import date
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_customer_id, login_customer, logout_customer
from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Customer, Product
from ..security import gen_card_token, gen_referral_code, hash_password, verify_password
from ..services.grj_catalog import GRJCatalogProduct, GRJCatalogUnavailable, fetch_grj_products, product_to_public_dict
from ..services.loyalty import card_progress, cards_completed, points_balance

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


def _chrome_hidden_context(**context):
    return {
        "business_name": settings.BUSINESS_NAME,
        "hide_chrome": True,
        **context,
    }


def normalize_phone(phone: str) -> str:
    """Remove tudo que nao for numero do telefone."""
    return "".join(ch for ch in phone if ch.isdigit())


def _money_reward() -> str:
    return "R$ 10,00"


def _product_slug(product: Product) -> str:
    return _slug_from_text(product.name) or f"produto-{product.id}"


def _slug_from_text(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _product_image_url(product: Product) -> str | None:
    if product.image_url:
        return product.image_url

    return _catalog_image_for_name(product.name)


def _catalog_image_for_name(name: str) -> str | None:
    name_lower = name.lower()
    if "20" in name_lower:
        return "/static/img/20.png"
    if "10" in name_lower:
        return "/static/img/10.png"
    if "510" in name_lower or "500" in name_lower or "fardo" in name_lower:
        return "/static/img/510.png"
    return None


def _shop_offer_from_product(product: Product) -> SimpleNamespace:
    pickup_price = product.promo_pickup_price or product.pickup_price or 0
    delivery_price = product.promo_delivery_price or product.delivery_price or pickup_price
    return SimpleNamespace(
        product_id=product.id,
        slug=_product_slug(product),
        name=product.name,
        description=product.description or "Água mineral Central Águas.",
        pickup_price=pickup_price,
        delivery_price=delivery_price,
        badge=product.promo_badge or "Pedido rápido",
        image_url=_product_image_url(product),
        stock_status=product.stock_status or "disponivel",
        rating_count=0,
        rating_average=0,
        customer_rating=None,
    )


def _local_product_to_public_dict(product: Product) -> dict[str, object]:
    pickup_price = product.promo_pickup_price or product.pickup_price or 0
    delivery_price = product.promo_delivery_price or product.delivery_price or pickup_price
    return {
        "external_id": str(product.id),
        "name": product.name,
        "description": product.description or "Água mineral Central Águas.",
        "pickup_price": pickup_price,
        "delivery_price": delivery_price,
        "stock_quantity": None,
        "stock_status": product.stock_status or "disponivel",
        "image_url": _product_image_url(product),
        "active": bool(product.active),
        "source": "local",
    }


def _shop_offer_from_grj_product(product: GRJCatalogProduct) -> SimpleNamespace:
    return SimpleNamespace(
        product_id=f"grj:{product.external_id}",
        slug=_slug_from_text(product.name),
        name=product.name,
        description=product.description,
        pickup_price=product.pickup_price,
        delivery_price=product.delivery_price,
        badge="Sistema GRJ",
        image_url=product.image_url or _catalog_image_for_name(product.name),
        stock_status=product.stock_status,
        rating_count=0,
        rating_average=0,
        customer_rating=None,
        source="grj",
    )


def _customer_prefill(customer: Customer | None) -> SimpleNamespace:
    return SimpleNamespace(
        name=customer.name if customer else "",
        phone=customer.phone if customer else "",
        neighborhood=customer.neighborhood if customer else "",
        street=customer.street if customer else "",
        number=customer.number if customer else "",
        complement=customer.complement if customer else "",
        buy_mode=customer.buy_mode if customer else "delivery",
        payment_method="pix",
    )


def _fallback_shop_offer() -> SimpleNamespace:
    return SimpleNamespace(
        product_id=None,
        slug="galao-20l",
        name="Galão 20L",
        description="Água mineral para retirada ou entrega.",
        pickup_price=14.0,
        delivery_price=16.0,
        badge="Pedido rápido",
        image_url="/static/img/20.png",
        stock_status="disponivel",
        rating_count=0,
        rating_average=0,
        customer_rating=None,
    )


def _active_shop_offers(db: Session) -> list[SimpleNamespace]:
    offers, _ = _shop_catalog(db)
    return offers


def _shop_catalog(db: Session) -> tuple[list[SimpleNamespace], str]:
    try:
        grj_products = fetch_grj_products(limit=500)
    except GRJCatalogUnavailable:
        grj_products = []
    if grj_products:
        return [_shop_offer_from_grj_product(product) for product in grj_products], ""

    products = db.execute(
        select(Product)
        .where(Product.active == True)
        .order_by(Product.display_order.asc(), Product.name.asc())
    ).scalars().all()
    offers = [_shop_offer_from_product(product) for product in products]
    return (
        offers or [_fallback_shop_offer()],
        "Não foi possível carregar o catálogo atualizado agora. Mostrando produtos locais para você continuar.",
    )


def _home_location(customer: Customer | None) -> SimpleNamespace:
    if not customer:
        return SimpleNamespace(
            label="Informe seu endereço",
            detail="Entrega em Votuporanga",
            has_address=False,
            href="/app#address",
        )

    address_bits = [customer.street, customer.number]
    street_line = ", ".join(bit for bit in address_bits if bit)
    detail = customer.neighborhood or "Votuporanga"
    return SimpleNamespace(
        label=street_line or "Endereço não informado",
        detail=detail,
        has_address=bool(street_line),
        href="/app#address",
    )


def _home_loyalty(customer: Customer | None, db: Session) -> SimpleNamespace:
    if not customer:
        return SimpleNamespace(
            available=False,
            balance=0,
            progress=0,
            completed=0,
            missing=settings.CARD_TARGET_POINTS,
            message="Entre para acompanhar seus selos.",
        )

    balance = points_balance(db, customer.id)
    progress = card_progress(balance)
    completed = cards_completed(balance)
    missing = settings.CARD_TARGET_POINTS - progress if progress else settings.CARD_TARGET_POINTS
    return SimpleNamespace(
        available=True,
        balance=balance,
        progress=progress,
        completed=completed,
        missing=missing,
        message="Você tem recompensa disponível." if completed else f"Faltam {missing} selos.",
    )


def _app_delivery_days() -> list[SimpleNamespace]:
    labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    today = date.today()
    days = []
    for offset in range(4):
        current = date.fromordinal(today.toordinal() + offset)
        days.append(
            SimpleNamespace(
                label="Hoje" if offset == 0 else "Amanhã" if offset == 1 else labels[current.weekday()],
                date=f"{current.day:02d}/{current.month:02d}",
                iso_date=current.isoformat(),
            )
        )
    return days


def _hydration_profile(customer: Customer | None) -> SimpleNamespace:
    people = customer.people_in_home if customer and customer.people_in_home else 1
    if people <= 1:
        rhythm = "individual"
        reminder_count = 5
        message = "Rotina leve para lembrar ao longo do dia."
    elif people <= 3:
        rhythm = "casa"
        reminder_count = 6
        message = "Sugestão para manter a casa toda no ritmo."
    else:
        rhythm = "familia"
        reminder_count = 7
        message = "Mais lembretes para uma rotina com mais pessoas."

    return SimpleNamespace(
        people=people,
        rhythm=rhythm,
        reminder_count=reminder_count,
        message=message,
    )


# --- ROTA HOME ---
@router.get("/")
def home(request: Request):
    return RedirectResponse("/app", status_code=307)


@router.get("/app", response_class=HTMLResponse)
def app_home(request: Request, db: Session = Depends(get_db)):
    close_db = False
    if not hasattr(db, "execute"):
        db = SessionLocal()
        close_db = True

    customer = None
    cid = get_current_customer_id(request)
    if cid:
        customer = db.scalar(select(Customer).where(Customer.id == int(cid)))

    offers, catalog_error = _shop_catalog(db)
    loyalty = _home_loyalty(customer, db)
    try:
        return templates.TemplateResponse(
            request=request,
            name="app_home.html",
            context={
                "business_name": settings.BUSINESS_NAME,
                "customer": customer,
                "customer_logged_in": customer is not None,
                "customer_first_name": customer.name.split(" ")[0] if customer and customer.name else "",
                "location": _home_location(customer),
                "loyalty": loyalty,
                "primary_offer": offers[0],
                "quick_offers": offers[:3],
                "catalog_error": catalog_error,
                "loyalty_target": settings.CARD_TARGET_POINTS,
                "loyalty_reward": _money_reward(),
                "delivery_days": _app_delivery_days(),
                "hydration_profile": _hydration_profile(customer),
            },
        )
    finally:
        if close_db:
            db.close()


@router.get("/api/grj/produtos")
def api_grj_products(db: Session = Depends(get_db)):
    try:
        grj_products = fetch_grj_products(limit=500)
    except GRJCatalogUnavailable as exc:
        local_products = db.execute(
            select(Product)
            .where(Product.active == True)
            .order_by(Product.display_order.asc(), Product.name.asc())
        ).scalars().all()
        return {
            "ok": False,
            "source": "local_fallback",
            "message": "Não foi possível carregar o catálogo atualizado agora. Mostrando produtos locais para você continuar.",
            "detail": str(exc),
            "products": [_local_product_to_public_dict(product) for product in local_products],
        }

    return {
        "ok": True,
        "source": "grj_api",
        "products": [product_to_public_dict(product) for product in grj_products],
    }


@router.get("/loja", response_class=HTMLResponse)
def shop_page(
    request: Request,
    marca: str = "",
    produto: str = "",
    rating_error: str = "",
    rating_success: str = "",
    db: Session = Depends(get_db),
):
    return RedirectResponse("/app?screen=store", status_code=307)


@router.get("/fidelidade", response_class=HTMLResponse)
def loyalty_page(request: Request):
    return RedirectResponse("/app?screen=loyalty", status_code=307)


@router.get("/assine", response_class=HTMLResponse)
def subscribe_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="assine.html",
        context={"business_name": settings.BUSINESS_NAME},
    )


@router.post("/assine/interesse")
def subscription_interest_placeholder():
    return RedirectResponse("/assine", status_code=303)


@router.post("/loja/finalizar", response_class=HTMLResponse)
def finish_shop_order(
    request: Request,
    items_json: str = Form("[]"),
    fulfillment: str = Form("delivery"),
    payment_method: str = Form("pix"),
    name: str = Form(""),
    phone: str = Form(""),
    neighborhood: str = Form(""),
    street: str = Form(""),
    number: str = Form(""),
    complement: str = Form(""),
    notes: str = Form(""),
):
    try:
        raw_items = json.loads(items_json)
    except json.JSONDecodeError:
        raw_items = []

    items = []
    for raw_item in raw_items if isinstance(raw_items, list) else []:
        qty = int(raw_item.get("qty") or 1)
        unit_price = float(raw_item.get("unit_price") or raw_item.get("price") or 0)
        items.append(
            SimpleNamespace(
                name=raw_item.get("slug", "Produto"),
                qty=qty,
                subtotal=unit_price * qty,
            )
        )

    order = SimpleNamespace(
        code="PREVIEW",
        customer_name=name.strip() or "Cliente",
        customer_phone=normalize_phone(phone),
        fulfillment=fulfillment,
        payment_method=payment_method,
        street=street.strip(),
        number=number.strip(),
        complement=complement.strip(),
        neighborhood=neighborhood.strip(),
        notes=notes.strip(),
        total_estimate=sum(item.subtotal for item in items),
    )
    return templates.TemplateResponse(
        request=request,
        name="pedido_recebido.html",
        context={
            "business_name": settings.BUSINESS_NAME,
            "order": order,
            "items": items,
            "summary_items": items,
            "hide_chrome": True,
        },
    )


@router.post("/loja/prefill-login")
def shop_prefill_login(
    identifier: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    phone_n = normalize_phone(identifier)
    customer = db.scalar(select(Customer).where(Customer.phone == phone_n))
    if not customer or not verify_password(password, customer.pin_hash):
        return JSONResponse(
            {"ok": False, "message": "Nao foi possivel carregar este cadastro."},
            status_code=401,
        )

    return JSONResponse(
        {
            "ok": True,
            "customer": {
                "name": customer.name or "",
                "phone": customer.phone or "",
                "neighborhood": customer.neighborhood or "",
                "street": customer.street or "",
                "number": customer.number or "",
                "complement": customer.complement or "",
                "buy_mode": customer.buy_mode or "delivery",
            },
        }
    )


@router.post("/loja/avaliar")
def shop_rating_placeholder():
    return RedirectResponse("/app?screen=store", status_code=303)


# --- LOGIN ---
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=_chrome_hidden_context(),
    )


@router.post("/login", response_class=HTMLResponse)
def login_action(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    phone_n = normalize_phone(phone)
    customer = db.scalar(select(Customer).where(Customer.phone == phone_n))

    if not customer or not verify_password(password, customer.pin_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=_chrome_hidden_context(error="WhatsApp ou Senha invalidos."),
            status_code=400,
        )

    login_customer(request, customer.id)
    if customer.must_change_password:
        return RedirectResponse("/alterar-senha-obrigatoria", status_code=303)
    return RedirectResponse("/app", status_code=303)


@router.get("/alterar-senha-obrigatoria", response_class=HTMLResponse)
def change_password_page(request: Request, db: Session = Depends(get_db)):
    cid = get_current_customer_id(request)
    if not cid:
        return RedirectResponse("/login", status_code=303)

    customer = db.scalar(select(Customer).where(Customer.id == int(cid)))
    if not customer:
        return RedirectResponse("/logout", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="change_password.html",
        context=_chrome_hidden_context(),
    )


@router.post("/alterar-senha-obrigatoria", response_class=HTMLResponse)
def change_password_action(
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    cid = get_current_customer_id(request)
    if not cid:
        return RedirectResponse("/login", status_code=303)

    customer = db.scalar(select(Customer).where(Customer.id == int(cid)))
    if not customer:
        return RedirectResponse("/logout", status_code=303)

    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context=_chrome_hidden_context(error="As senhas nao coincidem."),
            status_code=400,
        )

    if len(password) != 4 or not password.isdigit():
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context=_chrome_hidden_context(error="A nova senha deve ter exatamente 4 digitos numericos."),
            status_code=400,
        )

    customer.pin_hash = hash_password(password)
    customer.must_change_password = False
    db.commit()
    return RedirectResponse("/app", status_code=303)


@router.get("/logout")
def logout(request: Request):
    logout_customer(request)
    return RedirectResponse("/login", status_code=303)


# --- CADASTRO ---
@router.get("/cadastrar", response_class=HTMLResponse)
def register_page(request: Request, ref: str | None = None):
    return templates.TemplateResponse(
        request=request,
        name="public_register.html",
        context=_chrome_hidden_context(ref=(ref or "").strip().upper()),
    )


@router.post("/cadastrar", response_class=HTMLResponse)
def register_action(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    birth_date: str = Form(""),
    zip_code: str = Form(...),
    street: str = Form(""),
    number: str = Form(""),
    neighborhood: str = Form(""),
    ref_code: str | None = Form(None),
    db: Session = Depends(get_db),
):
    phone_clean = normalize_phone(phone)
    cep_clean = normalize_phone(zip_code)
    parsed_birth_date = None
    if birth_date:
        try:
            parsed_birth_date = date.fromisoformat(birth_date)
        except ValueError:
            return templates.TemplateResponse(
                request=request,
                name="public_register.html",
                context=_chrome_hidden_context(
                    error="Data de nascimento invalida.",
                    form_data={
                        "name": name,
                        "phone": phone,
                        "birth_date": birth_date,
                        "zip_code": zip_code,
                    },
                ),
                status_code=400,
            )

    # --- TRAVA DE CEP (VOTUPORANGA) ---
    try:
        if not cep_clean:
            raise ValueError("CEP vazio")
        cep_int = int(cep_clean)
        if not (15500000 <= cep_int <= 15599999):
            return templates.TemplateResponse(
                request=request,
                name="public_register.html",
                context=_chrome_hidden_context(
                    error="Desculpe, cadastro exclusivo para Votuporanga-SP.",
                    form_data={
                        "name": name,
                        "phone": phone,
                        "birth_date": birth_date,
                        "zip_code": zip_code,
                    },
                ),
                status_code=400,
            )
    except ValueError:
        return templates.TemplateResponse(
            request=request,
            name="public_register.html",
            context=_chrome_hidden_context(
                error="CEP invalido.",
                form_data={"name": name, "phone": phone, "birth_date": birth_date},
            ),
            status_code=400,
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="public_register.html",
            context=_chrome_hidden_context(
                error="As senhas nao coincidem.",
                form_data={"name": name, "phone": phone, "birth_date": birth_date},
            ),
            status_code=400,
        )

    if db.scalar(select(Customer).where(Customer.phone == phone_clean)):
        return templates.TemplateResponse(
            request=request,
            name="public_register.html",
            context=_chrome_hidden_context(
                error="Este telefone ja esta cadastrado.",
                form_data={"name": name, "birth_date": birth_date},
            ),
            status_code=400,
        )

    new_customer = Customer(
        name=name.strip(),
        phone=phone_clean,
        pin_hash=hash_password(password),
        birth_date=parsed_birth_date,
        cep=cep_clean,
        street=street.strip(),
        number=number.strip(),
        neighborhood=neighborhood.strip(),
        city="Votuporanga",
        state="SP",
        card_token=gen_card_token(),
        referral_code=gen_referral_code(),
    )

    if ref_code:
        referrer = db.scalar(select(Customer).where(Customer.referral_code == ref_code))
        if referrer:
            new_customer.referred_by_id = referrer.id

    db.add(new_customer)
    db.commit()

    login_customer(request, new_customer.id)
    return RedirectResponse("/app", status_code=303)


# --- API PROXY BLINDADA (User-Agent + SSL Ignore) ---
@router.get("/api/cep/{cep}")
def api_cep(cep: str):
    try:
        cep_limpo = normalize_phone(cep)
        if len(cep_limpo) != 8:
            return JSONResponse({"erro": True, "detalhe": "CEP invalido."}, status_code=400)
        url = f"https://viacep.com.br/ws/{cep_limpo}/json/"

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            data = json.loads(response.read().decode())
            return JSONResponse(data)

    except Exception as e:
        return JSONResponse({"erro": True, "detalhe": str(e)})


@router.get("/api/localizacao/reversa")
def api_reverse_location(lat: str = "", lng: str = ""):
    try:
        latitude = float(lat)
        longitude = float(lng)
    except ValueError:
        return JSONResponse({"erro": True, "detalhe": "Localizacao invalida."}, status_code=400)

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return JSONResponse({"erro": True, "detalhe": "Localizacao fora do intervalo valido."}, status_code=400)

    try:
        params = urllib.parse.urlencode(
            {
                "format": "jsonv2",
                "lat": f"{latitude:.6f}",
                "lon": f"{longitude:.6f}",
                "zoom": "18",
                "addressdetails": "1",
                "accept-language": "pt-BR",
            }
        )
        url = f"https://nominatim.openstreetmap.org/reverse?{params}"
        headers = {
            "User-Agent": (
                "CentralAguasFidelidade/1.0 "
                "(contato@centralaguas.com.br)"
            )
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode())

        address = data.get("address") or {}
        street = (
            address.get("road")
            or address.get("pedestrian")
            or address.get("residential")
            or address.get("footway")
            or address.get("path")
            or ""
        )
        neighborhood = (
            address.get("suburb")
            or address.get("neighbourhood")
            or address.get("quarter")
            or address.get("city_district")
            or ""
        )
        city = address.get("city") or address.get("town") or address.get("municipality") or "Votuporanga"
        state = address.get("state") or "SP"

        if not any([street, neighborhood, city]):
            return JSONResponse({"erro": True, "detalhe": "Endereco nao encontrado."}, status_code=404)

        label_parts = [street, neighborhood, city]
        label = " - ".join(part for part in label_parts if part)

        return JSONResponse(
            {
                "erro": False,
                "label": label,
                "street": street,
                "neighborhood": neighborhood,
                "city": city,
                "state": state,
            }
        )
    except Exception as e:
        return JSONResponse({"erro": True, "detalhe": str(e)}, status_code=502)
