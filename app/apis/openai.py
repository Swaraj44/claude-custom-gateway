"""OpenAI-compatible endpoints: GET /v1/models and POST /v1/chat/completions."""

import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.claude_cli import run_claude_once
from app.config import settings
from app.openai_compat import (
    build_tools_section,
    messages_to_prompt_and_blocks,
    openai_stream,
    parse_function_calls,
    usage_dict,
)
from app.schemas import ChatCompletionRequest
from app.security import check_api_key
from app.utils import error

router = APIRouter()


@router.get("/v1/models", dependencies=[Depends(check_api_key)])
def list_models():
    now = int(time.time())
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "created": now, "owned_by": "claude-cli"} for m in settings.models],
    }


@router.post("/v1/chat/completions", dependencies=[Depends(check_api_key)])
def openai_chat_completions(req: ChatCompletionRequest):
    prompt, content_blocks, system_prompt = messages_to_prompt_and_blocks(req.messages)
    has_tools = bool(req.tools)
    tool_names = set()
    for t in req.tools or []:
        fn = t.get("function") or {}
        if fn.get("name"):
            tool_names.add(fn["name"])
    if has_tools:
        tools_section = build_tools_section(req.tools, req.tool_choice)
        system_prompt = (system_prompt + "\n\n" + tools_section) if system_prompt else tools_section
    if not prompt.strip() and content_blocks is None:
        return error(400, "messages must contain at least one message with text content")
    # Image content blocks require a vision-capable model; the CLI default may
    # not support images, so fall back to the configured vision model.
    model = req.model or (settings.vision_model if content_blocks is not None else None)
    include_usage = bool((req.stream_options or {}).get("include_usage"))
    if req.stream:
        return StreamingResponse(
            openai_stream(model, prompt, system_prompt, has_tools, tool_names or None,
                          content_blocks=content_blocks, include_usage=include_usage),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    data, err = run_claude_once(prompt, model, None, system_prompt, raw_model=True,
                                content_blocks=content_blocks)
    if err is not None:
        return err
    tool_calls, content = parse_function_calls(data.get("result", ""), tool_names or None)
    message = {"role": "assistant", "content": content if content else None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "claude-cli",
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": usage_dict(data.get("usage") or {}, data.get("total_cost_usd"),
                            data.get("session_id")),
    }
