import logging
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Attendant
from ..security import hash_password
from ..services.grj_admin import ADMIN_PATHS, GRJ_ORIGINS, clear_grj_session, redeem_grj_code, set_grj_session

router = APIRouter(prefix="/integracoes/grj")
logger = logging.getLogger(__name__)


@router.post("/acesso")
def grj_admin_access(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    if request.headers.get("origin") not in GRJ_ORIGINS or not 20 <= len(code) <= 128:
        return HTMLResponse("Acesso inválido. Abra novamente o E-commerce no GRJ.", status_code=403)
    try:
        grant = redeem_grj_code(code)
        user = grant.get("user")
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1 or grant.get("section") not in ADMIN_PATHS:
            raise ValueError("Invalid GRJ administrator")
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("GRJ admin access failed (%s)", type(exc).__name__)
        return HTMLResponse("Não foi possível abrir o painel. Volte ao E-commerce no GRJ e tente novamente.", status_code=403)
    bridge_email = f"grj-admin-{user['id']}@integracao.grupogrj.com.br"
    attendant = db.scalar(select(Attendant).where(Attendant.email == bridge_email))
    if not attendant:
        attendant = Attendant(email=bridge_email, name=str(user.get("name") or "Admin GRJ")[:120],
                              role="admin", is_active=True, password_hash=hash_password(secrets.token_urlsafe(48)))
        db.add(attendant)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            attendant = db.scalar(select(Attendant).where(Attendant.email == bridge_email))
    if not attendant or not attendant.is_active or attendant.role != "admin":
        return HTMLResponse("Acesso administrativo indisponível.", status_code=403)
    response = RedirectResponse(ADMIN_PATHS[grant["section"]], status_code=303, headers={"Cache-Control": "no-store"})
    set_grj_session(response, attendant.id)
    return response


@router.get("/sair")
def grj_admin_logout():
    response = HTMLResponse('<p>Painel encerrado. <a href="https://www.grupogrj.com.br/gestao/ecommerce/" target="_top">Voltar ao E-commerce</a></p>', headers={"Cache-Control": "no-store"})
    clear_grj_session(response)
    return response
