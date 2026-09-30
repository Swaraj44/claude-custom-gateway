"""Native chat endpoints: POST /api/chat and POST /api/chat/stream."""

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.claude_cli import claude_events, run_claude_once
from app.schemas import ChatRequest, ChatResponse
from app.security import check_api_key
from app.utils import sse

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(check_api_key)])
def chat(req: ChatRequest):
    data, err = run_claude_once(req.prompt, req.model, req.session_id)
    if err is not None:
        return err
    return ChatResponse(
        response=data.get("result", ""),
        session_id=data.get("session_id"),
        cost_usd=data.get("total_cost_usd"),
        duration_ms=data.get("duration_ms"),
        is_error=data.get("is_error", False),
        usage=data.get("usage") or None,
    )


@router.post("/api/chat/stream", dependencies=[Depends(check_api_key)])
def chat_stream(req: ChatRequest):
    return StreamingResponse(
        event_stream(req.prompt, req.model, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def event_stream(prompt: str, model: Optional[str], session_id: Optional[str]):
    emitted = False
    for ev in claude_events(prompt, model, session_id):
        kind = ev["kind"]
        if kind == "text":
            yield sse({"text": ev["text"]})
            emitted = True
        elif kind == "result":
            payload = {
                "done": True,
                "session_id": ev["session_id"],
                "cost_usd": ev["cost_usd"],
                "duration_ms": ev["duration_ms"],
                "is_error": ev["is_error"],
                "usage": ev.get("usage") or {},
            }
            if not emitted and ev["result"]:
                payload["text"] = ev["result"]
            if ev["is_error"]:
                payload["error"] = ev["result"] or "claude CLI reported an error"
            yield sse(payload)
            emitted = True
        elif kind == "error":
            yield sse({"error": ev["message"], "done": True})
