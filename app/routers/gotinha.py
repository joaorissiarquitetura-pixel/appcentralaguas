import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..services.gotinha import GotinhaAssetRegistry, GotinhaEmotion

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/gotinha", response_class=HTMLResponse)
def gotinha_preview(request: Request):
    if settings.is_production and not settings.DEBUG:
        raise HTTPException(status_code=404)

    registry = GotinhaAssetRegistry()
    initial_emotion = GotinhaEmotion.ALEGRIA
    return templates.TemplateResponse(
        request=request,
        name="gotinha.html",
        context={
            "business_name": settings.BUSINESS_NAME,
            "emotions": [emotion.value for emotion in GotinhaEmotion],
            "initial_emotion": initial_emotion.value,
            "initial_asset": registry.emotion_asset(initial_emotion),
            "manifest_json": json.dumps(registry.as_public_payload()),
        },
    )
