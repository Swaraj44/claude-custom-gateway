# How Claude Custom Gateway Works — The Process, Step by Step

This document describes the exact process the service follows for every request, with worked examples at each stage. For setup instructions see the [README](../README.md).

---

## Table of Contents

- [Big Picture](#big-picture)
- [The Two API Surfaces](#the-two-api-surfaces)
- [Stage 0 — Shared Pre-Processing](#stage-0--shared-pre-processing)
- [Stage 1 — Native `/api/chat` Process](#stage-1--native-apichat-process)
- [Stage 2 — OpenAI-Compatible `/v1/chat/completions` Process](#stage-2--openai-compatible-v1chatcompletions-process)
- [The Function-Calling Bridge](#the-function-calling-bridge)
- [Streaming Details](#streaming-details)
- [Timeouts, Errors, and Cleanup](#timeouts-errors-and-cleanup)
- [Code Map](#code-map)

---

## Big Picture

```
                 ┌────────────────────────────────────────────────────────┐
                 │             Claude Custom Gateway (FastAPI)            │
                 │                                                        │
 client ──HTTP──▶│  auth ──▶ validate ──▶ transform ──▶ spawn CLI ──▶ ...  │
 client ◀─SSE───│                         (prompt /     claude -p        │
                 │                          parse)       (subprocess)     │
                 └────────────────────────────────────────────────────────┘
```

The service never talks to Anthropic's API directly. For every request it spawns a fresh `claude` CLI process, pipes the prompt in via **stdin**, and reads structured JSON/JSONL back from **stdout**:

```
client ──HTTP──> FastAPI (uvicorn) ──stdin──> claude -p --output-format stream-json --verbose
client <──SSE──── FastAPI (uvicorn) <─JSONL── claude
```

Key properties of this design:

- **No shell involved** — the CLI is invoked as an argument list with the prompt piped via stdin, so there is no shell-injection risk and no argument-length limits.
- **No shared state between `/v1` requests** — each request is a one-shot `claude -p` run; the client resends the full conversation every turn (standard OpenAI behavior). Only the native `/api/chat` endpoints support sessions (`--resume`).
- **Concurrency** — each request runs in FastAPI's threadpool, so blocking subprocess I/O from one request does not block others.

---

## The Two API Surfaces

| Surface | Endpoints | Who uses it | Behavior |
|---|---|---|---|
| **Native** | `POST /api/chat`, `POST /api/chat/stream` | Web UI, scripts | Prompt in → full Claude Code agent out (CLI tools enabled, sessions supported) |
| **OpenAI-compatible** | `GET /v1/models`, `POST /v1/chat/completions` | Kilo Code, Cline, etc. | OpenAI messages in → OpenAI response out. Runs the CLI in **raw-model mode** (all CLI tools disabled) and bridges function calling over XML |

---

## Stage 0 — Shared Pre-Processing

Every request to a protected endpoint passes through:

1. **API-key check** (`app/security.py`) — reads `Authorization: Bearer <key>` or `x-api-key`; compared against `CLAUDE_SERVICE_API_KEY` from `.env` (empty = auth disabled). Failure → `401`.
2. **Body validation** — Pydantic models (`app/schemas.py`) validate the JSON body. Failure → `400`, formatted as `{"error": ...}` (native) or OpenAI-style `{"error": {"message": ...}}` (`/v1/*`).
3. **CLI discovery** (once, at startup — `app/config.py`) — `shutil.which("claude")`, with fallbacks for `~/.local/bin/claude` and Windows npm paths.

---

## Stage 1 — Native `/api/chat` Process

The simplest path. Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{"prompt": "Explain recursion in one sentence"}'
```

Process:

1. **Build the command** (`build_cmd` in `app/claude_cli.py`). The prompt is *not* an argument — it goes to stdin:

   ```bash
   claude -p --output-format json
   # with options:
   claude -p --output-format json --model sonnet --resume b2f289c9-...
   ```

2. **Run and capture** (`run_claude_once`) — `subprocess.run` with the prompt as stdin, `CLAUDE_SERVICE_TIMEOUT` (default 600 s) as the timeout.

3. **Parse the CLI's JSON result.** The CLI prints a single JSON object; the service extracts the relevant fields:

   ```json
   {
     "type": "result",
     "result": "Recursion is when a function solves a problem by calling itself on smaller inputs...",
     "session_id": "b2f289c9-...",
     "total_cost_usd": 0.068,
     "duration_ms": 1787,
     "usage": {"input_tokens": 10, "output_tokens": 22}
   }
   ```

4. **Respond** with the native shape:

   ```json
   {
     "response": "Recursion is when a function solves a problem by calling itself on smaller inputs...",
     "session_id": "b2f289c9-...",
     "cost_usd": 0.068,
     "duration_ms": 1787,
     "is_error": false
   }
   ```

**Multi-turn:** pass the returned `session_id` back in the next request. The service adds `--resume <session_id>`, and the CLI itself replays the conversation — no transcript is resent.

---

## Stage 2 — OpenAI-Compatible `/v1/chat/completions` Process

This is where most of the transformation work happens. Example request with tools:

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "model": "sonnet",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "What is the weather in Tokyo?"}
    ],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
          "type": "object",
          "properties": {"city": {"type": "string"}},
          "required": ["city"]
        }
      }
    }]
  }'
```

Step by step:

### 2.1 Flatten messages into a transcript (`messages_to_prompt`)

OpenAI sends an array of `system` / `user` / `assistant` / `tool` messages. The CLI expects one prompt. So:

- **`system` messages** are collected, joined, truncated to 100,000 chars, and later written to a temp file passed as `--system-prompt-file` (this *replaces* Claude Code's own agent system prompt). A file rather than an argument, because agent system prompts often exceed Windows' 32,767-char command-line limit, which fails the spawn with WinError 206. With no `system` message, a one-line default (`You are a helpful assistant.`) is passed instead — otherwise the CLI would fall back to its ~3k-token coding-agent prompt on every call.
- **The remaining turns** become Anthropic content blocks, sent to the CLI as a stream-json user message: a fixed header block, then **one text block per turn** (`User: ...` / `Assistant: ...`), with any images right after their turn:

  ```
  [header]  Below is the conversation so far, one message per block. Continue as the Assistant ...
  [block]   User: What is the weather in Tokyo?
  [block]   Assistant: <tool_call name="get_weather">...</tool_call>
  [block]   User: <tool_result name="get_weather">...</tool_result>
  ```

  The instruction lives in the leading header (not at the end), so request N's blocks are an exact prefix of request N+1's — see [prompt caching](#prompt-caching--verified-working-through-the-bridge). A plain single-turn request without `tools` is still sent as raw text; with `tools` (an agent loop) even the first turn uses blocks so it gets cached for the second.

- **`assistant` turns containing `tool_calls`** are rendered back into the `<tool_call>` XML format (see [the bridge](#the-function-calling-bridge)).
- **`tool` result messages** are grouped into a single `User` turn of `<tool_result name="...">` blocks.

### 2.2 Inject the tool definitions (`build_tools_section`)

When `tools` are present, a "Tool Use" section is appended to the system prompt. It teaches the model the XML call format, lists every function with its JSON schema, and honors `tool_choice`:

```
# Tool Use

You can call functions by including blocks like this in your reply:

<tool_call name="function_name">
<arg name="parameter_name">value</arg>
</tool_call>

Rules:
- Use exactly this <tool_call>/<arg> format for every call.
- Argument values: strings as plain text; numbers, booleans, arrays, and objects in JSON form.
- To call several functions, write several <tool_call> blocks one after another.
- Put tool calls at the END of your reply, never inside code fences.
- If no tool call is needed, reply normally without any <tool_call> block.
- The results will be provided to you as <tool_result> blocks in the next turn.

# Functions

## get_weather
Get current weather for a city
Parameters: {"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}
```

**Why not Claude's native `<function_calls>`/`<invoke>` syntax?** When the model writes that syntax as plain text, the API treats it as a real tool call (`stop_reason: "tool_use"`). The CLI runs with no tools, so the call is unusable; the CLI retries once and then returns the literal text `The model's tool call could not be parsed (retry also failed).` as the reply. In testing this hit about half of Kilo Code-style agent requests on sonnet. The distinct `<tool_call>`/`<arg>` tags avoid it entirely (0 failures in 8 identical runs, and 4/4 multi-turn streaming agent sessions). As a safety net, if the CLI still returns that text, the gateway reruns the call once.

### 2.3 Spawn the CLI in raw-model mode

```bash
claude -p --output-format json \
  --tools "" --strict-mcp-config \
  --system-prompt-file /tmp/claude-gw-system-XXXX.txt \   # "You are a concise assistant.\n\n# Tool Use\n..."
  --model sonnet
```

`--tools "" --strict-mcp-config` disables *all* Claude Code built-in tools and MCP servers, so the model answers purely from the messages the client sent — it can never read/write files itself. Tool execution is entirely the client's job.

### 2.4 Parse the reply (`parse_function_calls`)

Suppose the CLI's `result` is:

```
I'll check the weather for you.

<tool_call name="get_weather">
<arg name="city">Tokyo</arg>
</tool_call>
```

The parser extracts the block and converts it into OpenAI `tool_calls` (assigning a generated `call_...` id). The text before the block becomes the message `content`. It is deliberately forgiving:

- unclosed `<tool_call>` blocks (truncated output); an argument cut off mid-value is dropped rather than passed on half-written
- the legacy `<function_calls>`/`<invoke>`/`<parameter>` syntax, including unclosed blocks and bare `<invoke>` blocks (validated against the requested tool names so quoted examples in ordinary text are not misparsed)
- markdown code fences around blocks
- non-string parameter values (`"42"` → `42`, `"true"` → `true`, arrays/objects parsed from JSON)

### 2.5 Respond in OpenAI shape

```json
{
  "id": "chatcmpl-9f3a...",
  "object": "chat.completion",
  "created": 1760000000,
  "model": "sonnet",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "I'll check the weather for you.",
      "tool_calls": [{
        "id": "call_a1b2c3...",
        "type": "function",
        "function": {"name": "get_weather", "arguments": "{\"city\": \"Tokyo\"}"}
      }]
    },
    "finish_reason": "tool_calls"
  }],
  "usage": {"prompt_tokens": 180, "completion_tokens": 45, "total_tokens": 225}
}
```

The client executes the tool and sends the result back as a `tool` message; the loop repeats.

---

## The Function-Calling Bridge

A full agent loop across the bridge, showing exactly what crosses the wire at each turn:

**Turn 1 — client sends the request** (the example above).

**Turn 2 — client returns the tool result:**

```json
{
  "model": "sonnet",
  "messages": [
    {"role": "system", "content": "You are a concise assistant."},
    {"role": "user", "content": "What is the weather in Tokyo?"},
    {"role": "assistant", "content": null, "tool_calls": [{
      "id": "call_a1b2c3...",
      "type": "function",
      "function": {"name": "get_weather", "arguments": "{\"city\": \"Tokyo\"}"}
    }]},
    {"role": "tool", "tool_call_id": "call_a1b2c3...", "content": "{\"temperature\": 18, \"condition\": \"light rain\"}"}
  ],
  "tools": ["... same as before ..."]
}
```

**What the service flattens this into** (content blocks sent to the CLI via stdin as a stream-json user message; the last block carries the cache marker):

```
[text] Below is the conversation so far, one message per block. Continue as the Assistant by responding to the last message. If it contains tool results, use them to proceed: either make the next tool calls or give your final answer.
[text] User: What is the weather in Tokyo?
[text] Assistant: <tool_call name="get_weather">
       <arg name="city">Tokyo</arg>
       </tool_call>
[text] User: <tool_result name="get_weather">
       {"temperature": 18, "condition": "light rain"}
       </tool_result>          ← cache_control: {"type": "ephemeral", "ttl": "1h"}
```

**Turn 3 — the model answers without another call**, so the parser finds no XML block, `finish_reason` is `"stop"`, and the plain text is returned as `content` — a normal chat completion.

Parallel calls (multiple `<tool_call>` blocks in one reply) come back as multiple `tool_calls` entries, all with `finish_reason: "tool_calls"`.

---

## Streaming Details

The CLI's `--output-format stream-json --verbose` mode prints JSONL events. The service consumes them with `claude_events` (`app/claude_cli.py`) and re-emits them in two formats:

**Native SSE** (`/api/chat/stream`):

```
data: {"text": "Recursion is"}

data: {"text": " when a function..."}

data: {"done": true, "session_id": "b2f289c9-...", "cost_usd": 0.068, "duration_ms": 1787, "is_error": false}
```

**OpenAI chunks** (`/v1/chat/completions` with `"stream": true`):

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"4"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{...}}

data: [DONE]
```

Event mapping (`app/claude_cli.py:claude_events` → `app/apis/chat.py` / `app/openai_compat/stream.py`):

| CLI `stream-json` event | Becomes |
|---|---|
| `{"type": "assistant", "message": {"content": [{"type": "text", ...}]}}` | a text chunk (native `{"text": ...}` / OpenAI `delta.content`) |
| `{"type": "result", ...}` | the final event with session id, cost, duration, usage |
| non-zero exit / invalid JSON / no result | an error event (see below) |

**Important:** when the request contains `tools`, streaming is **buffered** — the service runs the CLI to completion via `run_claude_once` before emitting anything, because tool calls must be parsed whole. The content arrives as one chunk, followed by `tool_calls` chunks. Without tools, chunks stream live as the CLI produces them.

### Prompt caching — verified working through the bridge

The `claude` CLI puts cache breakpoints on the system prompt but **not** on the user message, so on its own only the system prompt is reused — the conversation history would be re-written to cache (at 1.25–2× input price) on every turn. The bridge fixes this:

1. The conversation is sent as one content block per turn behind a fixed header (see [2.1](#21-flatten-messages-into-a-transcript-messages_to_prompt)), so each request is a block-for-block prefix of the next.
2. The last block carries `cache_control: {"type": "ephemeral", "ttl": "1h"}` (`CLAUDE_SERVICE_PROMPT_CACHE_TTL`). The TTL must match the CLI's own breakpoints (`1h` on subscription logins), because a `1h` breakpoint may not follow a `5m` one.
3. The CLI is run with a clean environment: variables inherited from a parent Claude Code session (which would add a per-call scratchpad path to every prompt) are dropped, and `CLAUDE.md` / auto-memory are disabled for `/v1` calls.

Verified live (Claude Code 2.1.267, sonnet, ~17k-token system prompt + tools, 11k-token first user message):

| | cache write | cache read | cost |
|---|---|---|---|
| Turn 2, before | 11,186 | 17,108 (system only) | $0.060 |
| Turn 2, after | 408 | 27,767 (system + history) | $0.019 |

The `/v1` response `usage` block surfaces this (non-streaming and streaming, final chunk):

```json
{
  "prompt_tokens": 2,
  "completion_tokens": 10,
  "total_tokens": 12,
  "prompt_tokens_details": {"cached_tokens": 6031},
  "cache_creation_input_tokens": 497,
  "cache_read_input_tokens": 6031
}
```

`prompt_tokens_details.cached_tokens` is the standard OpenAI field (tools that display cached tokens will show it); the `cache_*_input_tokens` fields are Anthropic's raw names. Fields are omitted when zero. With the default `1h` TTL, a conversation stays cached for an hour of inactivity.

---

## Timeouts, Errors, and Cleanup

- **Timeout:** every CLI process is killed after `CLAUDE_SERVICE_TIMEOUT` seconds (default 600). Non-streaming runs use `subprocess.run(timeout=...)`; streaming runs use a `threading.Timer` plus `os.killpg` (the process is started with `start_new_session=True` so the whole process group dies, leaving no orphans).
- **stdin feeding:** the prompt is written by a daemon thread so a large prompt can never deadlock the reader loop.
- **Error mapping:**

  | Condition | Status | Notes |
  |---|---|---|
  | `claude` binary missing | `500` | checked at spawn time (`FileNotFoundError`) |
  | CLI non-zero exit / bad JSON | `502` | stderr (or first 500 chars of stdout) surfaced as the message |
  | Timeout | `504` | process group killed |
  | Missing/invalid API key | `401` | all `/api/*` and `/v1/*` endpoints |

- **Stream errors:** on `/v1/chat/completions` streaming the HTTP status is already 200 when a failure occurs, so the error is emitted as a content delta prefixed with `[service error]`, followed by a normal `finish_reason: "stop"` chunk and `data: [DONE]`. The native stream emits `{"error": "...", "done": true}` instead.

---

## Code Map

| File | Responsibility |
|---|---|
| `app/main.py` | App factory, CORS, error formatting, startup banner, uvicorn entry |
| `app/config.py` | Environment-variable settings + `claude` binary discovery |
| `app/security.py` | API-key check (`Bearer` / `x-api-key`) |
| `app/schemas.py` | Pydantic request/response models |
| `app/claude_cli.py` | Command building, subprocess lifecycle, JSONL event parsing, timeout/kill logic |
| `app/apis/chat.py` | Native `/api/chat` + `/api/chat/stream` endpoints |
| `app/apis/openai.py` | `/v1/models` + `/v1/chat/completions` endpoints |
| `app/openai_compat/prompt.py` | OpenAI messages → flattened transcript + system prompt |
| `app/openai_compat/tools.py` | Tool-section builder, XML renderer, tolerant XML parser |
| `app/openai_compat/stream.py` | CLI results → OpenAI response objects / SSE chunks |
| `app/static/index.html` | Web UI |
