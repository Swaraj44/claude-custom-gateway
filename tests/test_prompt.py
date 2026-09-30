from app.openai_compat import messages_to_prompt, messages_to_prompt_and_blocks
from app.schemas import OpenAIMessage


def test_single_user_message():
    prompt, system = messages_to_prompt([OpenAIMessage(role="user", content="Hello")])
    assert prompt == "Hello"
    assert system is None


def test_system_message_extracted():
    prompt, system = messages_to_prompt([
        OpenAIMessage(role="system", content="Be brief."),
        OpenAIMessage(role="user", content="Hi"),
    ])
    assert system == "Be brief."
    assert prompt == "Hi"


def test_multi_turn_transcript():
    prompt, _ = messages_to_prompt([
        OpenAIMessage(role="user", content="Hi"),
        OpenAIMessage(role="assistant", content="Hello!"),
        OpenAIMessage(role="user", content="Bye"),
    ])
    assert prompt.startswith("Conversation so far:")
    assert "User: Hi" in prompt
    assert "Assistant: Hello!" in prompt
    assert prompt.endswith("Respond as the Assistant to the last message above.")


def test_tool_calls_and_results_continuation():
    prompt, _ = messages_to_prompt([
        OpenAIMessage(role="user", content="Weather?"),
        OpenAIMessage(role="assistant", content="", tool_calls=[
            {"id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'}},
        ]),
        OpenAIMessage(role="tool", tool_call_id="call_1", content="18C"),
    ])
    assert "<function_calls>" in prompt
    assert '<invoke name="get_weather">' in prompt
    assert "<function_results>" in prompt
    assert "<name>get_weather</name>" in prompt
    assert "Continue as the Assistant" in prompt


def _img_msg(text, data="aGVsbG8=", media="image/png"):
    return OpenAIMessage(role="user", content=[
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (media, data)}},
    ])


def test_no_images_gives_no_blocks():
    prompt, blocks, system = messages_to_prompt_and_blocks([
        OpenAIMessage(role="system", content="Be brief."),
        OpenAIMessage(role="user", content="Hi"),
    ])
    assert prompt == "Hi"
    assert blocks is None
    assert system == "Be brief."


def test_single_message_with_image():
    prompt, blocks, _ = messages_to_prompt_and_blocks([_img_msg("What is this?")])
    assert prompt == "What is this?"
    assert blocks == [
        {"type": "text", "text": "What is this?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}},
    ]


def test_multi_turn_with_images_interleaved():
    prompt, blocks, _ = messages_to_prompt_and_blocks([
        OpenAIMessage(role="user", content="Hi"),
        OpenAIMessage(role="assistant", content="Hello!"),
        _img_msg("And this?"),
    ])
    types = [b["type"] for b in blocks]
    assert types == ["text", "text", "text", "image", "text"]
    assert blocks[0]["text"] == "User: Hi"
    assert blocks[1]["text"] == "Assistant: Hello!"
    assert blocks[2]["text"] == "User: And this?"
    assert blocks[4]["text"].startswith("Respond as the Assistant")


def test_image_only_message():
    msg = OpenAIMessage(role="user", content=[
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
    ])
    prompt, blocks, _ = messages_to_prompt_and_blocks([msg])
    assert prompt == ""
    assert blocks == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
    ]


def test_remote_and_invalid_image_urls_skipped():
    msg = OpenAIMessage(role="user", content=[
        {"type": "text", "text": "Look"},
        {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
        {"type": "image_url", "image_url": {"url": "data:image/bmp;base64,QUJD"}},
    ])
    prompt, blocks, _ = messages_to_prompt_and_blocks([msg])
    assert blocks is None
    assert prompt == "Look"
