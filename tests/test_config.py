import os
import stat

from app import config


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
    _make_exe(ext / "anthropic.claude-code-2.1.9-linux-x64/resources/native-binary/claude")
    newest = _make_exe(ext / "anthropic.claude-code-2.1.318-linux-x64/resources/native-binary/claude")
    assert config._find_claude_bin() == str(newest)


def test_local_install_preferred_over_bundled(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    local = _make_exe(tmp_path / ".local" / "bin" / "claude")
    _make_exe(tmp_path / ".vscode/extensions/anthropic.claude-code-2.1.318-linux-x64/resources/native-binary/claude")
    assert config._find_claude_bin() == str(local)


def test_non_executable_skipped_and_default_returned(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    p = tmp_path / ".local" / "bin" / "claude"
    p.parent.mkdir(parents=True)
    p.write_text("")
    assert config._find_claude_bin() == "claude"
