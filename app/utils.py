#Shared HTTP helpers: JSON error responses and SSE framing
import json

from fastapi.responses import JSONResponse


def error(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": message})


def sse(obj: dict) -> bytes:
    return b"data: " + json.dumps(obj).encode("utf-8") + b"\n\n"
