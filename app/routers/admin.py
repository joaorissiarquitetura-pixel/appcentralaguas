import os
import hmac
import logging
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from fastapi import APIRouter, Request, Form, Depends, File, UploadFile
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, func, extract, desc, text, delete
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import time as _time
import json

from ..database import get_db
from ..models import AppBanner, AppBannerEvent, AppDevice, AppNotification, AppPromotion, Attendant, Coupon, Customer, CustomerHouseStock, LocationAccessLog, Product, PushSubscription, Transaction, LoyaltyLedger, Alert, Redemption, TransactionItem, WhatsAppCampaign, WhatsAppCampaignRecipient, WhatsAppConversation, WhatsAppMessage
from ..auth import get_current_attendant_id, is_admin
from ..security import hash_password
from ..config import settings
from ..services.address import geocode_address_query, geocode_structured
from ..services.audit import log_admin_action
from ..services.grj_catalog import GRJCatalogUnavailable, fetch_grj_products
from ..services.push import fcm_configured, push_configured, send_fcm, send_notification_to_app_devices, send_notification_to_subscriptions
from ..services.whatsapp import normalize_brazilian_phone, send_campaign_template_whatsapp, send_text_whatsapp, whatsapp_cloud_api_configured
from ..services.whatsapp_webhook import get_or_create_whatsapp_conversation

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/admin")
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("app/static/uploads/products")
BANNER_UPLOAD_DIR = Path("app/static/uploads/banners")
APP_TZ = ZoneInfo("America/Sao_Paulo")


def _banner_file_url(filename: str) -> str:
    return f"/static/uploads/banners/{filename}"


def _store_banner_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("Imagem do banner deve ser JPG, PNG ou WEBP")
    BANNER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}{suffix}"
    target_path = BANNER_UPLOAD_DIR / filename
    target_path.write_bytes(upload.file.read())
    return _banner_file_url(filename)


def _store_remote_banner_image(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL da imagem deve começar com http:// ou https://")

    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "CentralAguasApp/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            suffix_by_type = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
            }
            suffix = suffix_by_type.get(content_type) or Path(parsed.path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise ValueError("URL informada não retornou uma imagem JPG, PNG ou WEBP")
            data = response.read(5 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("Não foi possível baixar a imagem informada. Envie o arquivo pelo botão de upload.") from exc

    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Imagem do banner deve ter no máximo 5 MB")

    BANNER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}{suffix}"
    (BANNER_UPLOAD_DIR / filename).write_bytes(data)
    return _banner_file_url(filename)


def _normalize_banner_image(image_url: str, upload: UploadFile | None) -> str:
    if upload and upload.filename:
        return _store_banner_upload(upload)
    image = image_url.strip()
    if not image:
        raise ValueError("Informe a imagem do banner")
    if image.startswith("/static/uploads/banners/"):
        return image
    if image.startswith("/static/"):
        return image
    return _store_remote_banner_image(image)

# --- FUNÇÃO DE SEGURANÇA ---
def require_admin(request: Request, db: Session) -> Attendant | None:
    aid = get_current_attendant_id(request)
    if not aid:
        return None
    admin = db.scalar(select(Attendant).where(Attendant.id == int(aid)))
    if not admin or not is_admin(admin):
        return None
    return admin


def _admin_datetime_label(value: datetime | None, fmt: str = "%d/%m %H:%M") -> str:
    if not value:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TZ).strftime(fmt)


def _channel_label(channel: str | None) -> str:
    text = (channel or "").strip().lower()
    if text in {"app", "app_online", "online"}:
        return "App"
    if text in {"retirada", "pickup"}:
        return "Retirada"
    if text in {"entrega", "delivery"}:
        return "Sistema"
    return "Sistema" if text else "Sem compra"


def _commercial_map_summary(db: Session) -> dict:
    customers = db.execute(select(Customer)).scalars().all()
    by_neighborhood = {}
    markers = []

    for customer in customers:
        neighborhood = customer.neighborhood or "Sem bairro"
        bucket = by_neighborhood.setdefault(
            neighborhood,
            {
                "neighborhood": neighborhood,
                "city": customer.city or "Sem cidade",
                "customers": 0,
                "with_coordinates": 0,
                "loyalty_points": 0,
            },
        )
        bucket["customers"] += 1
        bucket["loyalty_points"] += customer.points or 0
        if customer.lat is not None and customer.lon is not None:
            bucket["with_coordinates"] += 1
            markers.append(
                {
                    "id": customer.id,
                    "name": customer.name,
                    "lat": customer.lat,
                    "lon": customer.lon,
                    "neighborhood": neighborhood,
                    "city": customer.city,
                    "street": customer.street,
                    "number": customer.number,
                    "complement": customer.complement,
                    "state": customer.state,
                    "cep": customer.cep,
                    "points": customer.points or 0,
                }
            )

    neighborhoods = sorted(
        by_neighborhood.values(),
        key=lambda item: (item["customers"], item["with_coordinates"], item["loyalty_points"]),
        reverse=True,
    )
    campaign_zones = []
    for row in neighborhoods[:5]:
        campaign_zones.append(
            {
                "neighborhood": row["neighborhood"],
                "city": row["city"],
                "customers": row["customers"],
                "signal": "forte" if row["customers"] >= 10 else "media" if row["customers"] >= 5 else "teste",
                "reason": "Alta concentração para impulsionamento regional." if row["customers"] >= 5 else "Base pequena, boa para campanha de validação.",
            }
        )

    total = len(customers)
    return {
        "total": total,
        "with_coords": len(markers),
        "missing": max(total - len(markers), 0),
        "neighborhoods": neighborhoods,
        "campaign_zones": campaign_zones,
        "customers_json": json.dumps(markers),
    }


def _active_consumption_alerts(db: Session, limit: int = 200) -> list[dict]:
    alerts_db = db.execute(
        select(Alert).where(Alert.resolved_at.is_(None)).order_by(Alert.created_at.desc()).limit(limit)
    ).scalars().all()

    alerts_display = []
    for alert in alerts_db:
        last_txs = db.execute(
            select(Transaction.created_at)
            .where(Transaction.customer_id == alert.customer_id)
            .order_by(Transaction.created_at.desc())
            .limit(5)
        ).scalars().all()

        avg_days, last_date_str, next_date_str = 0, "N/A", "N/A"
        if last_txs:
            last_tx_date = last_txs[0]
            last_date_str = last_tx_date.strftime("%d/%m/%Y")
            if len(last_txs) >= 2:
                intervals = [max(1, (last_txs[i] - last_txs[i + 1]).days) for i in range(len(last_txs) - 1)]
                avg_days = int(sum(intervals) / len(intervals))
                next_date_str = (last_tx_date + timedelta(days=avg_days)).strftime("%d/%m/%Y")

        alerts_display.append(
            {
                "customer": alert.customer,
                "avg": avg_days,
                "last_date": last_date_str,
                "next_date": next_date_str,
                "status": "critico" if alert.type == "overdue" else "aviso",
                "msg": "Atrasado!" if alert.type == "overdue" else "Próximo do fim",
            }
        )

    return alerts_display


def _campaign_default_preview() -> str:
    return (
        "Oi, {{1}}! Vim te contar uma novidade.\n\n"
        "A Central Águas está ficando ainda mais perto de você. Agora também no digital!\n\n"
        "Como você já faz parte do nosso Clube de Fidelidade, queremos te convidar para conhecer "
        "em primeira mão o novo app da Central Águas.\n\n"
        "Por lá, você já pode:\n"
        "- Fazer pedidos de água online\n"
        "- Consultar seus pontos\n"
        "- Controlar seus galões cheios e vazios\n"
        "- Criar lembretes para não deixar a água acabar\n"
        "- Acompanhar promoções e cupons\n"
        "- Continuar acumulando pontos nas compras\n\n"
        "O app ainda está em fase de testes, então sua experiência e seu feedback vão nos ajudar "
        "a deixar tudo cada vez melhor.\n\n"
        "E fique tranquilo: nossos outros canais de atendimento continuam os mesmos. Você ainda "
        "pode falar com a Central Águas pelo telefone e WhatsApp de sempre.\n\n"
        "Central Águas: a gente cuida da água para você ter tempo de cuidar de todo o resto."
    )


