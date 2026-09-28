from typing import Any, List, Optional

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    session_id: Optional[str] = None

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt must not be blank")
        return v

    @field_validator("model", "session_id")
    @classmethod
    def optional_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("must be a non-empty string when provided")
        return v


class ChatResponse(BaseModel):
    response: str
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[float] = None
    is_error: bool = False


class OpenAIMessage(BaseModel):
    role: str = "user"
    content: Any = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def text(self) -> str:
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            parts = []
            for p in self.content:
                if isinstance(p, str):
                    parts.append(p)
                elif isinstance(p, dict) and p.get("type") == "text":
                    parts.append(p.get("text", ""))
            return "".join(parts)
        return str(self.content)


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[OpenAIMessage]
    stream: bool = False
    tools: Optional[List[dict]] = None
    tool_choice: Optional[Any] = None

    @field_validator("messages")
    @classmethod
    def messages_not_empty(cls, v: List[OpenAIMessage]) -> List[OpenAIMessage]:
        if not v:
            raise ValueError("messages must not be empty")
        return v
