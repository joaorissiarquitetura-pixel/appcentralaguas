from fastapi import APIRouter

from ...config import settings
from ...schemas.common import api_success
from ...services.push import fcm_configured, push_configured

router = APIRouter()


@router.get("/bootstrap")
def app_bootstrap_v1():
    return api_success(
        {
            "push": {
                "web_push_configured": push_configured(),
                "firebase_fcm_configured": fcm_configured(),
                "public_key": settings.VAPID_PUBLIC_KEY,
            },
            "service_area": {
                "city": settings.SERVICE_AREA_CITY,
                "state": settings.SERVICE_AREA_STATE,
                "bounds": {
                    "min_lat": settings.SERVICE_AREA_MIN_LAT,
                    "max_lat": settings.SERVICE_AREA_MAX_LAT,
                    "min_lon": settings.SERVICE_AREA_MIN_LON,
                    "max_lon": settings.SERVICE_AREA_MAX_LON,
                },
            },
        }
    )
