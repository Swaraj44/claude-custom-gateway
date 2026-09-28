"""OpenAI-compatible endpoints: GET /v1/models and POST /v1/chat/completions."""

import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.claude_cli import run_claude_once
from app.config import settings
from app.openai_compat import (
    build_tools_section,
    messages_to_prompt,
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
    prompt, system_prompt = messages_to_prompt(req.messages)
    has_tools = bool(req.tools)
    tool_names = set()
    for t in req.tools or []:
        fn = t.get("function") or {}
        if fn.get("name"):
            tool_names.add(fn["name"])
    if has_tools:
        tools_section = build_tools_section(req.tools, req.tool_choice)
        system_prompt = (system_prompt + "\n\n" + tools_section) if system_prompt else tools_section
    if not prompt.strip():
        return error(400, "messages must contain at least one message with text content")
    if req.stream:
        return StreamingResponse(
            openai_stream(req.model, prompt, system_prompt, has_tools, tool_names or None),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    data, err = run_claude_once(prompt, req.model, None, system_prompt, raw_model=True)
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
        "model": req.model or "claude-cli",
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": usage_dict(data.get("usage") or {}),
    }
