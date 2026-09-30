"""Convert CLI results into OpenAI chat-completion responses and SSE chunks."""

import json
import time
import uuid
from typing import Optional

from app.claude_cli import claude_events, run_claude_once
from app.openai_compat.tools import parse_function_calls
from app.utils import sse


def usage_dict(usage: dict, cost_usd: Optional[float] = None,
               session_id: Optional[str] = None) -> dict:
    pt = usage.get("input_tokens") or 0
    ct = usage.get("output_tokens") or 0
    out = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}
    details = {}
    cached = usage.get("cache_read_input_tokens") or 0
    cache_creation = usage.get("cache_creation_input_tokens") or 0
    if cached:
        details["cached_tokens"] = cached
    if cache_creation:
        details["cache_creation_tokens"] = cache_creation
    if details:
        out["prompt_tokens_details"] = details
    for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        if usage.get(key):
            out[key] = usage[key]
    if cost_usd is None:
        cost_usd = usage.get("cost_usd")
    if cost_usd is not None:
        out["cost_usd"] = cost_usd
    if session_id:
        out["session_id"] = session_id
    return out


def openai_stream(model: Optional[str], prompt: str, system_prompt: Optional[str],
                  has_tools: bool = False, tool_names: Optional[set] = None,
                  content_blocks: Optional[list] = None,
                  include_usage: bool = False):
    chat_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())
    model_name = model or "claude-cli"

    def chunk(delta=None, finish_reason=None, usage=None, choices=None):
        obj = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": choices if choices is not None else [{
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
        data, err = run_claude_once(prompt, model, None, system_prompt, raw_model=True,
                                    content_blocks=content_blocks)
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
            usage = usage_dict(data.get("usage") or {}, data.get("total_cost_usd"),
                               data.get("session_id"))
            if tool_calls:
                for i, tc in enumerate(tool_calls):
                    yield chunk(delta={"tool_calls": [{
                        "index": i,
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }]})
                yield chunk(finish_reason="tool_calls", usage=None if include_usage else usage)
                if include_usage:
                    yield chunk(choices=[], usage=usage)
            else:
                yield chunk(finish_reason="stop", usage=None if include_usage else usage)
                if include_usage:
                    yield chunk(choices=[], usage=usage)
        yield b"data: [DONE]\n\n"
        return

    for ev in claude_events(prompt, model, None, system_prompt, raw_model=True,
                            content_blocks=content_blocks):
        kind = ev["kind"]
        if kind == "text":
            yield chunk(delta={"content": ev["text"]})
        elif kind == "result":
            usage = usage_dict(ev.get("usage") or {}, ev.get("cost_usd"),
                               ev.get("session_id"))
            yield chunk(finish_reason="stop", usage=None if include_usage else usage)
            if include_usage:
                yield chunk(choices=[], usage=usage)
        elif kind == "error":
            yield chunk(delta={"content": "\n[service error] " + ev["message"]})
            yield chunk(finish_reason="stop")
    yield b"data: [DONE]\n\n"
