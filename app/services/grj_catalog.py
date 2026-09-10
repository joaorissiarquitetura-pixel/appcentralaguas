from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GRJCatalogProduct:
    id: int | None
    codigo: str
    nome: str
    unidade: str
    preco_venda: float
    estoque_disponivel: float
    apelido: str
    imagem_url: str
    raw: dict[str, Any]

    @property
    def external_id(self) -> str:
        return self.codigo or str(self.id or "")

    @property
    def name(self) -> str:
        return self.nome

    @property
    def description(self) -> str:
        if self.apelido:
            return self.apelido
        if self.unidade:
            return f"Produto Central Águas - {self.unidade}."
        return "Produto Central Águas."

    @property
    def pickup_price(self) -> float:
        return self.preco_venda

    @property
    def delivery_price(self) -> float:
        return self.preco_venda

    @property
    def stock_quantity(self) -> float:
        return self.estoque_disponivel

    @property
    def stock_status(self) -> str:
        if self.estoque_disponivel <= 0:
            return "indisponivel"
        if self.estoque_disponivel <= 5:
            return "baixo_estoque"
        return "disponivel"

    @property
    def image_url(self) -> str | None:
        return self.imagem_url or None

    @property
    def active(self) -> bool:
        return bool(self.name.strip() or self.external_id.strip())


class GRJCatalogUnavailable(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.CENTRAL_AGUAS_APP_TOKEN.strip() and settings.CENTRAL_AGUAS_PRODUCTS_API_URL.strip())


def fetch_grj_products(limit: int = 500) -> list[GRJCatalogProduct]:
    if not configured():
        raise GRJCatalogUnavailable("central_aguas_catalog_api_not_configured")

    url = settings.CENTRAL_AGUAS_PRODUCTS_API_URL.strip()
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {settings.CENTRAL_AGUAS_APP_TOKEN.strip()}",
            "Accept": "application/json",
            "User-Agent": "CentralAguasFidelidade/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        reason = getattr(exc, "reason", exc)
        logger.warning("Central Aguas catalog API failed: %s", reason)
        raise GRJCatalogUnavailable(f"central_aguas_catalog_api_failed: {reason}") from exc

    if payload.get("status") != "ok" or not isinstance(payload.get("data"), list):
        raise GRJCatalogUnavailable("central_aguas_catalog_api_invalid_response")

    products = [_normalize_api_product(item) for item in payload["data"][:limit] if isinstance(item, dict)]
    return [product for product in products if product.active]


def product_to_public_dict(product: GRJCatalogProduct) -> dict[str, Any]:
    return {
        "id": product.id,
        "codigo": product.codigo,
        "nome": product.nome,
        "unidade": product.unidade,
        "preco_venda": product.preco_venda,
        "estoque_disponivel": product.estoque_disponivel,
        "apelido": product.apelido,
        "external_id": product.external_id,
        "name": product.name,
        "description": product.description,
        "pickup_price": product.pickup_price,
        "delivery_price": product.delivery_price,
        "stock_quantity": product.stock_quantity,
        "stock_status": product.stock_status,
        "image_url": product.image_url,
        "active": product.active,
        "source": "grj_api",
    }


def _normalize_api_product(row: dict[str, Any]) -> GRJCatalogProduct:
    return GRJCatalogProduct(
        id=_to_int(row.get("id")),
        codigo=_clean_text(row.get("codigo")) or "",
        nome=_clean_text(row.get("nome")) or "Produto Central Águas",
        unidade=_clean_text(row.get("unidade")) or "",
        preco_venda=_to_float(row.get("preco_venda")),
        estoque_disponivel=_to_float(row.get("estoque_disponivel")),
        apelido=_clean_text(row.get("apelido")) or "",
        imagem_url=_image_url_from_row(row),
        raw=row,
    )


def _image_url_from_row(row: dict[str, Any]) -> str:
    for field_name in ("image_url", "imagem_url", "imagem", "foto_url", "url_imagem", "produto_imagem", "img"):
        image_url = _normalize_image_url(row.get(field_name))
        if image_url:
            return image_url
    return ""


def _normalize_image_url(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text.startswith("data:"):
        return text
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith(("http://", "https://")):
        return text

    api_url = settings.CENTRAL_AGUAS_PRODUCTS_API_URL.strip()
    parsed_api_url = urllib.parse.urlparse(api_url)
    if text.startswith("/") and parsed_api_url.scheme and parsed_api_url.netloc:
        base_origin = f"{parsed_api_url.scheme}://{parsed_api_url.netloc}/"
        return urllib.parse.urljoin(base_origin, text)

    base_path = api_url.rsplit("/", 1)[0] + "/" if "/" in api_url else api_url
    return urllib.parse.urljoin(base_path, text)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, str):
        value = value.replace(".", "").replace(",", ".") if "," in value else value
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
