import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()

@router.get("/sw.js")
def serve_sw():
    if os.path.exists("sw.js"):
        return FileResponse("sw.js", media_type="application/javascript")
    return HTMLResponse("// SW not found", status_code=404)


@router.get("/manifest.json")
def serve_manifest():
    if os.path.exists("manifest.json"):
        return FileResponse("manifest.json", media_type="application/manifest+json")
    return HTMLResponse("{}", status_code=404)


@router.get("/icon-192.png")
def serve_icon_192():
    if os.path.exists("icon-192.png"):
        return FileResponse("icon-192.png", media_type="image/png")
    return HTMLResponse("", status_code=404)


@router.get("/icon-512.png")
def serve_icon_512():
    if os.path.exists("icon-512.png"):
        return FileResponse("icon-512.png", media_type="image/png")
    return HTMLResponse("", status_code=404)


# ================================================================
# === ЭНДПОИНТЫ — ФРОНТЕНД ===
# ================================================================

@router.get("/")
def serve_frontend():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Ошибка: index.html не найден!</h1>",
            status_code=404
        )
