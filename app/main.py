import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import SessionLocal
from .init_db import create_tables, seed_if_needed
from .routers.admin import router as admin_router
from .routers.attendant import router as attendant_router
from .routers.customer import router as customer_router
from .routers.gotinha import router as gotinha_router
from .routers.public import router as public_router
from .schema_updates import ensure_runtime_schema_updates

load_dotenv()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.BUSINESS_NAME)
templates = Jinja2Templates(directory="app/templates")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    same_site=settings.SESSION_COOKIE_SAME_SITE,
    https_only=settings.SESSION_COOKIE_SECURE,
    max_age=settings.SESSION_MAX_AGE_SECONDS,
    session_cookie="central_aguas_session",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/rqdbw52paf85rzi0jfb5hzbm2j5x0y.html", response_class=FileResponse)
def facebook_domain_verification():
    return FileResponse("rqdbw52paf85rzi0jfb5hzbm2j5x0y.html", media_type="text/html")


# --- EVENTO DE STARTUP ---
@app.on_event("startup")
def on_startup():
    settings.validate_runtime()
    if settings.AUTO_CREATE_TABLES:
        create_tables()
        ensure_runtime_schema_updates()
        db = SessionLocal()
        try:
            seed_if_needed(db)
        finally:
            db.close()


app.include_router(public_router)
app.include_router(customer_router)
app.include_router(gotinha_router)
app.include_router(attendant_router, prefix="/atendente", tags=["Atendente"])
app.include_router(admin_router)


@app.get("/privacidade")
def privacidade(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="privacidade.html",
        context={"business_name": settings.BUSINESS_NAME, "hide_chrome": True},
    )


@app.exception_handler(PermissionError)
def permission_error_handler(request: Request, exc: PermissionError):
    logger.warning("Permission error on %s: %s", request.url.path, exc)
    if str(exc) == "not_authenticated":
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"error": "forbidden"}, status_code=403)


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path, exc_info=exc)
    return JSONResponse({"error": "internal_server_error"}, status_code=500)
