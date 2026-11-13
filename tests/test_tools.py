import json

from app import claude_cli
from app.openai_compat.tools import build_tools_section, parse_function_calls, render_tool_calls_xml


def test_parse_single_tool_call():
    text = ('Checking the weather.\n<function_calls>\n<invoke name="get_weather">\n'
            '<parameter name="city">Tokyo</parameter>\n</invoke>\n</function_calls>')
    calls, content = parse_function_calls(text, {"get_weather"})
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Tokyo"}
    assert content == "Checking the weather."


def test_parse_coerces_non_string_values():
    text = ('<function_calls><invoke name="search"><parameter name="limit">5</parameter>'
            '<parameter name="tags">["a","b"]</parameter></invoke></function_calls>')
    calls, _ = parse_function_calls(text, {"search"})
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"limit": 5, "tags": ["a", "b"]}


def test_unknown_tools_filtered_out():
    text = '<function_calls><invoke name="evil"><parameter name="x">1</parameter></invoke></function_calls>'
    calls, content = parse_function_calls(text, {"known"})
    assert calls is None
    assert content == text


def test_parse_tolerates_unclosed_block():
    text = 'Answer.<function_calls><invoke name="get_weather"><parameter name="city">Tokyo</parameter>'
    calls, content = parse_function_calls(text, None)
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Tokyo"}
    assert content == "Answer."


def test_parse_strips_code_fences():
    text = ('```\n<function_calls>\n<invoke name="f">\n<parameter name="x">1</parameter>\n'
            '</invoke>\n</function_calls>\n```')
    calls, content = parse_function_calls(text, None)
    assert calls[0]["function"]["name"] == "f"
    assert content == ""


def test_parse_tool_call_tags():
    text = ('Looking.\n<tool_call name="glob">\n<arg name="pattern">**/*.py</arg>\n</tool_call>\n'
            '<tool_call name="read">\n<arg name="filePath">README.md</arg>\n</tool_call>')
    calls, content = parse_function_calls(text, {"glob", "read"})
    assert [c["function"]["name"] for c in calls] == ["glob", "read"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"pattern": "**/*.py"}
    assert json.loads(calls[1]["function"]["arguments"]) == {"filePath": "README.md"}
    assert content == "Looking."


def test_parse_truncated_tool_call_tag():
    # A cut-off argument is dropped rather than passed on half-written.
    text = 'Ok.\n<tool_call name="write">\n<arg name="filePath">a.py</arg>\n<arg name="content">print(1)'
    calls, content = parse_function_calls(text, {"write"})
    assert json.loads(calls[0]["function"]["arguments"]) == {"filePath": "a.py"}
    assert content == "Ok."


def test_tool_call_tags_unknown_names_filtered():
    text = '<tool_call name="evil"><arg name="x">1</arg></tool_call>'
    calls, content = parse_function_calls(text, {"known"})
    assert calls is None
    assert content == text


def test_render_and_parse_round_trip():
    tool_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": json.dumps({"city": "Tokyo", "units": "metric"})},
    }]
    xml = render_tool_calls_xml(tool_calls)
    assert '<tool_call name="get_weather">' in xml
    assert "<invoke" not in xml and "<function_calls>" not in xml
    calls, _ = parse_function_calls(xml, {"get_weather"})
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Tokyo", "units": "metric"}


def test_build_tools_section_lists_functions_and_choice():
    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }]
    section = build_tools_section(tools, {"type": "function", "function": {"name": "get_weather"}})
    assert "## get_weather" in section
    assert "Get the weather" in section
    assert 'You MUST call the function "get_weather"' in section
    assert "<tool_call" in section
    assert "<invoke" not in section and "<function_calls>" not in section


def test_cli_malformed_tool_use_result_is_retried_once(monkeypatch):
    results = [{"result": claude_cli.MALFORMED_TOOL_USE_RESULT}, {"result": "ok"}]
    calls = []

    def fake(*args):
        calls.append(args)
        return results[len(calls) - 1], None

    monkeypatch.setattr(claude_cli, "_run_claude_once", fake)
    data, err = claude_cli.run_claude_once("hi", raw_model=True)
    assert err is None and data["result"] == "ok"
    assert len(calls) == 2


def test_cli_retry_reports_tokens_of_both_attempts(monkeypatch):
    results = [
        {"result": claude_cli.MALFORMED_TOOL_USE_RESULT, "total_cost_usd": 0.01,
         "usage": {"input_tokens": 5, "output_tokens": 40, "cache_read_input_tokens": 1000}},
        {"result": "ok", "total_cost_usd": 0.02,
         "usage": {"input_tokens": 5, "output_tokens": 10, "cache_read_input_tokens": 1000,
                   "service_tier": "standard"}},
    ]
    calls = []

    def fake(*args):
        calls.append(args)
        return results[len(calls) - 1], None

    monkeypatch.setattr(claude_cli, "_run_claude_once", fake)
    data, err = claude_cli.run_claude_once("hi", raw_model=True)
    assert err is None and data["result"] == "ok"
    assert data["usage"] == {"input_tokens": 10, "output_tokens": 50,
                             "cache_read_input_tokens": 2000, "service_tier": "standard"}
    assert abs(data["total_cost_usd"] - 0.03) < 1e-9


