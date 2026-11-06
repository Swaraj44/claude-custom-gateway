import json
import os
import signal
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Tuple

from app.config import settings
from app.utils import error


DEFAULT_RAW_SYSTEM_PROMPT = "You are a helpful assistant."

# Linux caps a single argv string at 128 KiB (MAX_ARG_STRLEN), and agent
# clients send system prompts plus tool schemas well past that. Anything over
# this size goes to the CLI through --system-prompt-file instead of argv.
SYSTEM_PROMPT_INLINE_MAX = 32 * 1024


@contextmanager
def spilled_system_prompt(system_prompt: Optional[str]) -> Iterator[Tuple[Optional[str], Optional[str]]]:
    """Yield (inline_prompt, file_path): small prompts stay inline, large ones go to a temp file."""
    if not system_prompt or len(system_prompt.encode("utf-8")) <= SYSTEM_PROMPT_INLINE_MAX:
        yield system_prompt, None
        return
    fd, path = tempfile.mkstemp(prefix="claude-gateway-system-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(system_prompt)
        yield None, path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def build_cmd(model: Optional[str] = None, session_id: Optional[str] = None,
              stream: bool = False, system_prompt: Optional[str] = None,
              raw_model: bool = False, stream_input: bool = False,
              system_prompt_file: Optional[str] = None) -> List[str]:
    output_format = "stream-json" if (stream or stream_input) else "json"
    cmd = [settings.claude_bin, "-p", "--output-format", output_format]
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
        if not system_prompt_file:
            system_prompt = system_prompt or DEFAULT_RAW_SYSTEM_PROMPT
    if system_prompt_file:
        cmd += ["--system-prompt-file", system_prompt_file]
    elif system_prompt:
        cmd += ["--system-prompt", system_prompt]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


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
            os.killpg(proc.pid, signal.SIGKILL)
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
    with spilled_system_prompt(system_prompt) as (inline_prompt, prompt_file):
        return _spawn_once(prompt, model, session_id, inline_prompt, prompt_file,
                           raw_model, content_blocks)


def _start_error(exc: OSError) -> str:
    if isinstance(exc, FileNotFoundError):
        return "claude CLI not found at '%s'" % settings.claude_bin
    return "could not start claude CLI: %s" % exc


def _spawn_once(prompt: str, model: Optional[str], session_id: Optional[str],
                system_prompt: Optional[str], system_prompt_file: Optional[str],
                raw_model: bool, content_blocks: Optional[List[dict]]):
    stream_input = content_blocks is not None
    cmd = build_cmd(model, session_id, stream=stream_input, system_prompt=system_prompt,
                    raw_model=raw_model, stream_input=stream_input,
                    system_prompt_file=system_prompt_file)
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_payload(prompt, content_blocks),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.timeout,
            env=cli_env(raw_model),
        )
    except OSError as exc:
        return None, error(500, _start_error(exc))
    except subprocess.TimeoutExpired:
        return None, error(504, "claude CLI timed out after %ds" % settings.timeout)
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
    # The temp file (if any) must outlive the CLI process, so it is removed
    # only when this generator finishes or is closed.
    with spilled_system_prompt(system_prompt) as (inline_prompt, prompt_file):
        yield from _stream_events(prompt, model, session_id, inline_prompt, prompt_file,
                                  raw_model, content_blocks)


def _stream_events(prompt: str, model: Optional[str], session_id: Optional[str],
                   system_prompt: Optional[str], system_prompt_file: Optional[str],
                   raw_model: bool, content_blocks: Optional[List[dict]]):
    stream_input = content_blocks is not None
    cmd = build_cmd(model, session_id, stream=True, system_prompt=system_prompt,
                    raw_model=raw_model, stream_input=stream_input,
                    system_prompt_file=system_prompt_file)
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            start_new_session=True,
            env=cli_env(raw_model),
        )
    except OSError as exc:
        stderr_file.close()
        yield {"kind": "error", "message": _start_error(exc)}
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
