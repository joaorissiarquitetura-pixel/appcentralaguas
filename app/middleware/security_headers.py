from collections.abc import Awaitable, Callable

from fastapi import Request, Response


async def security_headers_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    from ..services.grj_admin import GRJ_ORIGINS, grj_attendant_id
    if request.url.path.startswith("/integracoes/grj/") or grj_attendant_id(request):
        if "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' " + " ".join(sorted(GRJ_ORIGINS))
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), microphone=(), camera=()")
    return response
