import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _find_claude_bin() -> str:
    override = os.environ.get("CLAUDE_SERVICE_CLAUDE_BIN", "").strip()
    if override:
        # A mangled override (e.g. a Windows path that lost its separators, like 'C:\Users\DELL.local\bin\claude.EXE') must not brick the service: only trust it when it actually resolves to a file.
        if Path(override).is_file() or shutil.which(override):
            return override
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


_claude_bin_cache = ""


def claude_bin() -> str:
    """Current claude CLI path, re-resolved whenever the cached binary disappears.

    The CLI auto-updater replaces ~/.local/bin/claude.exe in place; a path cached at process start can therefore go missing later, which made every request fail with "claude CLI not found" until the service was restarted.
    """
    global _claude_bin_cache
    if not (_claude_bin_cache and Path(_claude_bin_cache).is_file()):
        _claude_bin_cache = _find_claude_bin()
    return _claude_bin_cache


def reset_claude_bin() -> None:
    """Force re-discovery on the next claude_bin() call (e.g. after a spawn failure)."""
    global _claude_bin_cache
    _claude_bin_cache = ""


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 6069
    timeout: int = 600
    # No built-in key: set CLAUDE_SERVICE_API_KEY in .env (empty = auth disabled).
    api_key: str = ""
    models: Tuple[str, ...] = ("sonnet", "opus", "haiku")
    vision_model: str = "sonnet"
    system_prompt_max: int = 100_000
    # System prompt for /v1 requests that send none; keeps the CLI from adding its own ~3k-token coding-agent prompt.
    default_system_prompt: str = "You are a helpful assistant."
    # TTL of the prompt-cache breakpoint placed on the last conversation block
    # ("1h", "5m", or "off"). Lets each turn reuse the previous turn's history.
    prompt_cache_ttl: str = "1h"
    # Optional --effort level for OpenAI-compatible calls (low/medium/high/...).
    effort: str = ""
    cors_origins: Tuple[str, ...] = ("*",)
    log_level: str = "info"
    # Log every request/response body (on under `claude-debug`); cap each logged payload at N chars (0 = no cap).
    log_payloads: bool = False
    log_payload_max: int = 0


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    value = _env(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError("%s must be a whole number, got %r" % (name, value)) from None


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name, "").lower()
    if not value:
        return default
    return value not in ("0", "false", "no", "off")


def _env_list(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    items = tuple(x.strip() for x in _env(name, "").split(",") if x.strip())
    return items or default


def load_settings() -> Settings:
    d = Settings()
    return Settings(
        host=_env("CLAUDE_SERVICE_HOST", d.host) or d.host,
        port=_env_int("CLAUDE_SERVICE_PORT", d.port),
        timeout=_env_int("CLAUDE_SERVICE_TIMEOUT", d.timeout),
        api_key=_env("CLAUDE_SERVICE_API_KEY", d.api_key),
        models=_env_list("CLAUDE_SERVICE_MODELS", d.models),
        vision_model=_env("CLAUDE_SERVICE_VISION_MODEL", d.vision_model) or d.vision_model,
        system_prompt_max=_env_int("CLAUDE_SERVICE_SYSTEM_PROMPT_MAX", d.system_prompt_max),
        default_system_prompt=_env("CLAUDE_SERVICE_DEFAULT_SYSTEM_PROMPT", d.default_system_prompt)
        or d.default_system_prompt,
        prompt_cache_ttl=_env("CLAUDE_SERVICE_PROMPT_CACHE_TTL", d.prompt_cache_ttl).lower() or d.prompt_cache_ttl,
        effort=_env("CLAUDE_SERVICE_EFFORT", d.effort).lower(),
        cors_origins=_env_list("CLAUDE_SERVICE_CORS_ORIGINS", d.cors_origins),
        log_level=_env("CLAUDE_SERVICE_LOG_LEVEL", d.log_level).lower() or d.log_level,
        log_payloads=_env_bool("CLAUDE_SERVICE_LOG_PAYLOADS", d.log_payloads),
        log_payload_max=_env_int("CLAUDE_SERVICE_LOG_PAYLOAD_MAX", d.log_payload_max),
    )


settings = load_settings()
