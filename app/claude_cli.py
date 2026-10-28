import json
import os
import signal
import subprocess
import tempfile
import threading
from typing import Dict, List, Optional

from app.config import reset_claude_bin, claude_bin, settings
from app.utils import error


def build_cmd(model: Optional[str] = None, session_id: Optional[str] = None,
              stream: bool = False, system_prompt: Optional[str] = None,
              raw_model: bool = False, stream_input: bool = False) -> List[str]:
    output_format = "stream-json" if (stream or stream_input) else "json"
    cmd = [claude_bin(), "-p", "--output-format", output_format]
    if stream or stream_input:
        cmd.append("--verbose")
    if stream_input:
        # Required for passing image content blocks via stdin. The CLI mandates
        # stream-json output whenever input-format is stream-json.
        cmd += ["--input-format", "stream-json"]
    if raw_model:
        cmd += ["--tools", "", "--strict-mcp-config"]
        if settings.effort:
            cmd += ["--effort", settings.effort]
        # Without --system-prompt the CLI sends its full coding-agent prompt
        # (~3k tokens), which a plain chat request neither wants nor pays for.
        system_prompt = system_prompt or settings.default_system_prompt
    if system_prompt:
        # Passed as a file, not an argument: agent system prompts (Kilo Code etc.)
        # run to tens of thousands of characters, past Windows' 32,767-char
        # command-line limit, where spawning fails with WinError 206 — raised
        # as FileNotFoundError and previously reported as "claude CLI not found".
        cmd += ["--system-prompt-file", write_system_prompt_file(system_prompt)]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def write_system_prompt_file(system_prompt: str) -> str:
    fd, path = tempfile.mkstemp(prefix="claude-gw-system-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(system_prompt)
    return path


def remove_cmd_files(cmd: List[str]) -> None:
    if "--system-prompt-file" in cmd:
        try:
            os.remove(cmd[cmd.index("--system-prompt-file") + 1])
        except OSError:
            pass


def spawn_error(exc: OSError) -> str:
    if getattr(exc, "winerror", None) == 206:
        return "claude CLI command line too long (WinError 206)"
    return "claude CLI not found at '%s'" % claude_bin()


# Set when the gateway is started from inside a Claude Code session. Inherited,
# they make the child CLI inject a per-call scratchpad path (a new UUID in every
# prompt) and can force settings such as the effort level.
PARENT_SESSION_ENV = (
    "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_EMIT_STARTUP_TIMING",
    "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING", "CLAUDE_CODE_ENABLE_TASKS", "CLAUDE_PID",
    "CLAUDE_EFFORT", "CLAUDE_AGENT_SDK_VERSION", "AI_AGENT",
)


def cli_env(raw_model: bool = False) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in PARENT_SESSION_ENV}
    if raw_model:
        # OpenAI-compatible calls bring their own system prompt; keep CLAUDE.md
        # files and auto-memory from being added to every request.
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return env


def kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def stdin_payload(prompt: str, content_blocks: Optional[List[dict]]) -> str:
    """Wrap the prompt for CLI stdin: stream-json user message when images are present."""
    if content_blocks is None:
        return prompt
    blocks = content_blocks
    if blocks and settings.prompt_cache_ttl in ("1h", "5m"):
        # The CLI does not cache the user message itself; marking its last block
        # lets the next turn (same blocks + new ones) read this history from cache.
        # The CLI's own breakpoints use 1h on subscription logins, and a 1h
        # breakpoint may not follow a 5m one, so the TTL must match the CLI's.
        blocks = list(blocks)
        blocks[-1] = dict(blocks[-1], cache_control={"type": "ephemeral", "ttl": settings.prompt_cache_ttl})
    return json.dumps({"type": "user", "message": {"role": "user", "content": blocks}})


# Returned by the CLI as the whole reply when the API flagged a native tool call
# it could not use (the CLI runs with no tools here) and its own retry failed.
MALFORMED_TOOL_USE_RESULT = "The model's tool call could not be parsed (retry also failed)."


