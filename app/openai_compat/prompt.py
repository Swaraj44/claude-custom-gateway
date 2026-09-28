"""Flatten OpenAI-style messages into a single CLI prompt."""

from typing import List, Optional, Tuple

from app.config import settings
from app.openai_compat.tools import render_tool_calls_xml, xml_escape
from app.schemas import OpenAIMessage


def messages_to_prompt(messages: List[OpenAIMessage]) -> Tuple[str, Optional[str]]:
    system_parts = []
    turns = []
    tool_names = {}
    pending_results = []

    def flush_results():
        if not pending_results:
            return
        results = "\n".join(
            "<result>\n<name>%s</name>\n<output>%s</output>\n</result>" % (name, xml_escape(content))
            for name, content in pending_results
        )
        turns.append(("User", "<function_results>\n%s\n</function_results>" % results))
        pending_results.clear()

    for m in messages:
        role = (m.role or "").lower()
        if role == "system":
            text = m.text()
            if text.strip():
                system_parts.append(text)
        elif role == "tool":
            name = tool_names.get(m.tool_call_id or "", m.name or "tool")
            pending_results.append((name, m.text()))
        elif role == "assistant":
            flush_results()
            parts = []
            text = m.text()
            if text.strip():
                parts.append(text)
            if m.tool_calls:
                parts.append(render_tool_calls_xml(m.tool_calls))
                for tc in m.tool_calls:
                    fn = tc.get("function") or {}
                    if tc.get("id") and fn.get("name"):
                        tool_names[tc["id"]] = fn["name"]
            if parts:
                turns.append(("Assistant", "\n\n".join(parts)))
        elif role == "user":
            flush_results()
            text = m.text()
            if text.strip():
                turns.append(("User", text))
    flush_results()
    system_prompt = "\n\n".join(system_parts)[:settings.system_prompt_max] or None
    if not turns:
        return "", system_prompt
    if len(turns) == 1:
        prompt = turns[0][1]
    else:
        history = "\n\n".join("%s: %s" % (r, t) for r, t in turns)
        if turns[-1][0] == "User" and turns[-1][1].startswith("<function_results>"):
            prompt = ("Conversation so far:\n%s\n\nContinue as the Assistant: use the tool results above to "
                      "proceed. Either make the next tool calls or give your final answer." % history)
        else:
            prompt = "Conversation so far:\n%s\n\nRespond as the Assistant to the last message above." % history
    return prompt, system_prompt
