#API-key authentication for protected endpoints

from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings


def check_api_key(request: Request) -> None:
    if not settings.api_key:
        return
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        token = request.headers.get("x-api-key") or ""
    if token != settings.api_key:
        raise StarletteHTTPException(status_code=401, detail="Invalid or missing API key")
