import json
import os
import signal
import subprocess
import tempfile
import threading
from typing import List, Optional

from app.config import settings
from app.utils import error


def build_cmd(model: Optional[str] = None, session_id: Optional[str] = None,
              stream: bool = False, system_prompt: Optional[str] = None,
              raw_model: bool = False) -> List[str]:
    cmd = [settings.claude_bin, "-p", "--output-format", "stream-json" if stream else "json"]
    if stream:
        cmd.append("--verbose")
    if raw_model:
        cmd += ["--tools", "", "--strict-mcp-config"]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def run_claude_once(prompt: str, model: Optional[str] = None, session_id: Optional[str] = None,
                    system_prompt: Optional[str] = None, raw_model: bool = False):
    cmd = build_cmd(model, session_id, stream=False, system_prompt=system_prompt, raw_model=raw_model)
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.timeout,
        )
    except FileNotFoundError:
        return None, error(500, "claude CLI not found at '%s'" % settings.claude_bin)
    except subprocess.TimeoutExpired:
        return None, error(504, "claude CLI timed out after %ds" % settings.timeout)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if not err:
            err = (proc.stdout or "").strip()[:500]
        return None, error(502, err or "claude CLI exited with code %d" % proc.returncode)
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError:
        return None, error(502, "claude CLI returned invalid JSON")


def claude_events(prompt: str, model: Optional[str] = None, session_id: Optional[str] = None,
                  system_prompt: Optional[str] = None, raw_model: bool = False):
    cmd = build_cmd(model, session_id, stream=True, system_prompt=system_prompt, raw_model=raw_model)
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
        )
    except FileNotFoundError:
        stderr_file.close()
        yield {"kind": "error", "message": "claude CLI not found at '%s'" % settings.claude_bin}
        return

    def feed_stdin():
        try:
            proc.stdin.write(prompt)
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
