"""Health-check route."""

from fastapi import APIRouter

from pathlib import Path

from fastapi import APIRouter

from app.config import claude_bin, settings

router = APIRouter()


@router.get("/health")
def health():
    bin_path = claude_bin()
    return {"status": "ok", "claude_cli": bin_path, "claude_cli_ok": Path(bin_path).is_file(), "timeout_s": settings.timeout}
