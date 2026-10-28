import json

from app import claude_cli
from app.openai_compat import messages_to_prompt, messages_to_prompt_and_blocks
from app.openai_compat.prompt import TRANSCRIPT_HEADER
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
    assert '<tool_call name="get_weather">' in prompt
    assert '<tool_result name="get_weather">\n18C\n</tool_result>' in prompt
    assert "<function_calls>" not in prompt and "<function_results>" not in prompt
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
    assert types == ["text", "text", "text", "text", "image"]
    assert blocks[0]["text"] == TRANSCRIPT_HEADER
    assert blocks[1]["text"] == "User: Hi"
    assert blocks[2]["text"] == "Assistant: Hello!"
    assert blocks[3]["text"] == "User: And this?"


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


def test_multi_turn_text_uses_one_block_per_turn():
    _, blocks, _ = messages_to_prompt_and_blocks([
        OpenAIMessage(role="user", content="Hi"),
        OpenAIMessage(role="assistant", content="Hello!"),
        OpenAIMessage(role="user", content="Bye"),
    ])
    assert [b["text"] for b in blocks] == [TRANSCRIPT_HEADER, "User: Hi", "Assistant: Hello!", "User: Bye"]


def test_next_turn_extends_previous_blocks():
    history = [
        OpenAIMessage(role="user", content="Weather?"),
        OpenAIMessage(role="assistant", content="", tool_calls=[
            {"id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'}},
        ]),
        OpenAIMessage(role="tool", tool_call_id="call_1", content="18C"),
    ]
    _, first, _ = messages_to_prompt_and_blocks(history)
    _, second, _ = messages_to_prompt_and_blocks(history + [
        OpenAIMessage(role="assistant", content="It is 18C."),
        OpenAIMessage(role="user", content="Thanks"),
    ])
    assert second[:len(first)] == first


def test_stdin_payload_marks_last_block_for_caching(monkeypatch):
    monkeypatch.setattr(claude_cli, "settings", claude_cli.settings.__class__(prompt_cache_ttl="1h"))
    blocks = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    content = json.loads(claude_cli.stdin_payload("", blocks))["message"]["content"]
    assert "cache_control" not in content[0]
    assert content[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in blocks[1]


def test_stdin_payload_cache_off(monkeypatch):
    monkeypatch.setattr(claude_cli, "settings", claude_cli.settings.__class__(prompt_cache_ttl="off"))
    content = json.loads(claude_cli.stdin_payload("", [{"type": "text", "text": "a"}]))["message"]["content"]
    assert "cache_control" not in content[0]


def test_single_turn_transcript_mode_uses_blocks():
    msgs = [OpenAIMessage(role="system", content="Be brief."), OpenAIMessage(role="user", content="Hi")]
    prompt, blocks, system = messages_to_prompt_and_blocks(msgs, transcript=True)
    assert prompt == "Hi"
    assert system == "Be brief."
    assert blocks == [{"type": "text", "text": TRANSCRIPT_HEADER}, {"type": "text", "text": "User: Hi"}]


def test_transcript_first_turn_is_prefix_of_second():
    first_msgs = [OpenAIMessage(role="user", content="Read main.py")]
    _, first, _ = messages_to_prompt_and_blocks(first_msgs, transcript=True)
    _, second, _ = messages_to_prompt_and_blocks(first_msgs + [
        OpenAIMessage(role="assistant", content="Sure."),
        OpenAIMessage(role="user", content="Thanks"),
    ], transcript=True)
    assert second[:len(first)] == first


def test_single_turn_without_transcript_stays_plain():
    _, blocks, _ = messages_to_prompt_and_blocks([OpenAIMessage(role="user", content="Hi")])
    assert blocks is None


def test_cli_env_drops_parent_session_vars(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    monkeypatch.setenv("CLAUDE_EFFORT", "medium")
    monkeypatch.setenv("CLAUDE_SERVICE_PORT", "8000")
    env = claude_cli.cli_env()
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env and "CLAUDE_EFFORT" not in env
    assert env["CLAUDE_SERVICE_PORT"] == "8000"
    assert "CLAUDE_CODE_DISABLE_CLAUDE_MDS" not in env


def test_cli_env_raw_model_skips_claude_md():
    env = claude_cli.cli_env(raw_model=True)
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


def test_raw_model_always_sends_a_system_prompt():
    cmd = claude_cli.build_cmd("haiku", raw_model=True)
    assert cmd[cmd.index("--system-prompt") + 1] == claude_cli.DEFAULT_RAW_SYSTEM_PROMPT
    cmd = claude_cli.build_cmd("haiku", raw_model=True, system_prompt="Be brief.")
    assert cmd[cmd.index("--system-prompt") + 1] == "Be brief."
    assert "--system-prompt" not in claude_cli.build_cmd("haiku")