def test_parse_recovers_unclosed_arg_in_closed_block():
    # The "newString is missing and is required" bug: the model forgets the
    # final </arg> but does close the </tool_call> block.
    text = ('Editing.\n<tool_call name="edit">\n<arg name="filePath">a.py</arg>\n'
            '<arg name="oldString">x = 1</arg>\n<arg name="newString">x = 2\n</tool_call>')
    calls, content = parse_function_calls(text, {"edit"})
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"filePath": "a.py", "oldString": "x = 1", "newString": "x = 2"}
    assert content == "Editing."


def test_parse_recovers_unclosed_arg_followed_by_closed_arg():
    text = ('<tool_call name="edit">\n<arg name="oldString">x = 1\n'
            '<arg name="newString">x = 2</arg>\n</tool_call>')
    calls, _ = parse_function_calls(text, {"edit"})
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"oldString": "x = 1", "newString": "x = 2"}


def test_parse_strips_half_written_close_tag():
    text = ('<tool_call name="edit">\n<arg name="filePath">a.py</arg>\n'
            '<arg name="newString">x = 2</arg\n</tool_call>')
    calls, _ = parse_function_calls(text, {"edit"})
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"filePath": "a.py", "newString": "x = 2"}


def test_parse_single_quoted_names():
    text = "<tool_call name='read'>\n<arg name='filePath'>a.py</arg>\n</tool_call>"
    calls, _ = parse_function_calls(text, {"read"})
    assert calls[0]["function"]["name"] == "read"
    assert json.loads(calls[0]["function"]["arguments"]) == {"filePath": "a.py"}


def test_parse_parameter_tags_inside_tool_call_block():
    text = ('<tool_call name="read">\n<parameter name="filePath">a.py</parameter>\n</tool_call>')
    calls, _ = parse_function_calls(text, {"read"})
    assert json.loads(calls[0]["function"]["arguments"]) == {"filePath": "a.py"}


def test_truncated_last_block_still_drops_half_written_arg():
    # Bounded earlier block is recovered; the cut-off final block is not.
    text = ('<tool_call name="edit">\n<arg name="filePath">a.py</arg>\n'
            '<arg name="newString">x = 2\n'
            '<tool_call name="write">\n<arg name="filePath">b.py</arg>\n<arg name="content">print(')
    calls, _ = parse_function_calls(text, {"edit", "write"})
    assert json.loads(calls[0]["function"]["arguments"]) == {"filePath": "a.py", "newString": "x = 2"}
    assert json.loads(calls[1]["function"]["arguments"]) == {"filePath": "b.py"}


def test_reply_was_truncated_detection():
    from app.openai_compat.tools import reply_was_truncated
    # Complete replies, including a recovered unclosed arg, are not truncated.
    assert not reply_was_truncated("plain text answer")
    assert not reply_was_truncated('<tool_call name="read">\n<arg name="f">a</arg>\n</tool_call>')
    assert not reply_was_truncated('<tool_call name="e">\n<arg name="newString">x\n</tool_call>')
    # An opened but never-closed block means the generation was cut off.
    assert reply_was_truncated('Ok.\n<tool_call name="write">\n<arg name="content">print(')
    assert reply_was_truncated('<invoke name="write">\n<parameter name="content">print(')


def test_nonstream_truncated_reply_flagged(monkeypatch):
    from fastapi.testclient import TestClient
    from app.apis import openai as openai_api
    from app.config import settings
    from app.main import app

    def fake_run(prompt, model, session_id, system_prompt, raw_model=False, content_blocks=None):
        return {"result": "Half an answ", "usage": {}, "stop_reason": "max_tokens"}, None

    monkeypatch.setattr(openai_api, "run_claude_once", fake_run)
    client = TestClient(app)
    r = client.post("/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hi"}],
                          "tools": [{"type": "function", "function": {"name": "write"}}]},
                    headers={"Authorization": "Bearer %s" % settings.api_key})
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "length"
    assert "[token limit reached" in choice["message"]["content"]


def test_stream_truncated_reply_flagged(monkeypatch):
    from app.openai_compat import stream as stream_mod

    def fake_run(prompt, model, session_id, system_prompt, raw_model=False, content_blocks=None):
        return {"result": "Half an answ", "usage": {}, "stop_reason": "max_tokens"}, None

    monkeypatch.setattr(stream_mod, "run_claude_once", fake_run)
    out = b"".join(stream_mod.openai_stream(None, "hi", None, has_tools=True,
                                            tool_names={"write"}))
    assert b"[token limit reached" in out
    assert b'"finish_reason": "length"' in out or b'"finish_reason":"length"' in out


def test_stream_truncated_tool_call_keeps_calls_but_notes_limit(monkeypatch):
    # A recoverable call plus a cut-off one: the complete call is forwarded,
    # and the token-limit note is still shown.
    from app.openai_compat import stream as stream_mod

    text = ('<tool_call name="read">\n<arg name="filePath">a.py</arg>\n</tool_call>\n'
            '<tool_call name="write">\n<arg name="content">print(')

    def fake_run(prompt, model, session_id, system_prompt, raw_model=False, content_blocks=None):
        return {"result": text, "usage": {}}, None

    monkeypatch.setattr(stream_mod, "run_claude_once", fake_run)
    out = b"".join(stream_mod.openai_stream(None, "hi", None, has_tools=True,
                                            tool_names={"read", "write"}))
    assert b"[token limit reached" in out
    assert b'"name": "read"' in out
