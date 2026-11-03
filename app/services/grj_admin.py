import json
import urllib.parse
import urllib.request

from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..config import settings

GRJ_ORIGINS = {"https://www.grupogrj.com.br", "https://grupogrj.com.br"}
GRJ_COOKIE = "__Host-central_aguas_grj"
GRJ_SESSION_MAX_AGE = 3600
ADMIN_PATHS = {
    "painel": "/admin", "clientes": "/admin/customers", "cupons": "/admin/coupons",
    "notificacoes": "/admin/notifications", "whatsapp": "/admin/whatsapp-campaigns?tab=messages",
    "backend": "/admin/app",
}


def _serializer():
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt="grj-admin-session-v1")


def grj_attendant_id(request):
    value = getattr(request, "cookies", {}).get(GRJ_COOKIE)
    if not value:
        return None
    try:
        data = _serializer().loads(value, max_age=GRJ_SESSION_MAX_AGE)
        attendant_id = data.get("attendant_id") if isinstance(data, dict) else None
        return attendant_id if type(attendant_id) is int and attendant_id > 0 else None
    except BadSignature:
        return None


def set_grj_session(response, attendant_id):
    value = _serializer().dumps({"attendant_id": attendant_id})
    response.headers.append("set-cookie", f"{GRJ_COOKIE}={value}; Max-Age={GRJ_SESSION_MAX_AGE}; Path=/; Secure; HttpOnly; SameSite=None; Partitioned")


def clear_grj_session(response):
    response.headers.append("set-cookie", f"{GRJ_COOKIE}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=None; Partitioned")


def redeem_grj_code(code):
    token = settings.CENTRAL_AGUAS_APP_TOKEN.strip()
    if not token:
        raise RuntimeError("GRJ integration is not configured")
    url = urllib.parse.urljoin(settings.CENTRAL_AGUAS_PRODUCTS_API_URL, "admin-grants/redeem")
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname == "grupogrj.com.br":
        url = urllib.parse.urlunparse(parsed._replace(netloc="www.grupogrj.com.br"))
    request = urllib.request.Request(
        url, data=json.dumps({"code": code}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read(65536).decode())
    if not isinstance(result, dict) or result.get("status") != "ok" or not isinstance(result.get("data"), dict):
        raise ValueError("Invalid GRJ access response")
    return result["data"]
