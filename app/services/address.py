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
    number: str | None = None,
    neighborhood: str | None = None,
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

    number_clean = (number or "").strip()
    neighborhood_clean = (neighborhood or "").strip()
    city_clean = (city or "Votuporanga").strip()
    state_clean = (state or "SP").strip()
    street_with_number = ", ".join(part for part in [street, number_clean] if part)
    clean_with_number = ", ".join(part for part in [nome_limpo, number_clean] if part)

    tentativas = [
        ", ".join(part for part in [street_with_number, neighborhood_clean, city_clean, state_clean, "Brasil"] if part),
        ", ".join(part for part in [clean_with_number, neighborhood_clean, city_clean, state_clean, "Brasil"] if part),
        ", ".join(part for part in [street_with_number, city_clean, state_clean, "Brasil"] if part),
        ", ".join(part for part in [street, neighborhood_clean, city_clean, state_clean, "Brasil"] if part),
        f"{street}, {city_clean}, {state_clean}, Brasil",
        f"{nome_limpo}, {city_clean}, {state_clean}, Brasil",
    ]
    if cep:
        cep_numeros = sanitize_cep(cep)
        if len(cep_numeros) == 8:
            tentativas.append(", ".join(part for part in [street_with_number, f"{cep_numeros[:5]}-{cep_numeros[5:]}", city_clean, "Brasil"] if part))
            tentativas.append(f"{cep_numeros[:5]}-{cep_numeros[5:]}, {city_clean}, Brasil")
    tentativas.append(f"{city_clean}, {state_clean}, Brasil")

    seen = set()
    tentativas = [query for query in tentativas if query and not (query in seen or seen.add(query))]

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

    logger.info("Falling back to no geocoding result for street=%s number=%s city=%s cep=%s", street, number, city, cep)
    return None
