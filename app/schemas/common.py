from fastapi.responses import JSONResponse


def api_success(data=None, *, meta: dict | None = None, status_code: int = 200) -> JSONResponse:
    payload = {"success": True, "data": data if data is not None else {}}
    if meta is not None:
        payload["meta"] = meta
    return JSONResponse(payload, status_code=status_code)


def api_error(code: str, message: str, *, status_code: int = 400, details=None) -> JSONResponse:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({"success": False, "error": error}, status_code=status_code)
