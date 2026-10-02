import logging
import time
from typing import Optional

import requests

from ..config import settings

logger = logging.getLogger(__name__)

USER_AGENT = "CentralAguasApp_Votu (joaorissi.arquitetura@gmail.com)"


def geocode_address_query(address: str) -> Optional[dict]:
    """Busca um endereco pontual, preferindo o Google quando configurado."""
    query = (address or "").strip()
    if len(query) < 5:
        return None

    query_normalized = query.casefold()
    location_parts = [query]
    if settings.SERVICE_AREA_CITY.casefold() not in query_normalized:
        location_parts.append(settings.SERVICE_AREA_CITY)
    if settings.SERVICE_AREA_STATE.casefold() not in query_normalized:
        location_parts.append(settings.SERVICE_AREA_STATE)
    if "brasil" not in query_normalized and "brazil" not in query_normalized:
        location_parts.append("Brasil")
    query = ", ".join(part for part in location_parts if part)

    google_key = settings.GOOGLE_MAPS_API_KEY.strip()
    if google_key:
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": query,
                    "key": google_key,
                    "language": "pt-BR",
                    "region": "br",
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "OK" and payload.get("results"):
                result = payload["results"][0]
                location = result["geometry"]["location"]
                return {
                    "lat": float(location["lat"]),
                    "lon": float(location["lng"]),
                    "label": result.get("formatted_address", query),
                    "provider": "Google Maps",
                    "precision": "precisa" if result.get("geometry", {}).get("location_type") == "ROOFTOP" else "aproximada",
                }
            if payload.get("status") not in {"ZERO_RESULTS", "OK"}:
                logger.warning("Google geocoding returned status=%s", payload.get("status"))
        except Exception as exc:
            logger.warning("Google geocoding failed: %s", exc)

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if payload:
            result = payload[0]
            return {
                "lat": float(result["lat"]),
                "lon": float(result["lon"]),
                "label": result.get("display_name", query),
                "provider": "OpenStreetMap",
                "precision": "aproximada",
            }
    except Exception as exc:
        logger.warning("Fallback geocoding failed for query=%s: %s", query, exc)
    return None


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
