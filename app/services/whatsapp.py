import urllib.parse
from ..config import settings

def build_whatsapp_redeem_link(customer_name: str, customer_phone: str, completed_cards: int) -> str:
    number = settings.BUSINESS_WHATSAPP_NUMBER.strip().replace("+","")
    msg = (
        f"Olá! Sou {customer_name} (tel: {customer_phone}). "
        f"Completei {completed_cards} cartão(ões) no {settings.BUSINESS_NAME} "
        f"e gostaria de resgatar meus créditos. 😊"
    )
    return f"https://wa.me/{number}?text={urllib.parse.quote(msg)}"
