"""Function-calling bridge: parse and render Claude's XML tool-call format."""

import html
import json
import re
import uuid
from typing import Any, List, Optional

FUNCTION_CALLS_BLOCK_RE = re.compile(r"<function_calls>(.*?)</function_calls>", re.DOTALL)
INVOKE_RE = re.compile(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', re.DOTALL)
INVOKE_OPEN_RE = re.compile(r'<invoke\s+name="([^"]+)"\s*>')
PARAM_RE = re.compile(r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>', re.DOTALL)
PARAM_OPEN_RE = re.compile(r'<parameter\s+name="([^"]+)"\s*>')


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def param_value_to_xml(v) -> str:
    if isinstance(v, str):
        return xml_escape(v)
    return xml_escape(json.dumps(v, ensure_ascii=False))


def render_tool_calls_xml(tool_calls: List[dict]) -> str:
    invokes = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        raw_args = fn.get("arguments")
        if isinstance(raw_args, str):
            try:
                params = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                params = {}
        elif isinstance(raw_args, dict):
            params = raw_args
        else:
            params = {}
        params_xml = "\n".join(
            '<parameter name="%s">%s</parameter>' % (k, param_value_to_xml(v))
            for k, v in params.items()
        )
        invokes.append('<invoke name="%s">\n%s\n</invoke>' % (name, params_xml))
    return "<function_calls>\n%s\n</function_calls>" % "\n".join(invokes)


def coerce_param_value(raw: str):
    v = raw.strip()
    if not v:
        return ""
    if v[0] in '"{[':
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return raw
    if v in ("true", "false"):
        return v == "true"
    if v == "null":
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, ValueError):
        return raw


def strip_code_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else ""
    if content.endswith("```"):
        content = content[: content.rfind("```")].rstrip()
    return content.strip()


def build_tool_call(name: str, body: str) -> Optional[dict]:
    if not name:
        return None
    params = {}
    for p in PARAM_RE.finditer(body):
        params[p.group(1).strip()] = coerce_param_value(html.unescape(p.group(2).strip()))
    if not params:
        for p in PARAM_OPEN_RE.finditer(body):
            fragment = body[p.end():]
            nxt = PARAM_OPEN_RE.search(fragment)
            if nxt:
                fragment = fragment[: nxt.start()]
            params[p.group(1).strip()] = coerce_param_value(html.unescape(fragment.strip()))
    return {
        "id": "call_" + uuid.uuid4().hex[:24],
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(params, ensure_ascii=False)},
    }


def parse_invokes(block: str) -> List[dict]:
    calls = []
    for inv in INVOKE_RE.finditer(block):
        call = build_tool_call(inv.group(1).strip(), inv.group(2))
        if call:
            calls.append(call)
    if calls:
        return calls
    for m in INVOKE_OPEN_RE.finditer(block):
        body = block[m.end():]
        nxt = INVOKE_OPEN_RE.search(body)
        if nxt:
            body = body[: nxt.start()]
        call = build_tool_call(m.group(1).strip(), body)
        if call:
            calls.append(call)
    return calls


def parse_function_calls(text: str, known_names: Optional[set] = None):
    def valid(calls):
        if not calls:
            return []
        if known_names:
            return [c for c in calls if c["function"]["name"] in known_names]
        return calls

    blocks = list(FUNCTION_CALLS_BLOCK_RE.finditer(text))
    if blocks:
        calls = []
        for block in blocks:
            calls.extend(parse_invokes(block.group(1)))
        calls = valid(calls)
        if calls:
            content = strip_code_fences(text[: blocks[0].start()] + text[blocks[-1].end():])
            return calls, content
    start = text.find("<function_calls>")
    if start != -1:
        block = text[start + len("<function_calls>"):].split("</function_calls>")[0]
        calls = valid(parse_invokes(block))
        if calls:
            content = strip_code_fences(text[:start])
            return calls, content
    if known_names:
        invokes = list(INVOKE_RE.finditer(text))
        if invokes:
            calls = []
            for m in invokes:
                call = build_tool_call(m.group(1).strip(), m.group(2))
                if call:
                    calls.append(call)
            calls = valid(calls)
            if calls:
                end = invokes[-1].end()
                tail = text[end:].lstrip()
                if tail.startswith("</function_calls>"):
                    end = len(text) - len(tail) + len("</function_calls>")
                content = strip_code_fences(text[: invokes[0].start()] + text[end:])
                return calls, content
    return None, text


def build_tools_section(tools: List[dict], tool_choice: Optional[Any] = None) -> str:
    lines = [
        "# Tool Use",
        "",
        "You can invoke functions by including a block like this in your reply:",
        "",
        "<function_calls>",
        '<invoke name="function_name">',
        '<parameter name="parameter_name">value</parameter>',
        "</invoke>",
        "</function_calls>",
        "",
        "Rules:",
        "- Parameter values: strings as plain text; numbers, booleans, arrays, and objects in JSON form.",
        "- To call several functions, include multiple <invoke> blocks inside one <function_calls> block.",
        "- Put tool calls at the END of your reply, never inside code fences.",
        "- If no tool call is needed, reply normally without the block.",
        "- The result of each call will be provided to you as a <function_results> block in the next turn.",
        "",
        "# Functions",
        "",
    ]
    for t in tools:
        fn = t.get("function") or {}
        name = fn.get("name", "")
        desc = fn.get("description", "")
        schema = fn.get("parameters") or fn.get("input_schema") or {"type": "object", "properties": {}}
        lines.append("## %s" % name)
        if desc:
            lines.append(desc)
        lines.append("Parameters: %s" % json.dumps(schema, ensure_ascii=False))
        lines.append("")
    if tool_choice:
        if isinstance(tool_choice, str) and tool_choice == "required":
            lines.append("You MUST call at least one function in your reply.")
        elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
            fname = (tool_choice.get("function") or {}).get("name")
            if fname:
                lines.append('You MUST call the function "%s" in your reply.' % fname)
    return "\n".join(lines)
