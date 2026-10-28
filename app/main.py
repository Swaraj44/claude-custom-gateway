import shutil
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import claude_bin, settings
from app.apis import api_router
from app import payload_logging
from app.payload_logging import PayloadLoggingMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Claude Custom Gateway", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PayloadLoggingMiddleware)
    app.include_router(api_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        messages = [e.get("msg", "invalid value") for e in exc.errors()]
        message = "; ".join(messages) or "invalid request body"
        if request.url.path.startswith("/v1"):
            content = {"error": {"message": message, "type": "invalid_request_error", "code": 400}}
            return JSONResponse(status_code=400, content=content)
        return JSONResponse(status_code=400, content={"error": message})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        message = str(exc.detail)
        if request.url.path.startswith("/v1"):
            content = {"error": {"message": message, "type": "api_error", "code": exc.status_code}}
            return JSONResponse(status_code=exc.status_code, content=content)
        return JSONResponse(status_code=exc.status_code, content={"error": message})

    return app


app = create_app()


def main() -> None:
    if not Path(claude_bin()).is_file() and shutil.which(claude_bin()) is None:
        print("warning: 'claude' CLI not found on PATH; requests will fail until it is available", file=sys.stderr)
    print("Claude Custom Gateway (FastAPI) running")
    print("  Web UI:    http://%s:%d/" % (settings.host, settings.port))
    print("  Chat API:  POST http://%s:%d/api/chat" % (settings.host, settings.port))
    print("  Stream:    POST http://%s:%d/api/chat/stream  (SSE)" % (settings.host, settings.port))
    print("  OpenAI:    http://%s:%d/v1  (models + chat/completions)" % (settings.host, settings.port))
    print("  Health:    GET  http://%s:%d/health" % (settings.host, settings.port))
    print("  Docs:      GET  http://%s:%d/docs" % (settings.host, settings.port))
    print("  Kilo Code: use Base URL http://%s:%d/v1 with an 'OpenAI Compatible' custom provider" % (settings.host, settings.port))
    
    if settings.host in ("0.0.0.0", "::"):
        print("  Note:      listening on all interfaces — use http://127.0.0.1:%d/ locally or http://<your-ip>:%d/ from your network" % (settings.port, settings.port))
    print("  Payloads:  %s" % ("logging requests/responses" if payload_logging.enabled else "not logged"))
    if settings.api_key:
        print("  Auth:      API key required (CLAUDE_SERVICE_API_KEY is set)")
    else:
        print("warning: CLAUDE_SERVICE_API_KEY is empty, so /api/* and /v1/* accept requests without a key;"
              " set it in .env (see .env.example)", file=sys.stderr)
    print("  Claude:    %s | timeout: %ds | models: %s"
          % (claude_bin(), settings.timeout, ", ".join(settings.models)))
    print("Press Ctrl+C to stop")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


def main_pro() -> None:
    payload_logging.enabled = False
    main()


def main_debug() -> None:
    payload_logging.enabled = True
    main()


if __name__ == "__main__":
    main()
