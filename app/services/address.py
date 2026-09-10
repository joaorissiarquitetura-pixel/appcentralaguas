import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "CentralAguasApp_Votu (joaorissi.arquitetura@gmail.com)"


def sanitize_cep(cep: str) -> str:
    return "".join(ch for ch in (cep or "") if ch.isdigit())


def lookup_cep(cep: str) -> dict:
    cep8 = sanitize_cep(cep)
    if len(cep8) != 8:
        raise ValueError("CEP invalido")

    response = requests.get(
        f"https://viacep.com.br/ws/{cep8}/json/",
        headers={"User-Agent": USER_AGENT},
        timeout=5,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("erro"):
        raise ValueError("CEP nao encontrado")
    return data


def geocode_structured(
    street: str,
    city: str = "Votuporanga",
    state: str = "SP",
    cep: str | None = None,
) -> Optional[tuple[float, float]]:
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": USER_AGENT}

    prefixos = ["RUA", "AVENIDA", "AV.", "PRACA", "PRAÇA", "ALAMEDA", "TRAVESSA", "RODOVIA"]
    nome_limpo = (street or "").strip()
    for prefix in prefixos:
        if nome_limpo.upper().startswith(prefix):
            nome_limpo = nome_limpo[len(prefix) :].strip()
            break

    tentativas = [
        f"{street}, {city}, {state}, Brasil",
        f"{nome_limpo}, {city}, {state}, Brasil",
    ]
    if cep:
        cep_numeros = sanitize_cep(cep)
        if len(cep_numeros) == 8:
            tentativas.append(f"{cep_numeros[:5]}-{cep_numeros[5:]}, {city}, Brasil")
    tentativas.append(f"{city}, {state}, Brasil")

    for query in tentativas:
        params = {"q": query, "format": "json", "limit": 1}
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            payload = response.json()
            if payload:
                return float(payload[0]["lat"]), float(payload[0]["lon"])
        except Exception as exc:
            logger.warning("Geocoding failed for query=%s: %s", query, exc)
        time.sleep(1.2)

    logger.info("Falling back to no geocoding result for street=%s city=%s cep=%s", street, city, cep)
    return None
