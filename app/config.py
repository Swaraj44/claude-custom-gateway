import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


def _version_key(path: Path) -> Tuple[int, ...]:
    # ".../anthropic.claude-code-2.1.318-linux-x64/..." -> (2, 1, 318)
    name = path.parents[2].name if len(path.parents) > 2 else ""
    match = re.search(r"-(\d+(?:\.\d+)*)", name)
    return tuple(int(p) for p in match.group(1).split(".")) if match else ()


def _editor_bundled_bins() -> List[Path]:
    """Native CLI binaries shipped inside the Claude Code editor extension, newest first."""
    found: List[Path] = []
    for editor_dir in (".vscode", ".vscode-server", ".vscode-oss", ".cursor", ".windsurf"):
        ext_root = Path.home() / editor_dir / "extensions"
        for name in ("claude", "claude.exe"):
            found.extend(ext_root.glob("anthropic.claude-code-*/resources/native-binary/" + name))
    return sorted(found, key=_version_key, reverse=True)


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(str(path), os.X_OK)


def _find_claude_bin() -> str:
    override = os.environ.get("CLAUDE_SERVICE_CLAUDE_BIN", "").strip()
    if override:
        return shutil.which(override) or os.path.expanduser(override)
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude.exe",
        home / ".local" / "bin" / "claude",
        home / ".claude" / "local" / "claude",
        home / ".npm-global" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
    ]
    candidates += _editor_bundled_bins()
    for c in candidates:
        if _is_executable(c):
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