def run_claude_once(prompt: str, model: Optional[str] = None, session_id: Optional[str] = None,
                    system_prompt: Optional[str] = None, raw_model: bool = False,
                    content_blocks: Optional[List[dict]] = None):
    data, err = _run_claude_once(prompt, model, session_id, system_prompt, raw_model, content_blocks)
    if raw_model and err is None and (data.get("result") or "").strip() == MALFORMED_TOOL_USE_RESULT:
        # Sampling usually differs on a fresh run; one retry beats failing the agent's turn.
        data, err = _run_claude_once(prompt, model, session_id, system_prompt, raw_model, content_blocks)
    return data, err


def _run_claude_once(prompt: str, model: Optional[str], session_id: Optional[str],
                     system_prompt: Optional[str], raw_model: bool,
                     content_blocks: Optional[List[dict]]):
    stream_input = content_blocks is not None
    cmd = build_cmd(model, session_id, stream=stream_input, system_prompt=system_prompt,
                    raw_model=raw_model, stream_input=stream_input)
    def run(c):
        return subprocess.run(
            c,
            input=stdin_payload(prompt, content_blocks),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.timeout,
            env=cli_env(raw_model),
        )

    try:
        try:
            proc = run(cmd)
        except FileNotFoundError as e:
            if getattr(e, "winerror", None) == 206:
                raise
            # The cached CLI path can vanish mid-run (auto-updater replaces the exe);
            # re-discover and retry once before giving up.
            reset_claude_bin()
            proc = run([claude_bin()] + cmd[1:])
    except FileNotFoundError as e:
        return None, error(500, spawn_error(e))
    except subprocess.TimeoutExpired:
        return None, error(504, "claude CLI timed out after %ds" % settings.timeout)
    finally:
        remove_cmd_files(cmd)
    if not stream_input:
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            if not err:
                err = (proc.stdout or "").strip()[:500]
            return None, error(502, err or "claude CLI exited with code %d" % proc.returncode)
        try:
            return json.loads(proc.stdout), None
        except json.JSONDecodeError:
            return None, error(502, "claude CLI returned invalid JSON")
    result_event = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result_event = event
    if result_event is not None:
        return result_event, None
    err = (proc.stderr or "").strip()
    if not err:
        err = (proc.stdout or "").strip()[:500]
    return None, error(502, err or "claude CLI exited with code %d" % proc.returncode)


def claude_events(prompt: str, model: Optional[str] = None, session_id: Optional[str] = None,
                  system_prompt: Optional[str] = None, raw_model: bool = False,
                  content_blocks: Optional[List[dict]] = None):
    stream_input = content_blocks is not None
    cmd = build_cmd(model, session_id, stream=True, system_prompt=system_prompt,
                    raw_model=raw_model, stream_input=stream_input)
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")

    def spawn(c):
        return subprocess.Popen(
            c,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            start_new_session=(os.name == "posix"),
            env=cli_env(raw_model),
        )

    try:
        try:
            proc = spawn(cmd)
        except FileNotFoundError as e:
            if getattr(e, "winerror", None) == 206:
                raise
            reset_claude_bin()
            proc = spawn([claude_bin()] + cmd[1:])
    except FileNotFoundError as e:
        stderr_file.close()
        remove_cmd_files(cmd)
        yield {"kind": "error", "message": spawn_error(e)}
        return

    def feed_stdin():
        try:
            proc.stdin.write(stdin_payload(prompt, content_blocks))
            proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    threading.Thread(target=feed_stdin, daemon=True).start()
    timer = threading.Timer(settings.timeout, kill_process, args=(proc,))
    timer.start()
    got_result = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        yield {"kind": "text", "text": block["text"]}
            elif etype == "result":
                got_result = True
                yield {
                    "kind": "result",
                    "session_id": event.get("session_id"),
                    "cost_usd": event.get("total_cost_usd"),
                    "duration_ms": event.get("duration_ms"),
                    "is_error": event.get("is_error", False),
                    "result": event.get("result", ""),
                    "usage": event.get("usage") or {},
                }
        proc.wait()
        if not got_result:
            stderr_file.seek(0)
            stderr = (stderr_file.read() or "").strip()
            if proc.returncode != 0:
                yield {"kind": "error", "message": stderr or "claude CLI exited with code %d" % proc.returncode}
            else:
                yield {"kind": "error", "message": "claude CLI closed the stream without a result"}
    finally:
        timer.cancel()
        kill_process(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        stderr_file.close()
        remove_cmd_files(cmd)