def _campaign_legacy_preview() -> str:
    return (
        "Olá, {{1}}! A Central Águas está com o app funcionando. "
        "Acesse app.centralaguas.com.br para fazer pedidos, consultar seus pontos, "
        "controlar seu estoque de galões e criar lembretes para beber água. "
        "Para não receber mais avisos, responda SAIR."
    )


def _refresh_draft_campaign_previews(db: Session) -> None:
    legacy_preview = _campaign_legacy_preview()
    default_preview = _campaign_default_preview()
    campaigns = db.execute(
        select(WhatsAppCampaign).where(
            WhatsAppCampaign.status == "draft",
            WhatsAppCampaign.message_preview == legacy_preview,
        )
    ).scalars().all()
    for campaign in campaigns:
        campaign.message_preview = default_preview
    if campaigns:
        db.commit()


def _campaign_message_text(campaign: WhatsAppCampaign, customer_name: str | None = None) -> str:
    """Texto legível no histórico para um template enviado pela campanha."""
    preview = (campaign.message_preview or "").strip()
    if preview:
        first_name = (customer_name or "cliente").strip().split(" ", 1)[0] or "cliente"
        preview = preview.replace("{{1}}", first_name[:60])
        return preview[:4096]
    return f"Template enviado: {campaign.template_name}"[:4096]


def _backfill_campaign_messages(db: Session) -> None:
    """Cria o histórico das campanhas enviadas antes da integração com o inbox."""
    sent_recipients = db.execute(
        select(WhatsAppCampaignRecipient, WhatsAppCampaign)
        .join(WhatsAppCampaign, WhatsAppCampaign.id == WhatsAppCampaignRecipient.campaign_id)
        .where(
            WhatsAppCampaignRecipient.status == "sent",
            WhatsAppCampaignRecipient.message_id.is_(None),
        )
    ).all()

    changed = False
    for recipient, campaign in sent_recipients:
        customer = db.get(Customer, recipient.customer_id) if recipient.customer_id else None
        conversation = get_or_create_whatsapp_conversation(
            db,
            phone=recipient.phone,
            customer=customer,
        )
        timestamp = recipient.sent_at or campaign.sent_at or recipient.created_at or datetime.utcnow()
        message = WhatsAppMessage(
            conversation_id=conversation.id,
            customer_id=customer.id if customer else None,
            phone=recipient.phone,
            direction="outbound",
            message_type="template",
            text=_campaign_message_text(campaign, recipient.customer_name),
            raw_payload=json.dumps(
                {
                    "campaign_id": campaign.id,
                    "template_name": campaign.template_name,
                    "historical": True,
                },
                ensure_ascii=False,
            ),
            status="sent",
            timestamp=timestamp,
        )
        db.add(message)
        db.flush()

        recipient.conversation_id = conversation.id
        recipient.message_id = message.id
        if not conversation.last_message_at or timestamp >= conversation.last_message_at:
            conversation.last_message_at = timestamp
            conversation.last_message_preview = message.text[:255]
        conversation.updated_at = datetime.utcnow()
        changed = True

    if changed:
        db.commit()


def _refresh_campaign_message_history(db: Session) -> None:
    """Mantém o histórico das campanhas com o nome renderizado do cliente."""
    sent_messages = db.execute(
        select(WhatsAppCampaignRecipient, WhatsAppCampaign, WhatsAppMessage)
        .join(WhatsAppCampaign, WhatsAppCampaign.id == WhatsAppCampaignRecipient.campaign_id)
        .join(WhatsAppMessage, WhatsAppMessage.id == WhatsAppCampaignRecipient.message_id)
        .where(WhatsAppMessage.message_type == "template")
    ).all()

    changed = False
    for recipient, campaign, message in sent_messages:
        rendered_text = _campaign_message_text(campaign, recipient.customer_name)
        if message.text != rendered_text:
            message.text = rendered_text
            changed = True
        if message.authored_attendant_id is not None:
            message.authored_attendant_id = None
            changed = True
    if changed:
        db.commit()


def _campaign_recipient_phones_for_template(db: Session, template_name: str) -> set[str]:
    selected_template = (template_name or "").strip()
    if not selected_template:
        return set()

    rows = db.execute(
        select(WhatsAppCampaignRecipient.phone)
        .join(WhatsAppCampaign, WhatsAppCampaign.id == WhatsAppCampaignRecipient.campaign_id)
        .where(
            WhatsAppCampaign.template_name == selected_template,
            WhatsAppCampaignRecipient.status.in_(["pending", "sent"]),
        )
    ).scalars().all()
    return {phone for phone in (normalize_brazilian_phone(row) for row in rows) if phone}


def _eligible_campaign_customers(db: Session, limit: int, exclude_template_name: str | None = None) -> list[Customer]:
    target = max(1, min(int(limit or 500), 5000))
    excluded_phones = _campaign_recipient_phones_for_template(db, exclude_template_name or "")
    customers = db.execute(
        select(Customer)
        .where(Customer.phone.is_not(None))
        .order_by(Customer.name.asc(), Customer.id.asc())
    ).scalars().all()
    seen: set[str] = set()
    eligible = []
    for customer in customers:
        phone = normalize_brazilian_phone(customer.phone)
        if not phone or phone in seen or phone in excluded_phones:
            continue
        seen.add(phone)
        eligible.append(customer)
        if len(eligible) >= target:
            break
    return eligible


def _house_stock_summary(stock: CustomerHouseStock | None) -> dict:
    if not stock:
        return {
            "label": "Sem calibração",
            "detail": "Cliente ainda não informou os galões da casa.",
            "status": "missing",
            "updated": "",
            "total": None,
            "full": None,
            "in_use": None,
            "empty": None,
            "oldest_validity": "",
        }
    if stock.skipped and not stock.calibrated:
        return {
            "label": "Registrar depois",
            "detail": "Cliente deixou para informar quando estiver em casa.",
            "status": "skipped",
            "updated": _admin_datetime_label(stock.updated_at, "%d/%m/%Y %H:%M"),
            "total": stock.total,
            "full": stock.full,
            "in_use": stock.in_use,
            "empty": stock.empty,
            "oldest_validity": stock.oldest_validity or "",
        }
    detail = (
        f"{stock.full or 0} cheio(s), {stock.empty or 0} vazio(s), "
        f"{stock.in_use or 0} em uso"
    )
    if stock.oldest_validity:
        detail += f" · validade mais antiga {stock.oldest_validity}"
    return {
        "label": f"{stock.total or 0} galão(ões)",
        "detail": detail,
        "status": "ok",
        "updated": _admin_datetime_label(stock.updated_at, "%d/%m/%Y %H:%M"),
        "total": stock.total,
        "full": stock.full,
        "in_use": stock.in_use,
        "empty": stock.empty,
        "oldest_validity": stock.oldest_validity or "",
    }


def _grj_app_status_url() -> str:
    orders_url = settings.CENTRAL_AGUAS_ORDERS_API_URL.strip()
    if orders_url.endswith("/orders"):
        return f"{orders_url}/app-status"
    return urllib.parse.urljoin(orders_url.rstrip("/") + "/", "app-status")


def _valid_recovery_token(token: str) -> bool:
    expected = os.getenv("ADMIN_RECOVERY_TOKEN", "").strip()
    if len(expected) < 24:
        return False
    return hmac.compare_digest(token.strip(), expected)


