from app.openai_compat import messages_to_prompt
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
