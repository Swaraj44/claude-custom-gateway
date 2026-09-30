"""OpenAI-compatibility layer: prompt flattening, tool-call bridge, and streaming."""

from app.openai_compat.prompt import messages_to_prompt, messages_to_prompt_and_blocks
from app.openai_compat.stream import openai_stream, usage_dict
from app.openai_compat.tools import build_tools_section, parse_function_calls, render_tool_calls_xml

__all__ = [
    "build_tools_section",
    "messages_to_prompt",
    "messages_to_prompt_and_blocks",
    "openai_stream",
    "parse_function_calls",
    "render_tool_calls_xml",
    "usage_dict",
]
