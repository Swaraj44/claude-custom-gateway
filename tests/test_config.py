"""Regression tests for claude CLI discovery (mangled override / vanishing binary)."""

from pathlib import Path

from app import config

MANGLED = r"C:\Users\DELL.local\bin\claude.EXE"


def test_mangled_override_is_ignored(monkeypatch):
    monkeypatch.setenv("CLAUDE_SERVICE_CLAUDE_BIN", MANGLED)
    resolved = config._find_claude_bin()
    assert resolved != MANGLED
    assert Path(resolved).is_file() or resolved == "claude"


def test_valid_override_is_used(monkeypatch, tmp_path):
    fake = tmp_path / "claude.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("CLAUDE_SERVICE_CLAUDE_BIN", str(fake))
    assert config._find_claude_bin() == str(fake)


def test_claude_bin_rediscovered_when_binary_disappears(monkeypatch, tmp_path):
    old = tmp_path / "claude.exe"
    new = tmp_path / "claude.new.exe"
    old.write_bytes(b"")
    new.write_bytes(b"")
    monkeypatch.setattr(config, "_find_claude_bin", lambda: str(old))
    config.reset_claude_bin()
    assert config.claude_bin() == str(old)
    old.unlink()  # auto-updater replaced the exe in place
    monkeypatch.setattr(config, "_find_claude_bin", lambda: str(new))
    assert config.claude_bin() == str(new)
    config.reset_claude_bin()


def test_claude_bin_cached_until_reset(monkeypatch, tmp_path):
    fake = tmp_path / "claude.exe"
    fake.write_bytes(b"")
    calls = []

    def fake_find():
        calls.append(1)
        return str(fake)

    monkeypatch.setattr(config, "_find_claude_bin", fake_find)
    config.reset_claude_bin()
    assert config.claude_bin() == str(fake)
    assert config.claude_bin() == str(fake)
    assert len(calls) == 1
    config.reset_claude_bin()
    assert config.claude_bin() == str(fake)
    assert len(calls) == 2


def test_bare_name_keeps_rediscovering(monkeypatch):
    calls = []

    def fake_find():
        calls.append(1)
        return "claude"

    monkeypatch.setattr(config, "_find_claude_bin", fake_find)
    config.reset_claude_bin()
    assert config.claude_bin() == "claude"
    assert config.claude_bin() == "claude"
    assert len(calls) == 2  # not cached: the CLI may be installed later
    config.reset_claude_bin()


ALL_VARS = [
    "CLAUDE_SERVICE_HOST", "CLAUDE_SERVICE_PORT", "CLAUDE_SERVICE_TIMEOUT", "CLAUDE_SERVICE_API_KEY",
    "CLAUDE_SERVICE_MODELS", "CLAUDE_SERVICE_VISION_MODEL", "CLAUDE_SERVICE_SYSTEM_PROMPT_MAX",
    "CLAUDE_SERVICE_DEFAULT_SYSTEM_PROMPT", "CLAUDE_SERVICE_PROMPT_CACHE_TTL", "CLAUDE_SERVICE_EFFORT",
    "CLAUDE_SERVICE_CORS_ORIGINS", "CLAUDE_SERVICE_LOG_LEVEL", "CLAUDE_SERVICE_LOG_PAYLOADS",
    "CLAUDE_SERVICE_LOG_PAYLOAD_MAX",
]


def _clear(monkeypatch):
    for name in ALL_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_have_no_builtin_api_key(monkeypatch):
    _clear(monkeypatch)
    s = config.load_settings()
    assert s.api_key == ""
    assert s.port == 6069 and s.models == ("sonnet", "opus", "haiku")


def test_every_setting_comes_from_env(monkeypatch):
    _clear(monkeypatch)
    values = {
        "CLAUDE_SERVICE_HOST": "127.0.0.1",
        "CLAUDE_SERVICE_PORT": "7000",
        "CLAUDE_SERVICE_TIMEOUT": "30",
        "CLAUDE_SERVICE_API_KEY": "secret",
        "CLAUDE_SERVICE_MODELS": "sonnet, claude-opus-5 ,",
        "CLAUDE_SERVICE_VISION_MODEL": "opus",
        "CLAUDE_SERVICE_SYSTEM_PROMPT_MAX": "5000",
        "CLAUDE_SERVICE_DEFAULT_SYSTEM_PROMPT": "Be brief.",
        "CLAUDE_SERVICE_PROMPT_CACHE_TTL": "5M",
        "CLAUDE_SERVICE_EFFORT": "Low",
        "CLAUDE_SERVICE_CORS_ORIGINS": "http://localhost:3000,https://example.com",
        "CLAUDE_SERVICE_LOG_LEVEL": "WARNING",
        "CLAUDE_SERVICE_LOG_PAYLOADS": "1",
        "CLAUDE_SERVICE_LOG_PAYLOAD_MAX": "200",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    s = config.load_settings()
    assert (s.host, s.port, s.timeout, s.api_key) == ("127.0.0.1", 7000, 30, "secret")
    assert s.models == ("sonnet", "claude-opus-5")
    assert (s.vision_model, s.system_prompt_max, s.default_system_prompt) == ("opus", 5000, "Be brief.")
    assert (s.prompt_cache_ttl, s.effort) == ("5m", "low")
    assert s.cors_origins == ("http://localhost:3000", "https://example.com")
    assert (s.log_level, s.log_payloads, s.log_payload_max) == ("warning", True, 200)


def test_empty_values_fall_back_to_defaults(monkeypatch):
    _clear(monkeypatch)
    for name in ALL_VARS:
        if name != "CLAUDE_SERVICE_API_KEY":
            monkeypatch.setenv(name, "")
    s = config.load_settings()
    d = config.Settings()
    assert s == d


def test_bad_number_names_the_variable(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CLAUDE_SERVICE_PORT", "abc")
    try:
        config.load_settings()
    except ValueError as e:
        assert "CLAUDE_SERVICE_PORT" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_env_example_lists_every_setting():
    text = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    for name in ALL_VARS + ["CLAUDE_SERVICE_CLAUDE_BIN"]:
        assert "\n%s=" % name in text, name
