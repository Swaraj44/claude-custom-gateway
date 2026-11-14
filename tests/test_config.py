import os
import stat

from app import config

EXE = "claude.exe" if os.name == "nt" else "claude"


def _make_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    monkeypatch.delenv("CLAUDE_SERVICE_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)


def test_env_override_wins(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    exe = _make_exe(tmp_path / "custom" / "claude")
    monkeypatch.setenv("CLAUDE_SERVICE_CLAUDE_BIN", str(exe))
    assert config._find_claude_bin() == str(exe)


def test_falls_back_to_newest_vscode_bundled_binary(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ext = tmp_path / ".vscode" / "extensions"
    _make_exe(ext / "anthropic.claude-code-2.1.9-linux-x64/resources/native-binary" / EXE)
    newest = _make_exe(ext / "anthropic.claude-code-2.1.318-linux-x64/resources/native-binary" / EXE)
    assert config._find_claude_bin() == str(newest)


def test_local_install_preferred_over_bundled(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    local = _make_exe(tmp_path / ".local" / "bin" / EXE)
    _make_exe(tmp_path / ".vscode/extensions/anthropic.claude-code-2.1.318-linux-x64/resources/native-binary" / EXE)
    assert config._find_claude_bin() == str(local)


def test_non_executable_skipped_and_default_returned(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    p = tmp_path / ".local" / "bin" / "claude"
    p.parent.mkdir(parents=True)
    p.write_text("")
    assert config._find_claude_bin() == "claude"


def test_prompt_cache_ttl_only_1h_enables_the_marker(monkeypatch):
    for value, expected in (("1h", "1h"), (" 1H ", "1h"), ("off", "off"), ("5m", "off"), ("", "off")):
        monkeypatch.setenv("CLAUDE_SERVICE_PROMPT_CACHE_TTL", value)
        assert config.load_settings().prompt_cache_ttl == expected
    monkeypatch.delenv("CLAUDE_SERVICE_PROMPT_CACHE_TTL")
    assert config.load_settings().prompt_cache_ttl == "1h"
