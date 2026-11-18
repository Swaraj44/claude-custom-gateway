import json

from app import models


def _write_catalog(dir_path, fetched_at=1):
    cat = dir_path / "cache" / "model-catalog"
    cat.mkdir(parents=True)
    data = {
        "version": 2,
        "fetchedAt": fetched_at,
        "catalog": {"config": {
            "models": [
                {"id": "claude-opus-4-6", "name": "Opus 4.6", "section": "overflow"},
                {"id": "claude-opus-5-5", "name": "Opus 5.5", "section": "main", "description": "Big"},
                {"id": "claude-sonnet-5-5", "name": "Sonnet 5.5", "section": "main"},
            ],
            "provider_alias_targets": {
                "opus": {"default": "claude-opus-5-5"},
                "sonnet": {"default": "claude-sonnet-5-5"},
            },
        }},
    }
    (cat / "abc-cc.json").write_text(json.dumps(data))


def test_models_from_cli_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_SERVICE_MODELS", raising=False)
    _write_catalog(tmp_path)
    ids = models.model_ids()
    assert ids == ["sonnet", "opus", "claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-4-6"]
    entry = next(m for m in models.available_models() if m["id"] == "opus")
    assert entry["alias_for"] == "claude-opus-5-5"


def test_models_fallback_without_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_SERVICE_MODELS", raising=False)
    assert models.model_ids() == list(models.FALLBACK_MODELS)


def test_models_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    _write_catalog(tmp_path)
    monkeypatch.setenv("CLAUDE_SERVICE_MODELS", "opus, claude-opus-4-6")
    assert models.model_ids() == ["opus", "claude-opus-4-6"]