@router.get("/recover-access", response_class=HTMLResponse)
def admin_recover_access_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not _valid_recovery_token(token):
        return HTMLResponse("Recuperacao indisponivel.", status_code=404)
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="pt-BR">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Recuperar admin</title>
          <style>
            body { font-family: Arial, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #eef6ff; color: #102033; }
            form { width: min(420px, calc(100vw - 32px)); display: grid; gap: 14px; padding: 24px; background: #fff; border: 1px solid #d8e6f5; border-radius: 12px; box-shadow: 0 18px 50px rgba(0,0,0,.08); }
            h1 { margin: 0 0 4px; font-size: 22px; }
            label { display: grid; gap: 6px; font-size: 13px; font-weight: 700; }
            input { height: 42px; border: 1px solid #cbd9ea; border-radius: 8px; padding: 0 12px; font: inherit; }
            button { height: 44px; border: 0; border-radius: 8px; background: #0b4ccb; color: #fff; font-weight: 800; cursor: pointer; }
            p { margin: 0; color: #607084; font-size: 14px; }
          </style>
        </head>
        <body>
          <form method="post" action="/admin/recover-access">
            <h1>Recuperar admin</h1>
            <p>Defina o login que vai acessar o painel.</p>
            <input type="hidden" name="token" value="{token}">
            <label>Nome
              <input name="name" value="Administrador" required>
            </label>
            <label>E-mail
              <input name="email" type="email" value="admin@centralaguas.com" required>
            </label>
            <label>Senha nova
              <input name="password" type="password" minlength="8" required>
            </label>
            <button type="submit">Salvar acesso admin</button>
          </form>
        </body>
        </html>
        """.replace("{token}", token.strip())
    )


@router.post("/recover-access", response_class=HTMLResponse)
def admin_recover_access_action(
    request: Request,
    token: str = Form(""),
    name: str = Form("Administrador"),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not _valid_recovery_token(token):
        return HTMLResponse("Recuperacao indisponivel.", status_code=404)
    if len(password.strip()) < 8:
        return HTMLResponse("A senha precisa ter pelo menos 8 caracteres.", status_code=400)

    email_normalized = email.strip().lower()
    admin = db.scalar(select(Attendant).where(Attendant.email == email_normalized))
    if not admin:
        admin = Attendant(
            name=name.strip() or "Administrador",
            email=email_normalized,
            password_hash=hash_password(password.strip()),
            role="admin",
            is_active=True,
        )
        db.add(admin)
    else:
        admin.name = name.strip() or admin.name
        admin.password_hash = hash_password(password.strip())
        admin.role = "admin"
        admin.is_active = True
    db.commit()

    return HTMLResponse(
        """
        <!doctype html>
        <html lang="pt-BR">
        <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
        <body style="font-family:Arial,sans-serif;display:grid;place-items:center;min-height:100vh;background:#eef6ff;color:#102033">
          <main style="background:white;padding:24px;border-radius:12px;border:1px solid #d8e6f5;max-width:420px">
            <h1 style="margin-top:0">Admin atualizado</h1>
            <p>Agora entre com o e-mail e senha que voce acabou de definir.</p>
            <a href="/atendente/login" style="display:inline-block;margin-top:12px;background:#0b4ccb;color:white;padding:12px 16px;border-radius:8px;text-decoration:none;font-weight:800">Ir para login</a>
          </main>
        </body>
        </html>
        """
    )


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


def _admin_local_product(product: Product) -> SimpleNamespace:
    return SimpleNamespace(
        id=product.id,
        external_id=str(product.id),
        name=product.name,
        description=product.description,
        promo_badge=product.promo_badge,
        image_url=product.image_url,
        pickup_price=product.pickup_price,
        delivery_price=product.delivery_price,
        promo_pickup_price=product.promo_pickup_price,
        promo_delivery_price=product.promo_delivery_price,
        stock_status=product.stock_status or "disponivel",
        stock_quantity=None,
        active=bool(product.active),
        featured_on_home=bool(product.featured_on_home),
        display_order=product.display_order or 0,
        source_label="Manual",
        imported=False,
    )


def _admin_grj_product(product, display_order: int) -> SimpleNamespace:
    image_url = f"/api/grj/produtos/{quote(product.external_id, safe='')}/imagem" if product.image_url else ""
    return SimpleNamespace(
        id=None,
        external_id=product.external_id,
        name=product.name,
        description=product.description,
        promo_badge="Importado da GRJ",
        image_url=image_url,
        pickup_price=product.pickup_price,
        delivery_price=product.delivery_price,
        promo_pickup_price=None,
        promo_delivery_price=None,
        stock_status=product.stock_status,
        stock_quantity=product.stock_quantity,
        active=bool(product.active),
        featured_on_home=True,
        display_order=display_order,
        source_label="GRJ",
        imported=True,
    )

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
    customer_ids = [int(c.id) for c in all_customers]
    stock_by_customer = {}
    latest_tx_by_customer = {}
    latest_device_by_customer = {}
    if customer_ids:
        stock_by_customer = {
            stock.customer_id: stock
            for stock in db.execute(
                select(CustomerHouseStock).where(CustomerHouseStock.customer_id.in_(customer_ids))
            ).scalars().all()
        }
        for tx in db.execute(
            select(Transaction)
            .where(Transaction.customer_id.in_(customer_ids))
            .order_by(Transaction.customer_id.asc(), Transaction.created_at.desc())
        ).scalars().all():
            latest_tx_by_customer.setdefault(tx.customer_id, tx)
        for device in db.execute(
            select(AppDevice)
            .where(AppDevice.customer_id.in_(customer_ids))
            .order_by(AppDevice.customer_id.asc(), AppDevice.last_seen_at.desc())
        ).scalars().all():
            latest_device_by_customer.setdefault(device.customer_id, device)

    customer_summaries = {}
    calibrated_count = 0
    for customer in all_customers:
        stock = stock_by_customer.get(customer.id)
        stock_summary = _house_stock_summary(stock)
        if stock and stock.calibrated:
            calibrated_count += 1
        latest_tx = latest_tx_by_customer.get(customer.id)
        latest_device = latest_device_by_customer.get(customer.id)
        last_purchase_at = customer.last_purchase_at
        source = _channel_label(latest_tx.channel if latest_tx else None)
        if stock and stock.client_order_id and (not latest_tx or stock.updated_at >= latest_tx.created_at):
            source = "App"
            last_purchase_at = max(filter(None, [last_purchase_at, stock.updated_at]), default=stock.updated_at)
        elif latest_tx:
            last_purchase_at = latest_tx.created_at

        customer_summaries[customer.id] = {
            "stock": stock_summary,
            "last_purchase": _admin_datetime_label(last_purchase_at, "%d/%m/%Y %H:%M") if last_purchase_at else "Sem compra",
            "last_purchase_source": source,
            "last_purchase_points": latest_tx.points if latest_tx else 0,
            "last_app_access": _admin_datetime_label(latest_device.last_seen_at, "%d/%m/%Y %H:%M") if latest_device else "Sem acesso",
            "device_label": latest_device.platform if latest_device and latest_device.platform else "",
        }

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
            "customer_summaries": customer_summaries,
            "linked_customers": linked_customers,
            "unlinked_customers": len(all_customers) - linked_customers,
            "calibrated_customers": calibrated_count,
            "uncalibrated_customers": max(len(all_customers) - calibrated_count, 0),
            "birthdays": birthdays,
            "ranking": ranking,
            "q": q,
            "business_name": settings.BUSINESS_NAME,
            "admin": admin
        }
    )

# --- MAPA DE CLIENTES ---
@router.get("/map", response_class=HTMLResponse)
def map_page(request: Request, success: str = "", err: str = "", db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    map_summary = _commercial_map_summary(db)

    return templates.TemplateResponse(
        request=request,
        name="admin_map.html",
        context={
            "business_name": settings.BUSINESS_NAME,
            "admin": admin,
            "total": map_summary["total"],
            "with_coords": map_summary["with_coords"],
            "missing": map_summary["missing"],
            "neighborhoods": map_summary["neighborhoods"][:10],
            "campaign_zones": map_summary["campaign_zones"],
            "customers_json": map_summary["customers_json"],
            "google_geocoding_configured": bool(settings.GOOGLE_MAPS_API_KEY.strip()),
            "success": success,
            "err": err,
        }
    )


@router.post("/map/customers/{customer_id}/coordinates", response_class=JSONResponse)
async def update_customer_coordinates(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    customer = db.get(Customer, customer_id)
    if not customer:
        return JSONResponse({"ok": False, "error": "customer_not_found"}, status_code=404)

    try:
        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "invalid_coordinates"}, status_code=400)

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return JSONResponse({"ok": False, "error": "invalid_coordinates"}, status_code=400)

    customer.lat = lat
    customer.lon = lon
    log_admin_action(
        db,
        action="customer_coordinates_updated",
        actor_attendant_id=admin.id,
        entity_type="customer",
        entity_id=customer.id,
        details={"lat": lat, "lon": lon, "source": "admin_map_drag"},
        request=request,
    )
    db.commit()
    return {"ok": True, "lat": lat, "lon": lon}


@router.post("/map/geocode-search", response_class=JSONResponse)
async def geocode_map_search(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    address = str(payload.get("address") or "").strip()
    if len(address) < 5 or len(address) > 300:
        return JSONResponse({"ok": False, "error": "invalid_address"}, status_code=400)

    result = geocode_address_query(address)
    if not result:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return {"ok": True, **result}


# --- ALERTAS INTELIGENTES ---
@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    alerts_display = _active_consumption_alerts(db)

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
    err: str = "",
    success: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    return RedirectResponse("/admin/coupons", status_code=303)


@router.get("/coupons", response_class=HTMLResponse)
def admin_coupons(
    request: Request,
    edit_coupon_id: int = 0,
    err: str = "",
    success: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    coupons = db.execute(select(Coupon).order_by(Coupon.display_order.asc(), Coupon.created_at.desc())).scalars().all()
    editing_coupon = db.get(Coupon, edit_coupon_id) if edit_coupon_id else None

    return templates.TemplateResponse(
        request=request,
        name="admin_coupons.html",
        context={
            "admin": admin,
            "business_name": settings.BUSINESS_NAME,
            "coupons": coupons,
            "editing_coupon": editing_coupon,
            "coupon_available_count": sum(1 for coupon in coupons if _coupon_available(coupon)),
            "err": err,
            "success": success,
        },
    )


@router.get("/notifications", response_class=HTMLResponse)
def admin_notifications(
    request: Request,
    tab: str = "push",
    page: int = 1,
    err: str = "",
    success: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    blocked_device_ids = {
        row[0]
        for row in db.execute(select(AppDevice.device_id).where(AppDevice.is_blocked == True)).all()
    }
    subscriptions = db.execute(select(PushSubscription).order_by(PushSubscription.updated_at.desc()).limit(80)).scalars().all()
    notification_page = max(int(page or 1), 1)
    notification_per_page = 20
    notification_total = db.scalar(select(func.count(AppNotification.id))) or 0
    latest_notifications = db.execute(
        select(AppNotification)
        .order_by(AppNotification.created_at.desc())
        .offset((notification_page - 1) * notification_per_page)
        .limit(notification_per_page)
    ).scalars().all()
    banners = db.execute(select(AppBanner).order_by(AppBanner.active.desc(), AppBanner.display_order.asc(), AppBanner.created_at.desc()).limit(30)).scalars().all()
    app_promotions = db.execute(select(AppPromotion).order_by(AppPromotion.active.desc(), AppPromotion.display_order.asc(), AppPromotion.created_at.desc()).limit(30)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin_notifications.html",
        context={
            "admin": admin,
            "business_name": settings.BUSINESS_NAME,
            "latest_notifications": latest_notifications,
            "notification_page": notification_page,
            "notification_per_page": notification_per_page,
            "notification_total": notification_total,
            "notification_total_pages": max((notification_total + notification_per_page - 1) // notification_per_page, 1),
            "banners": banners,
            "app_promotions": app_promotions,
            "active_tab": tab if tab in {"push", "banners", "promotions", "history"} else "push",
            "device_count": db.scalar(select(func.count(AppDevice.id))) or 0,
            "fcm_device_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.fcm_token.is_not(None), AppDevice.is_blocked.is_not(True))) or 0,
            "push_active_count": sum(1 for subscription in subscriptions if subscription.active and subscription.device_id not in blocked_device_ids),
            "push_configured": push_configured(),
            "fcm_configured": fcm_configured(),
            "format_dt": _admin_datetime_label,
            "err": err,
            "success": success,
        },
    )


@router.get("/whatsapp-campaigns", response_class=HTMLResponse)
def whatsapp_campaigns_page(
    request: Request,
    campaign_id: int | None = None,
    conversation_id: int | None = None,
    tab: str = "campaigns",
    err: str = "",
    success: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/atendente/login", status_code=303)

    _backfill_campaign_messages(db)
    _refresh_campaign_message_history(db)
    _refresh_draft_campaign_previews(db)

    campaigns = db.execute(
        select(WhatsAppCampaign).order_by(WhatsAppCampaign.created_at.desc()).limit(30)
    ).scalars().all()
    selected_campaign = db.get(WhatsAppCampaign, campaign_id) if campaign_id else (campaigns[0] if campaigns else None)
    recipients = []
    if selected_campaign:
        recipients = db.execute(
            select(WhatsAppCampaignRecipient)
            .where(WhatsAppCampaignRecipient.campaign_id == selected_campaign.id)
            .order_by(WhatsAppCampaignRecipient.id.desc())
            .limit(120)
        ).scalars().all()
    conversations = db.execute(
        select(WhatsAppConversation)
        .order_by(WhatsAppConversation.last_message_at.desc().nullslast(), WhatsAppConversation.updated_at.desc())
        .limit(40)
    ).scalars().all()
    selected_conversation = None
    if conversation_id:
        selected_conversation = db.get(WhatsAppConversation, conversation_id)
    if not selected_conversation:
        selected_conversation = conversations[0] if conversations else None
    latest_messages = []
    if selected_conversation:
        if tab == "messages" and selected_conversation.unread_count:
            selected_conversation.unread_count = 0
            selected_conversation.last_read_by_attendant_id = admin.id
            selected_conversation.last_read_at = datetime.utcnow()
            selected_conversation.updated_at = selected_conversation.last_read_at
            db.commit()
        latest_messages = db.execute(
            select(WhatsAppMessage)
            .where(WhatsAppMessage.conversation_id == selected_conversation.id)
            .order_by(WhatsAppMessage.timestamp.desc())
            .limit(20)
        ).scalars().all()

    valid_phone_count = len(_eligible_campaign_customers(db, 5000))
    return templates.TemplateResponse(
        request=request,
        name="admin_whatsapp_campaigns.html",
        context={
            "business_name": settings.BUSINESS_NAME,
            "admin": admin,
            "campaigns": campaigns,
            "selected_campaign": selected_campaign,
            "recipients": recipients,
            "conversations": conversations,
            "selected_conversation": selected_conversation,
            "latest_messages": latest_messages,
            "valid_phone_count": valid_phone_count,
            "template_configured": bool(settings.WHATSAPP_APP_LAUNCH_TEMPLATE_NAME.strip()),
            "api_configured": whatsapp_cloud_api_configured(),
            "default_template": settings.WHATSAPP_APP_LAUNCH_TEMPLATE_NAME.strip(),
            "default_language": settings.WHATSAPP_RESET_TEMPLATE_LANGUAGE.strip() or "pt_BR",
            "default_preview": _campaign_default_preview(),
            "active_tab": tab if tab in {"campaigns", "messages"} else "campaigns",
            "format_dt": _admin_datetime_label,
            "err": err,
            "success": success,
        },
    )


def _whatsapp_message_author_label(message: WhatsAppMessage, conversation: WhatsAppConversation | None = None) -> str:
    if message.direction == "inbound":
        if message.customer and message.customer.name:
            return message.customer.name
        if conversation:
            return conversation.customer_name or conversation.phone
        return message.phone
    if message.authored_attendant:
        return f"{message.authored_attendant.name} - Central Águas"
    return "Central Águas"


def _whatsapp_message_status_label(message: WhatsAppMessage) -> str:
    if message.direction == "inbound":
        return "recebida"
    if message.message_type == "template":
        return "campanha enviada"
    if message.message_type == "auto_reply":
        return "automática"
    return "enviada"


def _whatsapp_message_payload(message: WhatsAppMessage, conversation: WhatsAppConversation | None = None) -> dict:
    return {
        "id": message.id,
        "direction": message.direction,
        "author": _whatsapp_message_author_label(message, conversation),
        "status": _whatsapp_message_status_label(message),
        "status_class": "sent" if message.direction == "outbound" else "pending",
        "text": message.text or "Mensagem sem texto salvo",
        "timestamp": _admin_datetime_label(message.timestamp),
    }


def _latest_whatsapp_messages(db: Session, conversation_id: int, limit: int = 40) -> list[WhatsAppMessage]:
    return list(
        reversed(
            db.execute(
                select(WhatsAppMessage)
                .where(WhatsAppMessage.conversation_id == conversation_id)
                .order_by(WhatsAppMessage.timestamp.desc(), WhatsAppMessage.id.desc())
                .limit(limit)
            ).scalars().all()
        )
    )


def _send_whatsapp_conversation_reply(
    *,
    db: Session,
    admin: Attendant,
    conversation: WhatsAppConversation,
    message: str,
    identify_sender: str,
    request: Request,
) -> tuple[bool, str, WhatsAppMessage | None]:
    message_text = (message or "").strip()
    if not message_text:
        return False, "Digite uma mensagem", None
    if not whatsapp_cloud_api_configured():
        return False, "WhatsApp Cloud API não configurado", None

    sender_label = f"{admin.name.strip()} - Central Águas" if identify_sender == "1" and admin.name.strip() else "Central Águas"
    outgoing_text = f"*{sender_label}*\n{message_text}" if identify_sender == "1" and admin.name.strip() else message_text
    ok, reason, wa_message_id = send_text_whatsapp(to_phone=conversation.phone, text=outgoing_text)
    if not ok:
        return False, f"Não foi possível enviar a resposta ({reason}). Se a janela de 24h fechou, envie um template primeiro.", None

    now = datetime.utcnow()
    outgoing_message = WhatsAppMessage(
        conversation_id=conversation.id,
        customer_id=conversation.customer_id,
        authored_attendant_id=admin.id,
        phone=conversation.phone,
        direction="outbound",
        wa_message_id=wa_message_id,
        message_type="text",
        text=outgoing_text[:4096],
        status="sent",
        timestamp=now,
    )
    db.add(outgoing_message)
    db.flush()
    conversation.last_message_at = now
    conversation.last_outbound_at = now
    conversation.unread_count = 0
    conversation.updated_at = now
    conversation.assigned_attendant_id = conversation.assigned_attendant_id or admin.id
    log_admin_action(
        db,
        action="whatsapp_conversation_reply_sent",
        actor_attendant_id=admin.id,
        entity_type="whatsapp_conversation",
        entity_id=conversation.id,
        details={"message_id": wa_message_id, "phone": conversation.phone, "sender": sender_label},
        request=request,
    )
    return True, "sent", outgoing_message


@router.post("/whatsapp-conversations/{conversation_id}/reply")
def reply_whatsapp_conversation(
    conversation_id: int,
    request: Request,
    message: str = Form(...),
    identify_sender: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/atendente/login", status_code=303)

    conversation = db.get(WhatsAppConversation, conversation_id)
    if not conversation:
        return RedirectResponse("/admin/whatsapp-campaigns?tab=messages&err=Conversa%20não%20encontrada", status_code=303)

    ok, result, _sent_message = _send_whatsapp_conversation_reply(
        db=db,
        admin=admin,
        conversation=conversation,
        message=message,
        identify_sender=identify_sender,
        request=request,
    )
    if not ok:
        return RedirectResponse(
            f"/admin/whatsapp-campaigns?tab=messages&conversation_id={conversation.id}&err={quote(result)}",
            status_code=303,
        )

    db.commit()
    return RedirectResponse(
        f"/admin/whatsapp-campaigns?tab=messages&conversation_id={conversation.id}&success=Resposta%20enviada",
        status_code=303,
    )


@router.get("/whatsapp-conversations/{conversation_id}/messages")
def whatsapp_conversation_messages(
    conversation_id: int,
    request: Request,
    after_id: int = 0,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    conversation = db.get(WhatsAppConversation, conversation_id)
    if not conversation:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)

    messages_query = select(WhatsAppMessage).where(WhatsAppMessage.conversation_id == conversation.id)
    if after_id:
        messages_query = messages_query.where(WhatsAppMessage.id > after_id)
    messages = db.execute(
        messages_query.order_by(WhatsAppMessage.timestamp.asc(), WhatsAppMessage.id.asc()).limit(80)
    ).scalars().all()

    if conversation.unread_count:
        conversation.unread_count = 0
        conversation.last_read_by_attendant_id = admin.id
        conversation.last_read_at = datetime.utcnow()
        conversation.updated_at = conversation.last_read_at
        db.commit()

    return JSONResponse(
        {
            "ok": True,
            "conversation_id": conversation.id,
            "last_message_id": max([message.id for message in messages], default=after_id),
            "messages": [_whatsapp_message_payload(message, conversation) for message in messages],
        }
    )


@router.post("/whatsapp-conversations/{conversation_id}/reply-json")
async def reply_whatsapp_conversation_json(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    conversation = db.get(WhatsAppConversation, conversation_id)
    if not conversation:
        return JSONResponse({"ok": False, "error": "Conversa não encontrada"}, status_code=404)

    form = await request.form()
    ok, result, sent_message = _send_whatsapp_conversation_reply(
        db=db,
        admin=admin,
        conversation=conversation,
        message=str(form.get("message") or ""),
        identify_sender=str(form.get("identify_sender") or ""),
        request=request,
    )
    if not ok:
        db.rollback()
        return JSONResponse({"ok": False, "error": result}, status_code=400)

    db.commit()
    db.refresh(sent_message)
    return JSONResponse(
        {
            "ok": True,
            "message": _whatsapp_message_payload(sent_message, conversation),
        }
    )


@router.post("/whatsapp-campaigns")
def create_whatsapp_campaign(
    request: Request,
    name: str = Form(...),
    template_name: str = Form(""),
    template_language: str = Form("pt_BR"),
    message_preview: str = Form(""),
    limit: int = Form(500),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/atendente/login", status_code=303)

    selected_template = template_name.strip() or settings.WHATSAPP_APP_LAUNCH_TEMPLATE_NAME.strip()
    if not selected_template:
        return RedirectResponse("/admin/whatsapp-campaigns?err=Configure%20o%20nome%20do%20template%20WhatsApp", status_code=303)

    customers = _eligible_campaign_customers(db, limit, exclude_template_name=selected_template)
    if not customers:
        return RedirectResponse("/admin/whatsapp-campaigns?err=Nenhum%20cliente%20novo%20para%20este%20template", status_code=303)

    campaign = WhatsAppCampaign(
        name=name.strip()[:120] or "Campanha WhatsApp",
        template_name=selected_template[:120],
        template_language=(template_language.strip() or "pt_BR")[:12],
        message_preview=message_preview.strip() or _campaign_default_preview(),
        target="all_customers",
        status="draft",
        created_by_attendant_id=admin.id,
    )
    db.add(campaign)
    db.flush()

    added = 0
    for customer in customers:
        phone = normalize_brazilian_phone(customer.phone)
        if not phone:
            continue
        db.add(
            WhatsAppCampaignRecipient(
                campaign_id=campaign.id,
                customer_id=customer.id,
                phone=phone,
                customer_name=customer.name,
                status="pending",
            )
        )
        added += 1

    log_admin_action(
        db,
        action="whatsapp_campaign_created",
        actor_attendant_id=admin.id,
        entity_type="whatsapp_campaign",
        entity_id=campaign.id,
        details={"template": campaign.template_name, "recipients": added},
        request=request,
    )
    db.commit()
    return RedirectResponse(
        f"/admin/whatsapp-campaigns?campaign_id={campaign.id}&success=Campanha%20criada%20com%20{added}%20destinatário(s)",
        status_code=303,
    )


@router.post("/whatsapp-campaigns/{campaign_id}/send")
def send_whatsapp_campaign_batch(
    campaign_id: int,
    request: Request,
    batch_size: int = Form(50),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/atendente/login", status_code=303)

    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        return RedirectResponse("/admin/whatsapp-campaigns?err=Campanha%20não%20encontrada", status_code=303)
    if not whatsapp_cloud_api_configured():
        return RedirectResponse(f"/admin/whatsapp-campaigns?campaign_id={campaign.id}&err=WhatsApp%20Cloud%20API%20não%20configurado", status_code=303)

    recipients = db.execute(
        select(WhatsAppCampaignRecipient)
        .where(
            WhatsAppCampaignRecipient.campaign_id == campaign.id,
            WhatsAppCampaignRecipient.status == "pending",
        )
        .order_by(WhatsAppCampaignRecipient.id.asc())
        .limit(max(1, min(int(batch_size or 50), 200)))
    ).scalars().all()
    if not recipients:
        campaign.status = "sent" if (campaign.sent_count or 0) else campaign.status
        campaign.sent_at = campaign.sent_at or datetime.utcnow()
        db.commit()
        return RedirectResponse(f"/admin/whatsapp-campaigns?campaign_id={campaign.id}&success=Nenhum%20destinatário%20pendente", status_code=303)

    sent = 0
    failed = 0
    now = datetime.utcnow()
    campaign.status = "sending"
    for recipient in recipients:
        ok, reason, wa_message_id = send_campaign_template_whatsapp(
            to_phone=recipient.phone,
            customer_name=recipient.customer_name or "",
            template_name=campaign.template_name,
            language=campaign.template_language,
        )
        if ok:
            customer = db.get(Customer, recipient.customer_id) if recipient.customer_id else None
            conversation = get_or_create_whatsapp_conversation(db, phone=recipient.phone, customer=customer)
            sent_at = datetime.utcnow()
            message = WhatsAppMessage(
                conversation_id=conversation.id,
                customer_id=customer.id if customer else None,
                phone=recipient.phone,
                direction="outbound",
                wa_message_id=wa_message_id,
                message_type="template",
                text=_campaign_message_text(campaign, recipient.customer_name),
                raw_payload=json.dumps({"campaign_id": campaign.id, "template_name": campaign.template_name}, ensure_ascii=False),
                status="accepted",
                timestamp=sent_at,
            )
            db.add(message)
            db.flush()
            recipient.status = "sent"
            recipient.error = None
            recipient.sent_at = sent_at
            recipient.conversation_id = conversation.id
            recipient.message_id = message.id
            conversation.last_message_at = sent_at
            conversation.last_outbound_at = sent_at
            conversation.updated_at = sent_at
            sent += 1
        else:
            recipient.status = "failed"
            recipient.error = reason[:180]
            failed += 1
        db.add(recipient)

    campaign.sent_count = int(campaign.sent_count or 0) + sent
    campaign.failed_count = int(campaign.failed_count or 0) + failed
    campaign.sent_at = now
    remaining = db.scalar(
        select(func.count(WhatsAppCampaignRecipient.id)).where(
            WhatsAppCampaignRecipient.campaign_id == campaign.id,
            WhatsAppCampaignRecipient.status == "pending",
        )
    ) or 0
    campaign.status = "sent" if remaining == 0 and failed == 0 else "partial" if sent else "failed"
    log_admin_action(
        db,
        action="whatsapp_campaign_batch_sent",
        actor_attendant_id=admin.id,
        entity_type="whatsapp_campaign",
        entity_id=campaign.id,
        details={"sent": sent, "failed": failed, "remaining": remaining},
        request=request,
    )
    db.commit()
    return RedirectResponse(
        f"/admin/whatsapp-campaigns?campaign_id={campaign.id}&success=Lote%20enviado:%20{sent}%20sucesso,%20{failed}%20falha(s),%20{remaining}%20pendente(s)",
        status_code=303,
    )


@router.post("/whatsapp-campaigns/{campaign_id}/delete")
def delete_whatsapp_campaign(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/atendente/login", status_code=303)

    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        return RedirectResponse("/admin/whatsapp-campaigns?err=Campanha%20não%20encontrada", status_code=303)

    campaign_name = campaign.name or "Campanha WhatsApp"
    recipient_total = db.scalar(
        select(func.count(WhatsAppCampaignRecipient.id)).where(
            WhatsAppCampaignRecipient.campaign_id == campaign.id
        )
    ) or 0
    log_admin_action(
        db,
        action="whatsapp_campaign_deleted",
        actor_attendant_id=admin.id,
        entity_type="whatsapp_campaign",
        entity_id=campaign.id,
        details={"name": campaign_name, "recipients": recipient_total},
        request=request,
    )
    db.delete(campaign)
    db.commit()
    return RedirectResponse(
        f"/admin/whatsapp-campaigns?success={quote('Campanha excluída: ' + campaign_name)}",
        status_code=303,
    )


@router.get("/app", response_class=HTMLResponse)
def admin_app_backend(
    request: Request,
    devices_page: int = 1,
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
    devices_page = max(int(devices_page or 1), 1)
    devices_per_page = 20
    device_total = db.scalar(select(func.count(AppDevice.id))) or 0
    devices = db.execute(
        select(AppDevice)
        .order_by(AppDevice.last_seen_at.desc())
        .offset((devices_page - 1) * devices_per_page)
        .limit(devices_per_page)
    ).scalars().all()
    subscriptions = db.execute(select(PushSubscription).order_by(PushSubscription.updated_at.desc()).limit(80)).scalars().all()
    location_logs = db.execute(select(LocationAccessLog).order_by(LocationAccessLog.created_at.desc()).limit(60)).scalars().all()
    total_customers = db.scalar(select(func.count(Customer.id))) or 0
    customers_with_purchases = db.scalar(select(func.count(Customer.id)).where(Customer.first_purchase_at.is_not(None))) or 0
    total_tx = db.scalar(select(func.count(Transaction.id))) or 0
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.resolved_at.is_(None))) or 0
    map_summary = _commercial_map_summary(db)
    consumption_alerts = _active_consumption_alerts(db, limit=6)

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
            "device_count": device_total,
            "devices_page": devices_page,
            "devices_per_page": devices_per_page,
            "devices_total_pages": max((device_total + devices_per_page - 1) // devices_per_page, 1),
            "active_24h_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.last_seen_at >= since_24h)) or 0,
            "blocked_device_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.is_blocked == True)) or 0,
            "fcm_device_count": db.scalar(select(func.count(AppDevice.id)).where(AppDevice.fcm_token.is_not(None), AppDevice.is_blocked.is_not(True))) or 0,
            "push_active_count": push_active_count,
            "location_allowed_count": location_allowed_count,
            "location_denied_count": location_denied_count,
            "total_customers": total_customers,
            "customers_with_purchases": customers_with_purchases,
            "total_tx": total_tx,
            "open_alerts": open_alerts,
            "conversion_percent": int((customers_with_purchases / total_customers) * 100) if total_customers else 0,
            "map_summary": map_summary,
            "neighborhoods": map_summary["neighborhoods"][:6],
            "campaign_zones": map_summary["campaign_zones"][:3],
            "consumption_alerts": consumption_alerts,
            "push_configured": push_configured(),
            "fcm_configured": fcm_configured(),
            "format_dt": _admin_datetime_label,
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


def _diagnose_fcm_device(db: Session, device: AppDevice | None, admin: Attendant | None = None) -> dict:
    diagnostic = {
        "ok": False,
        "fcm_configured": fcm_configured(),
        "send_attempted": False,
        "send_ok": False,
        "notification_id": None,
        "device": None,
        "related_fcm_devices": [],
        "checks": [],
        "probable_reason": "",
    }
    if not device:
        diagnostic["probable_reason"] = "Dispositivo nao encontrado."
        diagnostic["checks"].append({"name": "device_exists", "ok": False})
        return diagnostic

    diagnostic["device"] = {
        "id": device.id,
        "device_id": device.device_id,
        "customer_id": device.customer_id,
        "customer_name": device.customer.name if device.customer else "",
        "platform": device.platform or "",
        "notification_permission": device.notification_permission or "",
        "has_fcm_token": bool(device.fcm_token),
        "is_blocked": bool(device.is_blocked),
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
    }
    if device.customer_id:
        related_devices = db.execute(
            select(AppDevice).where(
                AppDevice.customer_id == device.customer_id,
                AppDevice.id != device.id,
                AppDevice.fcm_token.is_not(None),
                AppDevice.is_blocked.is_not(True),
            )
        ).scalars().all()
        diagnostic["related_fcm_devices"] = [
            {
                "id": item.id,
                "device_id": item.device_id,
                "platform": item.platform or "",
                "notification_permission": item.notification_permission or "",
                "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
            }
            for item in related_devices
        ]
    checks = [
        ("firebase_configured", diagnostic["fcm_configured"], "Firebase FCM nao esta configurado no backend."),
        ("device_not_blocked", not bool(device.is_blocked), "Dispositivo bloqueado no painel."),
        ("has_fcm_token", bool(device.fcm_token), "Celular nao registrou token FCM."),
        ("customer_linked", device.customer_id is not None, "Token FCM esta sem cliente vinculado."),
        (
            "permission_not_denied",
            (device.notification_permission or "").lower() != "denied",
            "Permissao de notificacao esta negada no celular.",
        ),
    ]
    for name, ok, reason in checks:
        diagnostic["checks"].append({"name": name, "ok": bool(ok), "reason": "" if ok else reason})
        if not ok and not diagnostic["probable_reason"]:
            diagnostic["probable_reason"] = reason

    if diagnostic["probable_reason"]:
        if not device.fcm_token and diagnostic["related_fcm_devices"]:
            diagnostic["probable_reason"] = (
                "Este registro nao tem token FCM, mas existe outro dispositivo do mesmo cliente com token. "
                "Teste o dispositivo relacionado ou instale a nova versao para unificar o device_id."
            )
        return diagnostic

    notification = AppNotification(
        title="Central Aguas",
        body="Teste de notificacao do app Central Aguas. Se chegou aqui, o FCM deste celular esta funcionando.",
        target="diagnostic",
        url="/app?screen=orders&skip_splash=1",
        status="queued",
        created_by_attendant_id=admin.id if admin else None,
    )
    db.add(notification)
    db.flush()
    diagnostic["notification_id"] = notification.id
    diagnostic["send_attempted"] = True

    ok = send_fcm(device, notification.title, notification.body, notification.url or "/app", notification.id)
    notification.sent_count = 1 if ok else 0
    notification.failed_count = 0 if ok else 1
    notification.status = "sent" if ok else "failed"
    notification.sent_at = datetime.utcnow()
    db.commit()

    diagnostic["send_ok"] = bool(ok)
    diagnostic["ok"] = bool(ok)
    if not ok:
        diagnostic["probable_reason"] = "Firebase recusou ou nao entregou o token. Veja o log do Coolify para o erro FCM detalhado."
    return diagnostic


@router.post("/app/devices/{device_id}/test-push", response_class=JSONResponse)
def admin_app_device_test_push(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    device = db.get(AppDevice, device_id)
    return _diagnose_fcm_device(db, device, admin)


@router.get("/app/grj-order-test", response_class=JSONResponse)
def admin_app_grj_order_test(
    request: Request,
    client_order_id: str = "",
    grj_order_id: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    references = [
        item.strip()
        for item in client_order_id.replace(";", ",").split(",")
        if item.strip()
    ][:50]
    grj_ids = [
        item.strip()
        for item in grj_order_id.replace(";", ",").split(",")
        if item.strip().isdigit()
    ][:50]
    token = settings.CENTRAL_AGUAS_APP_TOKEN.strip()
    diagnostic = {
        "ok": False,
        "config": {
            "orders_api_url": settings.CENTRAL_AGUAS_ORDERS_API_URL,
            "app_status_url": _grj_app_status_url(),
            "token_configured": bool(token),
        },
        "input": {
            "client_order_ids": references,
            "grj_order_ids": grj_ids,
        },
        "request_url": "",
        "http_status": None,
        "payload_status": "",
        "orders_count": 0,
        "orders": [],
        "error": "",
        "raw_preview": "",
    }
    if not references and not grj_ids:
        diagnostic["error"] = "Informe client_order_id=APP-... ou grj_order_id=123."
        return diagnostic
    if not token:
        diagnostic["error"] = "CENTRAL_AGUAS_APP_TOKEN nao configurado no app."
        return diagnostic

    query = urllib.parse.urlencode(
        {
            "client_order_ids": ",".join(references),
            "grj_order_ids": ",".join(grj_ids),
        }
    )
    url = f"{_grj_app_status_url()}?{query}"
    diagnostic["request_url"] = url
    api_request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(api_request, timeout=12) as api_response:
            diagnostic["http_status"] = api_response.status
            raw_body = api_response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        diagnostic["http_status"] = exc.code
        raw_body = exc.read().decode("utf-8", errors="replace")
        diagnostic["error"] = f"GRJ respondeu HTTP {exc.code}."
    except (urllib.error.URLError, TimeoutError) as exc:
        diagnostic["error"] = f"Falha ao chamar GRJ: {exc}"
        return diagnostic

    diagnostic["raw_preview"] = raw_body[:2000]
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        diagnostic["error"] = diagnostic["error"] or f"Resposta do GRJ nao e JSON valido: {exc}"
        return diagnostic

    orders = payload.get("data") if isinstance(payload, dict) else []
    diagnostic["payload_status"] = str(payload.get("status", "")) if isinstance(payload, dict) else ""
    diagnostic["orders"] = orders if isinstance(orders, list) else []
    diagnostic["orders_count"] = len(diagnostic["orders"])
    diagnostic["ok"] = 200 <= int(diagnostic["http_status"] or 0) < 300 and diagnostic["payload_status"] == "ok"
    if diagnostic["ok"] and diagnostic["orders_count"] == 0:
        diagnostic["error"] = "GRJ respondeu OK, mas nao encontrou pedido para essa referencia."
    return diagnostic


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
    log_admin_action(
        db,
        action="app_device_block_toggled",
        actor_attendant_id=admin.id,
        entity_type="app_device",
        entity_id=device.id,
        details={"device_id": device.device_id, "is_blocked": bool(device.is_blocked)},
        request=request,
    )
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
    log_admin_action(
        db,
        action="push_subscription_toggled",
        actor_attendant_id=admin.id,
        entity_type="push_subscription",
        entity_id=subscription.id,
        details={"device_id": subscription.device_id, "active": bool(subscription.active)},
        request=request,
    )
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
    redirect_to = "/admin/coupons"

    code_normalized = code.strip().upper()
    if not code_normalized:
        return RedirectResponse(f"{redirect_to}?err=Código%20obrigatório", status_code=303)

    existing = db.scalar(select(Coupon).where(Coupon.code == code_normalized, Coupon.id != coupon_id))
    if existing:
        return RedirectResponse(f"{redirect_to}?err=Código%20de%20cupom%20já%20existe", status_code=303)

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
    db.flush()
    log_admin_action(
        db,
        action="coupon_saved",
        actor_attendant_id=admin.id,
        entity_type="coupon",
        entity_id=coupon.id,
        details={"code": coupon.code, "active": bool(coupon.active), "discount_type": coupon.discount_type},
        request=request,
    )
    db.commit()

    return RedirectResponse(f"{redirect_to}?success=Cupom%20salvo", status_code=303)


@router.post("/coupons/{coupon_id}/toggle")
def toggle_coupon(coupon_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    coupon = db.get(Coupon, coupon_id)
    if coupon:
        coupon.active = not coupon.active
        log_admin_action(
            db,
            action="coupon_toggled",
            actor_attendant_id=admin.id,
            entity_type="coupon",
            entity_id=coupon.id,
            details={"code": coupon.code, "active": bool(coupon.active)},
            request=request,
        )
        db.commit()
    redirect_to = "/admin/coupons"
    return RedirectResponse(redirect_to, status_code=303)


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
    referer = request.headers.get("referer", "")
    if "/admin/notifications" in referer:
        redirect_to = "/admin/notifications"
    elif "/admin/app" in referer:
        redirect_to = "/admin/app"
    else:
        redirect_to = "/admin/notifications"

    try:
        notification = AppNotification(
            title=title.strip()[:120],
            body=body.strip(),
            target=target if target in {"all", "customers"} else "all",
            url=url.strip() or "/app",
            status="queued",
            created_by_attendant_id=admin.id,
        )
        db.add(notification)
        db.flush()
        log_admin_action(
            db,
            action="notification_created",
            actor_attendant_id=admin.id,
            entity_type="app_notification",
            entity_id=notification.id,
            details={"title": notification.title, "target": notification.target, "url": notification.url},
            request=request,
        )
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
            return RedirectResponse(f"{redirect_to}?success=Notificação%20registrada.%20Configure%20Firebase%20ou%20VAPID%20para%20envio%20push.", status_code=303)
        if (notification.sent_count or 0) > 0:
            return RedirectResponse(f"{redirect_to}?success=Notificação%20enviada%20para%20{notification.sent_count}%20dispositivo(s)", status_code=303)
        return RedirectResponse(f"{redirect_to}?err=Notificação%20registrada,%20mas%20nenhum%20dispositivo%20aceitou%20o%20envio.%20Confira%20os%20logs%20do%20Coolify.", status_code=303)
    except Exception as exc:
        db.rollback()
        logger.exception("Admin notification send failed: %s", exc)
        return RedirectResponse(f"{redirect_to}?err=Falha%20ao%20registrar%20notificação.%20Confira%20os%20logs%20do%20Coolify.", status_code=303)


@router.get("/notifications/send")
def send_app_notification_get():
    return RedirectResponse("/admin/notifications", status_code=303)


@router.post("/notifications/banners")
def create_app_banner(
    request: Request,
    title: str = Form(...),
    body: str = Form(""),
    image_url: str = Form(""),
    banner_image: UploadFile | None = File(None),
    link_url: str = Form(""),
    target: str = Form("all"),
    display_order: int = Form(0),
    active: str = Form("on"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)

    try:
        image = _normalize_banner_image(image_url, banner_image)
    except ValueError as exc:
        return RedirectResponse(f"/admin/notifications?tab=banners&err={quote(str(exc))}", status_code=303)

    banner = AppBanner(
        title=title.strip()[:120] or "Promoção",
        body=body.strip() or None,
        image_url=image[:500],
        link_url=(link_url.strip() or None),
        target=target if target in {"all", "customers"} else "all",
        display_order=int(display_order or 0),
        active=active == "on",
        created_by_attendant_id=admin.id,
    )
    db.add(banner)
    db.flush()
    log_admin_action(
        db,
        action="app_banner_created",
        actor_attendant_id=admin.id,
        entity_type="app_banner",
        entity_id=banner.id,
        details={"title": banner.title, "target": banner.target, "active": bool(banner.active)},
        request=request,
    )
    db.commit()
    return RedirectResponse("/admin/notifications?tab=banners&success=Banner%20salvo", status_code=303)


@router.post("/notifications/banners/{banner_id}/toggle")
def toggle_app_banner(banner_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    banner = db.get(AppBanner, banner_id)
    if not banner:
        return RedirectResponse("/admin/notifications?tab=banners&err=Banner%20não%20encontrado", status_code=303)
    was_inactive = not bool(banner.active)
    banner.active = not bool(banner.active)
    if was_inactive and banner.active:
        db.execute(delete(AppBannerEvent).where(AppBannerEvent.banner_id == banner.id))
    log_admin_action(
        db,
        action="app_banner_toggled",
        actor_attendant_id=admin.id,
        entity_type="app_banner",
        entity_id=banner.id,
        details={"title": banner.title, "active": bool(banner.active)},
        request=request,
    )
    db.commit()
    return RedirectResponse("/admin/notifications?tab=banners&success=Banner%20atualizado", status_code=303)


@router.post("/notifications/promotions")
def create_app_promotion(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    rule_type: str = Form("custom"),
    rule_config: str = Form(""),
    valid_from: str = Form(""),
    valid_until: str = Form(""),
    display_order: int = Form(0),
    active: str = Form("on"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    allowed_rule_types = {"bonus_points", "coupon_once", "banner_offer", "custom"}
    promotion = AppPromotion(
        title=title.strip()[:120] or "Promoção do app",
        description=description.strip() or None,
        rule_type=rule_type if rule_type in allowed_rule_types else "custom",
        rule_config=rule_config.strip() or None,
        valid_from=_parse_optional_datetime(valid_from),
        valid_until=_parse_optional_datetime(valid_until),
        display_order=int(display_order or 0),
        active=active == "on",
        created_by_attendant_id=admin.id,
    )
    db.add(promotion)
    db.flush()
    log_admin_action(
        db,
        action="app_promotion_created",
        actor_attendant_id=admin.id,
        entity_type="app_promotion",
        entity_id=promotion.id,
        details={"title": promotion.title, "rule_type": promotion.rule_type, "active": bool(promotion.active)},
        request=request,
    )
    db.commit()
    return RedirectResponse("/admin/notifications?tab=promotions&success=Promoção%20do%20app%20salva", status_code=303)


@router.post("/notifications/promotions/{promotion_id}/toggle")
def toggle_app_promotion(promotion_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    promotion = db.get(AppPromotion, promotion_id)
    if not promotion:
        return RedirectResponse("/admin/notifications?tab=promotions&err=Promoção%20não%20encontrada", status_code=303)
    promotion.active = not bool(promotion.active)
    log_admin_action(
        db,
        action="app_promotion_toggled",
        actor_attendant_id=admin.id,
        entity_type="app_promotion",
        entity_id=promotion.id,
        details={"title": promotion.title, "active": bool(promotion.active)},
        request=request,
    )
    db.commit()
    return RedirectResponse("/admin/notifications?tab=promotions&success=Promoção%20atualizada", status_code=303)


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
    return RedirectResponse("/admin/coupons?err=Produtos%20e%20preços%20são%20controlados%20pelo%20sistema%20GRJ", status_code=303)
    is_active = (active == "on")
    if product_id > 0:
        p = db.get(Product, product_id)
        if not p:
            return RedirectResponse("/admin/coupons?err=Produto%20não%20encontrado%20no%20cadastro%20local", status_code=303)
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
    return RedirectResponse("/admin/coupons?success=Produto%20salvo", status_code=303)

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
def geocode_pending(request: Request, force: str = Form(""), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin: return RedirectResponse("/atendente/login", status_code=303)
    query = select(Customer).where(Customer.street.is_not(None))
    if force != "1":
        query = query.where(Customer.lat.is_(None))
    pending = db.execute(query.order_by(Customer.id.asc())).scalars().all()
    updated = 0
    for c in pending:
        rua = c.street if c.street.lower().startswith(('rua', 'av', 'alameda')) else f"Rua {c.street}"
        resultado = geocode_structured(
            street=rua,
            number=c.number,
            neighborhood=c.neighborhood,
            city=c.city or "Votuporanga",
            state=c.state or "SP",
            cep=c.cep,
        )
        if resultado:
            c.lat, c.lon = resultado
            updated += 1
            db.commit()
        _time.sleep(1.2)
    return RedirectResponse(f"/admin/map?success={quote(f'Coordenadas atualizadas: {updated}')}", status_code=303)

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
    return {"name": customer.name, "phone": customer.phone or "", "total_points": customer.points or 0, "history": history}
