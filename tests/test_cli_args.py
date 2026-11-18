import errno
import json
import os
import subprocess

from app import claude_cli

BIG = "x" * (claude_cli.SYSTEM_PROMPT_INLINE_MAX + 1)


def test_small_system_prompt_stays_inline():
    with claude_cli.spilled_system_prompt("Be brief.") as (inline, path):
        assert inline == "Be brief." and path is None


def test_large_system_prompt_goes_to_temp_file_and_is_removed():
    with claude_cli.spilled_system_prompt(BIG) as (inline, path):
        assert inline is None
        with open(path, encoding="utf-8") as f:
            assert f.read() == BIG
    assert not os.path.exists(path)


def test_build_cmd_uses_file_flag_instead_of_inline_or_default():
    cmd = claude_cli.build_cmd("haiku", raw_model=True, system_prompt_file="/tmp/p.txt")
    assert cmd[cmd.index("--system-prompt-file") + 1] == "/tmp/p.txt"
    assert "--system-prompt" not in cmd


def test_run_once_passes_large_prompt_via_file(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        path = cmd[cmd.index("--system-prompt-file") + 1]
        with open(path, encoding="utf-8") as f:
            seen["content"] = f.read()
        seen["path"] = path
        seen["argv_bytes"] = max(len(a.encode()) for a in cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "ok"}), "")

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    data, err = claude_cli.run_claude_once("hi", system_prompt=BIG, raw_model=True)
    assert err is None and data["result"] == "ok"
    assert seen["content"] == BIG
    assert seen["argv_bytes"] < claude_cli.SYSTEM_PROMPT_INLINE_MAX
    assert not os.path.exists(seen["path"])


def test_run_once_returns_error_instead_of_raising_on_e2big(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise OSError(errno.E2BIG, "Argument list too long")

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    data, err = claude_cli.run_claude_once("hi", raw_model=True)
    assert data is None and err.status_code == 500
    assert "Argument list too long" in json.loads(err.body)["error"]


def test_stream_yields_error_event_on_spawn_oserror(monkeypatch):
    def fake_popen(cmd, **kwargs):
        raise OSError(errno.E2BIG, "Argument list too long")

    monkeypatch.setattr(claude_cli.subprocess, "Popen", fake_popen)
    events = list(claude_cli.claude_events("hi", system_prompt=BIG, raw_model=True))
    assert events == [{"kind": "error", "message": "could not start claude CLI: [Errno 7] Argument list too long"}]


def test_raw_model_calls_do_not_persist_sessions():
    assert "--no-session-persistence" in claude_cli.build_cmd("haiku", raw_model=True)
    # Native calls can be resumed, so their sessions must still be saved.
    assert "--no-session-persistence" not in claude_cli.build_cmd("haiku")
    assert "--no-session-persistence" not in claude_cli.build_cmd("haiku", session_id="abc")
