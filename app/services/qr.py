import io
import qrcode
from fastapi.responses import Response

def qr_png_response(data: str) -> Response:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
