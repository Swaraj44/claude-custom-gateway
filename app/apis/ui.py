"""Web UI route."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"
INDEX_HTML = _INDEX_HTML_PATH.read_text(encoding="utf-8")


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)
