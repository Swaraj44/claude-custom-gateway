"""Health-check route."""

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "claude_cli": settings.claude_bin, "timeout_s": settings.timeout}
