import json

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


def test_render_and_parse_round_trip():
    tool_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": json.dumps({"city": "Tokyo", "units": "metric"})},
    }]
    xml = render_tool_calls_xml(tool_calls)
    assert '<invoke name="get_weather">' in xml
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
