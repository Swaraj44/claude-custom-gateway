"""Regression tests: long system prompts must not end up on the command line.

Kilo Code-style system prompts run to tens of thousands of characters. Passed as
a --system-prompt argument they exceed Windows' 32,767-char command-line limit,
spawning fails with WinError 206 (a FileNotFoundError), and the gateway used to
report it as "claude CLI not found".
"""

import os
import subprocess

from app import claude_cli

LONG_PROMPT = "You are a coding agent. " * 4000  # ~96k chars


def test_system_prompt_goes_to_a_file():
    cmd = claude_cli.build_cmd(system_prompt=LONG_PROMPT, raw_model=True)
    try:
        assert "--system-prompt" not in cmd
        path = cmd[cmd.index("--system-prompt-file") + 1]
        with open(path, encoding="utf-8") as f:
            assert f.read() == LONG_PROMPT
        assert sum(len(a) for a in cmd) < 8000
    finally:
        claude_cli.remove_cmd_files(cmd)
    assert not os.path.exists(path)


def test_raw_model_default_prompt_uses_file():
    cmd = claude_cli.build_cmd(raw_model=True)
    try:
        path = cmd[cmd.index("--system-prompt-file") + 1]
        with open(path, encoding="utf-8") as f:
            assert f.read() == claude_cli.settings.default_system_prompt
    finally:
        claude_cli.remove_cmd_files(cmd)


def test_no_system_prompt_no_file():
    cmd = claude_cli.build_cmd()
    assert "--system-prompt-file" not in cmd


def test_run_once_cleans_up_prompt_file(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        path = cmd[cmd.index("--system-prompt-file") + 1]
        seen["path"] = path
        seen["existed"] = os.path.exists(path)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"type": "result", "result": "ok"}', stderr="")

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    data, err = claude_cli.run_claude_once("hi", system_prompt=LONG_PROMPT, raw_model=True)
    assert err is None and data["result"] == "ok"
    assert seen["existed"]
    assert not os.path.exists(seen["path"])


def test_command_too_long_is_not_reported_as_not_found(monkeypatch):
    def fake_run(cmd, **kwargs):
        e = FileNotFoundError(2, "The filename or extension is too long")
        e.winerror = 206
        raise e

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    data, err = claude_cli.run_claude_once("hi", raw_model=True)
    assert data is None
    assert "too long" in err.body.decode()
