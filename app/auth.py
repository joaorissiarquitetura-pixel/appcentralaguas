from fastapi import Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from .models import Customer, Attendant
from .security import verify_password

# Session keys
CUSTOMER_SESSION_KEY = "customer_id"
ATTENDANT_SESSION_KEY = "attendant_id"

def login_customer(request: Request, customer_id: int):
    request.session[CUSTOMER_SESSION_KEY] = customer_id

def logout_customer(request: Request):
    request.session.pop(CUSTOMER_SESSION_KEY, None)

def get_current_customer_id(request: Request) -> int | None:
    return request.session.get(CUSTOMER_SESSION_KEY)

def login_attendant(request: Request, attendant_id: int):
    request.session[ATTENDANT_SESSION_KEY] = attendant_id

def logout_attendant(request: Request):
    request.session.pop(ATTENDANT_SESSION_KEY, None)

def get_current_attendant_id(request: Request) -> int | None:
    return request.session.get(ATTENDANT_SESSION_KEY)

def require_customer(request: Request) -> int:
    cid = get_current_customer_id(request)
    if not cid:
        raise PermissionError("not_authenticated")
    return int(cid)

def require_attendant(request: Request) -> int:
    aid = get_current_attendant_id(request)
    if not aid:
        raise PermissionError("not_authenticated")
    return int(aid)

def is_admin(attendant: Attendant) -> bool:
    return attendant.role == "admin"
