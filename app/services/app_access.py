from __future__ import annotations

from dataclasses import dataclass

from ..config import settings


@dataclass(frozen=True)
class ServiceAreaResult:
    allowed: bool
    reason: str


def check_service_area(lat: float | None, lon: float | None, city: str = "", state: str = "") -> ServiceAreaResult:
    if city and state:
        same_city = city.strip().lower() == settings.SERVICE_AREA_CITY.strip().lower()
        same_state = state.strip().upper() == settings.SERVICE_AREA_STATE.strip().upper()
        if same_city and same_state:
            return ServiceAreaResult(True, "Cidade atendida")

    if lat is None or lon is None:
        return ServiceAreaResult(False, "Localização ainda não confirmada")

    inside_bounds = (
        settings.SERVICE_AREA_MIN_LAT <= lat <= settings.SERVICE_AREA_MAX_LAT
        and settings.SERVICE_AREA_MIN_LON <= lon <= settings.SERVICE_AREA_MAX_LON
    )
    if inside_bounds:
        return ServiceAreaResult(True, "Dentro da área de atendimento")
    return ServiceAreaResult(False, "Fora da área de atendimento")
