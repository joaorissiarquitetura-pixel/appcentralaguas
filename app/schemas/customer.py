from datetime import datetime

from pydantic import BaseModel


class CustomerPublic(BaseModel):
    id: int
    name: str
    phone: str
    birth_date: str | None = None
    referral_code: str | None = None
    must_change_password: bool = False
    address: dict
    loyalty: dict
    created_at: datetime | None = None
