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
