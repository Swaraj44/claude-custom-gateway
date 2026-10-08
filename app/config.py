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
    port: int = 6069
    timeout: int = 600
    api_key: str = "swaraj"
    models: Tuple[str, ...] = ("sonnet", "opus", "haiku")
    vision_model: str = "sonnet"
    system_prompt_max: int = 100_000
    # TTL of the prompt-cache breakpoint placed on the last conversation block
    # ("1h", "5m", or "off"). Lets each turn reuse the previous turn's history.
    prompt_cache_ttl: str = "1h"
    # Optional --effort level for OpenAI-compatible calls (low/medium/high/...).
    effort: str = ""
    claude_bin: str = "claude"
    # Log every request/response body (on under `claude-debug`); cap each logged payload at N chars (0 = no cap).
    log_payloads: bool = False
    log_payload_max: int = 0


def load_settings() -> Settings:
    return Settings(
        host=os.environ.get("CLAUDE_SERVICE_HOST", "0.0.0.0"),
        port=int(os.environ.get("CLAUDE_SERVICE_PORT", "6069")),
        timeout=int(os.environ.get("CLAUDE_SERVICE_TIMEOUT", "600")),
        api_key=os.environ.get("CLAUDE_SERVICE_API_KEY", "swaraj"),
        vision_model=os.environ.get("CLAUDE_SERVICE_VISION_MODEL", "sonnet"),
        prompt_cache_ttl=os.environ.get("CLAUDE_SERVICE_PROMPT_CACHE_TTL", "1h").strip().lower(),
        effort=os.environ.get("CLAUDE_SERVICE_EFFORT", "").strip().lower(),
        claude_bin=_find_claude_bin(),
        log_payloads=os.environ.get("CLAUDE_SERVICE_LOG_PAYLOADS", "0").strip().lower() not in ("0", "false", "no", "off"),
        log_payload_max=int(os.environ.get("CLAUDE_SERVICE_LOG_PAYLOAD_MAX", "0")),
    )


settings = load_settings()
