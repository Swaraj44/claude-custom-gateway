# How ClaudeBridge Works — The Process, Step by Step

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
                 │                    ClaudeBridge (FastAPI)              │
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

1. **API-key check** (`app/security.py`) — reads `Authorization: Bearer <key>` or `x-api-key`; compared against `CLAUDE_SERVICE_API_KEY` (default `swaraj`, empty = auth disabled). Failure → `401`.
2. **Body validation** — Pydantic models (`app/schemas.py`) validate the JSON body. Failure → `400`, formatted as `{"error": ...}` (native) or OpenAI-style `{"error": {"message": ...}}` (`/v1/*`).
3. **CLI discovery** (once, at startup — `app/config.py`) — `shutil.which("claude")`, with fallbacks for `~/.local/bin/claude` and Windows npm paths.

---

## Stage 1 — Native `/api/chat` Process

The simplest path. Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer swaraj" \
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
  -H "Authorization: Bearer swaraj" \
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

- **`system` messages** are collected, joined, truncated to 100,000 chars, and later passed as `--system-prompt` (this *replaces* Claude Code's own agent system prompt).
- **The remaining turns** are flattened into a `Role: text` transcript. A single turn is sent as-is; multiple turns become:

  ```
  Conversation so far:
  User: What is the weather in Tokyo?

  Respond as the Assistant to the last message above.
  ```

- **`assistant` turns containing `tool_calls`** are rendered back into the `<function_calls>` XML format (see [the bridge](#the-function-calling-bridge)).
- **`tool` result messages** are grouped into a single `User` turn wrapped in `<function_results>`. If that is the *last* turn, the closing instruction changes to tell the model to continue from the tool results.

### 2.2 Inject the tool definitions (`build_tools_section`)

When `tools` are present, a "Tool Use" section is appended to the system prompt. It teaches the model the XML call format, lists every function with its JSON schema, and honors `tool_choice`:

```
# Tool Use

You can invoke functions by including a block like this in your reply:

<function_calls>
<invoke name="function_name">
<parameter name="parameter_name">value</parameter>
</invoke>
</function_calls>

Rules:
- Parameter values: strings as plain text; numbers, booleans, arrays, and objects in JSON form.
- To call several functions, include multiple <invoke> blocks inside one <function_calls> block.
- Put tool calls at the END of your reply, never inside code fences.
- If no tool call is needed, reply normally without the block.
- The result of each call will be provided to you as a <function_results> block in the next turn.

# Functions

## get_weather
Get current weather for a city
Parameters: {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
```

### 2.3 Spawn the CLI in raw-model mode

```bash
claude -p --output-format json \
  --tools "" --strict-mcp-config \
  --system-prompt "You are a concise assistant.\n\n# Tool Use\n..." \
  --model sonnet
```

`--tools "" --strict-mcp-config` disables *all* Claude Code built-in tools and MCP servers, so the model answers purely from the messages the client sent — it can never read/write files itself. Tool execution is entirely the client's job.

### 2.4 Parse the reply (`parse_function_calls`)

Suppose the CLI's `result` is:

```
I'll check the weather for you.

<function_calls>
<invoke name="get_weather">
<parameter name="city">Tokyo</parameter>
</invoke>
</function_calls>
```

The parser extracts the block and converts it into OpenAI `tool_calls` (assigning a generated `call_...` id). The text before the block becomes the message `content`. It is deliberately forgiving:

- unclosed `<function_calls>` blocks (truncated output)
- missing opening tag (bare `<invoke>` blocks) — validated against the requested tool names so quoted examples in ordinary text are not misparsed
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

**What the service flattens this into** (sent to the CLI via stdin):

```
Conversation so far:
User: What is the weather in Tokyo?

Assistant: <function_calls>
<invoke name="get_weather">
<parameter name="city">Tokyo</parameter>
</invoke>
</function_calls>

User: <function_results>
<result>
<name>get_weather</name>
<output>{"temperature": 18, "condition": "light rain"}</output>
</result>
</function_results>

Continue as the Assistant: use the tool results above to proceed. Either make the next tool calls or give your final answer.
```

**Turn 3 — the model answers without another call**, so the parser finds no XML block, `finish_reason` is `"stop"`, and the plain text is returned as `content` — a normal chat completion.

Parallel calls (multiple `<invoke>` blocks in one reply) come back as multiple `tool_calls` entries, all with `finish_reason: "tool_calls"`.

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

The `claude` CLI marks cache breakpoints on its internal API calls even in one-shot `-p` mode, and the bridge keeps the flattened prompt **append-only** (turns 1..N stay byte-identical when turn N+1 is appended) and the system prompt byte-stable across turns — so consecutive requests within Anthropic's ~5-minute cache TTL **do hit the cache**. Verified live (Claude Code 2.1.267, sonnet, ~6.5k-token system prefix):

- Request 1 (first turn): `cache_creation_input_tokens: 6474` — prefix written to cache
- Request 2 (same prefix + one more turn, seconds later): `cache_read_input_tokens: 6031`, `cache_creation_input_tokens: 497` — ~92% of the input served from cache

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

`prompt_tokens_details.cached_tokens` is the standard OpenAI field (tools that display cached tokens will show it); the `cache_*_input_tokens` fields are Anthropic's raw names. Fields are omitted when zero. Cache expires after ~5 minutes of inactivity, so long thinking gaps between agent turns fall back to full-price input.

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
