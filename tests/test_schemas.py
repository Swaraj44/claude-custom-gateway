import pytest
from pydantic import ValidationError

from app.schemas import ChatCompletionRequest, ChatRequest, OpenAIMessage


def test_blank_prompt_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(prompt="   ")


def test_blank_optional_fields_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(prompt="hi", model="   ")
    with pytest.raises(ValidationError):
        ChatRequest(prompt="hi", session_id="   ")


def test_valid_request():
    req = ChatRequest(prompt="hi", model="sonnet", session_id="abc")
    assert req.model == "sonnet"


def test_empty_messages_rejected():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(messages=[])


def test_openai_message_text_extraction():
    assert OpenAIMessage(role="user", content="hello").text() == "hello"
    assert OpenAIMessage(role="user", content=None).text() == ""
    parts = [{"type": "text", "text": "a"}, "b", {"type": "image_url", "url": "x"}]
    assert OpenAIMessage(role="user", content=parts).text() == "ab"
