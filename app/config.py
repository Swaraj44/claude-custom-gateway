import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


def _find_claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude",
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return "claude"


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8000
    timeout: int = 600
    api_key: str = "swaraj"
    models: Tuple[str, ...] = ("sonnet", "opus", "haiku")
    vision_model: str = "sonnet"
    system_prompt_max: int = 100_000
    claude_bin: str = "claude"


def load_settings() -> Settings:
    return Settings(
        host=os.environ.get("CLAUDE_SERVICE_HOST", "0.0.0.0"),
        port=int(os.environ.get("CLAUDE_SERVICE_PORT", "8000")),
        timeout=int(os.environ.get("CLAUDE_SERVICE_TIMEOUT", "600")),
        api_key=os.environ.get("CLAUDE_SERVICE_API_KEY", "swaraj"),
        vision_model=os.environ.get("CLAUDE_SERVICE_VISION_MODEL", "sonnet"),
        claude_bin=_find_claude_bin(),
    )


settings = load_settings()
