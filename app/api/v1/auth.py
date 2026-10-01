from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...auth import get_current_customer_id, login_customer, logout_customer
from ...database import get_db
from ...models import Customer
from ...schemas.auth import (
    CustomerLoginRequest,
    CustomerRegisterRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyResetCodeRequest,
)
from ...schemas.common import api_error, api_success
from ...services.account_recovery import (
    GENERIC_RESET_MESSAGE,
    request_password_reset_code,
    reset_customer_password_with_token,
    verify_password_reset_code,
)
from ...services.auth_service import authenticate_customer, create_customer_account
from ...services.loyalty import card_progress, cards_completed, points_balance
from ...services.whatsapp import send_password_reset_code_whatsapp

router = APIRouter()


def _request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:80] or None
    if request.client:
        return request.client.host[:80]
    return None


def _customer_payload(db: Session, customer: Customer) -> dict:
    balance = points_balance(db, customer.id)
    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "birth_date": customer.birth_date.isoformat() if customer.birth_date else None,
        "referral_code": customer.referral_code,
        "must_change_password": bool(customer.must_change_password),
        "address": {
            "cep": customer.cep,
            "street": customer.street,
            "number": customer.number,
            "complement": customer.complement,
            "neighborhood": customer.neighborhood,
            "city": customer.city,
            "state": customer.state,
        },
        "loyalty": {
            "balance": balance,
            "card_progress": card_progress(balance),
            "cards_completed": cards_completed(balance),
        },
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


@router.get("/session")
def current_session(request: Request, db: Session = Depends(get_db)):
    customer_id = get_current_customer_id(request)
    if not customer_id:
        return api_success({"authenticated": False})
    customer = db.get(Customer, int(customer_id))
    if not customer:
        logout_customer(request)
        return api_success({"authenticated": False})
    return api_success({"authenticated": True, "customer": _customer_payload(db, customer)})


@router.post("/login")
def login(payload: CustomerLoginRequest, request: Request, db: Session = Depends(get_db)):
    customer = authenticate_customer(db, phone=payload.phone, password=payload.password)
    if not customer:
        return api_error("INVALID_CREDENTIALS", "Telefone ou senha invalidos.", status_code=401)
    login_customer(request, customer.id)
    return api_success({"customer": _customer_payload(db, customer)})


@router.post("/register")
def register(payload: CustomerRegisterRequest, request: Request, db: Session = Depends(get_db)):
    if payload.password != payload.confirm_password:
        return api_error("PASSWORD_CONFIRMATION_MISMATCH", "As senhas nao coincidem.", status_code=422)
    try:
        customer = create_customer_account(
            db,
            name=payload.name,
            phone=payload.phone,
            password=payload.password,
            birth_date=payload.birth_date,
            zip_code=payload.zip_code,
            street=payload.street,
            number=payload.number,
            complement=payload.complement,
            neighborhood=payload.neighborhood,
            ref_code=payload.ref_code,
        )
    except ValueError as exc:
        code = str(exc)
        messages = {
            "PHONE_REQUIRED": "Telefone obrigatorio.",
            "PHONE_ALREADY_REGISTERED": "Este telefone ja esta cadastrado.",
            "PASSWORD_MUST_BE_4_DIGITS": "A senha deve ter exatamente 4 digitos numericos.",
            "BIRTH_DATE_INVALID": "Data de nascimento invalida.",
            "CEP_INVALID": "CEP invalido.",
            "CEP_OUT_OF_SERVICE_AREA": "Cadastro disponivel apenas para Votuporanga-SP.",
        }
        return api_error(code, messages.get(code, "Dados invalidos."), status_code=422)

    login_customer(request, customer.id)
    return api_success({"customer": _customer_payload(db, customer)}, status_code=201)


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    customer, code, _reason = request_password_reset_code(
        db,
        phone=payload.phone,
        request_ip=_request_ip(request),
    )
    if not customer or not code:
        db.rollback()
        return api_success({"message": GENERIC_RESET_MESSAGE})

    sent, _send_reason = send_password_reset_code_whatsapp(to_phone=customer.phone, code=code)
    if not sent:
        db.rollback()
        return api_success({"message": GENERIC_RESET_MESSAGE})

    db.commit()
    return api_success({"message": GENERIC_RESET_MESSAGE})


@router.post("/verify-reset-code")
def verify_reset_code(payload: VerifyResetCodeRequest, db: Session = Depends(get_db)):
    try:
        reset_token = verify_password_reset_code(db, phone=payload.phone, code=payload.code)
        db.commit()
    except ValueError as exc:
        db.commit()
        code = str(exc)
        if code == "too_many_attempts":
            return api_error("RESET_CODE_TOO_MANY_ATTEMPTS", "Codigo invalido ou expirado.", status_code=400)
        return api_error("RESET_CODE_INVALID", "Codigo invalido ou expirado.", status_code=400)
    return api_success({"resetToken": reset_token})


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(payload.new_password) != 4 or not payload.new_password.isdigit():
        return api_error("PASSWORD_MUST_BE_4_DIGITS", "A senha deve ter exatamente 4 digitos numericos.", status_code=422)
    try:
        reset_customer_password_with_token(
            db,
            token=payload.reset_token,
            new_password=payload.new_password,
        )
        db.commit()
    except ValueError:
        db.rollback()
        return api_error("RESET_TOKEN_INVALID", "Token invalido ou expirado.", status_code=400)
    return api_success({"passwordChanged": True})


@router.post("/logout")
def logout(request: Request):
    logout_customer(request)
    return api_success({"authenticated": False})
