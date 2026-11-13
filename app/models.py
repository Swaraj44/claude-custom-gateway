"""
Model discovery: 
Claude Code fetches its model catalog from Anthropic and caches it under ``<config dir>/cache/model-catalog/*-cc.json``
(config dir is``$CLAUDE_CONFIG_DIR`` or ``~/.claude``). We read that cache so ``/v1/models`` lists every model the CLI offers (e.g. ``claude-opus-5-5``, ``claude-opus-4-6``)

plus the short aliases (``opus``, ``sonnet``, ...), and stays current as the CLI refreshes it. If the cache is missing or unreadable, a static fallback list is used.
"""

import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FALLBACK_MODELS: Tuple[str, ...] = ("sonnet", "opus", "haiku")

# Preferred order for the aliases at the top of the list.
_ALIAS_ORDER = ("sonnet", "opus", "haiku", "fable")

_lock = threading.Lock()
_cache: Dict[str, object] = {"key": None, "models": None}


def claude_config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(os.path.expanduser(override)) if override else Path.home() / ".claude"


def catalog_dir() -> Path:
    return claude_config_dir() / "cache" / "model-catalog"


def _catalog_files() -> List[Path]:
    try:
        return sorted(catalog_dir().glob("*-cc.json"))
    except OSError:
        return []


def _model_entry(model_id: str, name: Optional[str] = None, description: Optional[str] = None,
                 alias_for: Optional[str] = None) -> Dict[str, Optional[str]]:
    return {"id": model_id, "name": name or model_id, "description": description, "alias_for": alias_for}


def _parse_catalog(data: dict) -> List[Dict[str, Optional[str]]]:
    config = ((data.get("catalog") or {}).get("config")) or {}
    models = [m for m in config.get("models") or [] if isinstance(m, dict) and m.get("id")]
    if not models:
        return []
    # "main" models first (the picker's top section), then "overflow", keeping catalog order.
    models.sort(key=lambda m: 0 if m.get("section") == "main" else 1)
    by_id = {m["id"]: m for m in models}

    aliases = config.get("provider_alias_targets") or {}
    alias_names = sorted(aliases, key=lambda a: (_ALIAS_ORDER.index(a) if a in _ALIAS_ORDER else len(_ALIAS_ORDER), a))
    out: List[Dict[str, Optional[str]]] = []
    for alias in alias_names:
        target = (aliases.get(alias) or {}).get("default")
        target_name = (by_id.get(target) or {}).get("name") if target else None
        label = "%s (latest: %s)" % (alias.capitalize(), target_name or target) if target else alias.capitalize()
        out.append(_model_entry(alias, label, "Alias for the latest %s model" % alias, target))
    for m in models:
        out.append(_model_entry(m["id"], m.get("name"), m.get("description")))
    return out


def _load_from_catalog() -> List[Dict[str, Optional[str]]]:
    best: Tuple[float, List[Dict[str, Optional[str]]]] = (-1, [])
    for path in _catalog_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fetched = data.get("fetchedAt") or 0
        parsed = _parse_catalog(data)
        if parsed and fetched > best[0]:
            best = (fetched, parsed)
    return best[1]


def _cache_key() -> Tuple:
    env = os.environ.get("CLAUDE_SERVICE_MODELS", "")
    stats = []
    for path in _catalog_files():
        try:
            st = path.stat()
            stats.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return (env, tuple(stats))


def available_models() -> List[Dict[str, Optional[str]]]:
    """Models to advertise, as dicts with id, name, description, alias_for."""
    key = _cache_key()
    with _lock:
        if _cache["key"] == key and _cache["models"] is not None:
            return list(_cache["models"])  # type: ignore[arg-type]

    override = [m.strip() for m in key[0].split(",") if m.strip()]
    if override:
        models = [_model_entry(m) for m in override]
    else:
        models = _load_from_catalog() or [_model_entry(m) for m in FALLBACK_MODELS]

    with _lock:
        _cache["key"] = key
        _cache["models"] = models
    return list(models)


def model_ids() -> List[str]:
    return [m["id"] for m in available_models()]  # type: ignore[misc]
