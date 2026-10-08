#ASGI middleware that logs every HTTP request and response payload
import json
import logging
import time

from app.config import settings

logger = logging.getLogger("uvicorn.error.payload")

# Toggled at startup by the claude-pro / claude-debug entry points.
enabled = settings.log_payloads


def _format(body: bytes) -> str:
    if not body:
        return "<empty>"
    text = body.decode("utf-8", errors="replace")
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        pass
    limit = settings.log_payload_max
    if limit and len(text) > limit:
        text = text[:limit] + "... <truncated %d chars>" % (len(text) - limit)
    return text


class PayloadLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        if scope.get("query_string"):
            path += "?" + scope["query_string"].decode("latin-1")
        started = time.monotonic()
        request_body = bytearray()
        request_logged = False
        response_body = bytearray()
        status = 0

        def log_request():
            nonlocal request_logged
            if not request_logged:
                request_logged = True
                logger.info("--> %s %s\n%s", method, path, _format(bytes(request_body)))

        async def logging_receive():
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    log_request()
            return message

        async def logging_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                log_request()  # handlers that never read the body (e.g. GET)
                status = message["status"]
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    logger.info("<-- %s %s %d (%.0f ms)\n%s", method, path, status,
                                (time.monotonic() - started) * 1000, _format(bytes(response_body)))
            await send(message)

        await self.app(scope, logging_receive, logging_send)
