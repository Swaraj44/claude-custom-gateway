"""Convert CLI results into OpenAI chat-completion responses and SSE chunks."""

import json
import time
import uuid
from typing import Optional

from app.claude_cli import claude_events, run_claude_once
from app.openai_compat.tools import parse_function_calls
from app.utils import sse


def usage_dict(usage: dict) -> dict:
    pt = usage.get("input_tokens") or 0
    ct = usage.get("output_tokens") or 0
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}


def openai_stream(model: Optional[str], prompt: str, system_prompt: Optional[str],
                  has_tools: bool = False, tool_names: Optional[set] = None):
    chat_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())
    model_name = model or "claude-cli"

    def chunk(delta=None, finish_reason=None, usage=None):
        obj = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": delta if delta is not None else {},
                "finish_reason": finish_reason,
            }],
        }
        if usage is not None:
            obj["usage"] = usage
        return sse(obj)

    yield chunk(delta={"role": "assistant", "content": ""})

    if has_tools:
        data, err = run_claude_once(prompt, model, None, system_prompt, raw_model=True)
        if err is not None:
            try:
                message = json.loads(err.body).get("error", "claude CLI failed")
            except (AttributeError, json.JSONDecodeError):
                message = "claude CLI failed"
            yield chunk(delta={"content": "\n[service error] %s" % message})
            yield chunk(finish_reason="stop")
        else:
            tool_calls, content = parse_function_calls(data.get("result", ""), tool_names)
            if content:
                yield chunk(delta={"content": content})
            if tool_calls:
                for i, tc in enumerate(tool_calls):
                    yield chunk(delta={"tool_calls": [{
                        "index": i,
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }]})
                yield chunk(finish_reason="tool_calls", usage=usage_dict(data.get("usage") or {}))
            else:
                yield chunk(finish_reason="stop", usage=usage_dict(data.get("usage") or {}))
        yield b"data: [DONE]\n\n"
        return

    for ev in claude_events(prompt, model, None, system_prompt, raw_model=True):
        kind = ev["kind"]
        if kind == "text":
            yield chunk(delta={"content": ev["text"]})
        elif kind == "result":
            yield chunk(finish_reason="stop", usage=usage_dict(ev.get("usage") or {}))
        elif kind == "error":
            yield chunk(delta={"content": "\n[service error] " + ev["message"]})
            yield chunk(finish_reason="stop")
    yield b"data: [DONE]\n\n"
