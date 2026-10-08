# Claude Custom Gateway

**A streaming REST gateway to the Claude Code CLI.** It exposes a web UI, a native chat API, and an **OpenAI-compatible API** (`/v1/chat/completions` + `/v1/models`, **including function calling**) so third-party coding agents like **Kilo Code** can use your Claude CLI subscription as a custom provider — chat and agent modes included.

> **In short:** you authenticate once with the Claude CLI, run this service locally, and any OpenAI-compatible tool can talk to Claude through it.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1 — Install &amp; Authenticate the Claude CLI](#step-1--install--authenticate-the-claude-cli)
- [Step 2 — Set Up This Project](#step-2--set-up-this-project)
- [Step 3 — Run the Service](#step-3--run-the-service)
- [Configuration](#configuration)
- [Connect Third-Party Coding Agents](#connect-third-party-coding-agents)
- [Endpoints](#endpoints)
- [API Examples](#api-examples)
- [How It Works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

## Prerequisites

| Requirement            | Notes                                                      |
| ---------------------- | ---------------------------------------------------------- |
| Python 3.9+            | `python --version` to check                              |
| Claude Code CLI        | Installed, on PATH,**and authenticated** (see below) |
| (Optional) Node.js 18+ | Only if you install the CLI via npm                        |

> **Important:** This service does not handle Claude authentication itself — it shells out to the `claude` CLI. You **must** install the CLI and log in before using this project.

> **Platform support:** These setup instructions have been **fully tested on Linux**. The Windows and macOS instructions are provided as guidance but **have not been tested yet** — if you hit a problem on those platforms, see [Troubleshooting](#troubleshooting).

## Step 1 — Install & Authenticate the Claude CLI

Pick your operating system. After installing, run `claude` once in your terminal and follow the login flow (browser-based OAuth with your Claude Pro/Max account, or an Anthropic Console API key).

### Linux (tested)

**Option A — Native installer:**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Option B — npm:**

```bash
npm install -g @anthropic-ai/claude-code
```

**Authenticate:**

```bash
claude
```

Follow the interactive login wizard (Claude account via browser, or Console API key).

### Windows (untested)

**Option A — Native installer (PowerShell):**

```powershell
irm https://claude.ai/install.ps1 | iex
```

**Option B — npm:**

```powershell
npm install -g @anthropic-ai/claude-code
```

> **WSL note:** The CLI also runs great inside WSL. If you prefer that route, follow the Linux instructions inside your WSL distro and run this service there too — that path is covered by the tested Linux setup.

**Authenticate:**

```powershell
claude
```

The first run starts the login wizard — choose **Claude account** (Pro/Max subscription) or **Anthropic Console account** (API key) and complete the flow in your browser.

### macOS (untested)

**Option A — Native installer:**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Option B — npm:**

```bash
npm install -g @anthropic-ai/claude-code
```

**Option C — Homebrew:**

```bash
brew install --cask claude-code
```

**Authenticate:**

```bash
claude
```

Follow the interactive login wizard (Claude account via browser, or Console API key).

### Verify the installation (all platforms)

```bash
claude --version
```

If that prints a version, you're done with Step 1. If not, see [Troubleshooting](#troubleshooting).

---

## Step 2 — Set Up This Project

Clone the repository, create a virtual environment, and install dependencies.

### Linux (tested)

```bash
git clone <repository-url>
cd claude-custom-gateway
python3 -m venv .venv        # or: uv venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### macOS (untested)

Same as Linux — `python3` may be just `python` depending on your install.

### Windows (PowerShell, untested)

```powershell
git clone <repository-url>
cd claude-custom-gateway
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If activation is blocked by execution policy, allow scripts for the current user once:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### Windows (Command Prompt, untested)

```bat
git clone <repository-url>
cd claude-custom-gateway
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

---

## Step 3 — Run the Service

With the virtual environment activated (same command on every OS):

```bash
python -m app
```

The service binds to `0.0.0.0:6069`:

- **This machine:** open [http://127.0.0.1:6069/](http://127.0.0.1:6069/)
- **Other devices on your LAN:** `http://<your-LAN-IP>:6069/`
  - Linux: find your IP with `hostname -I`
  - macOS: `ipconfig getifaddr en0`
  - Windows (PowerShell): `Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress`

Alternative — run with auto-reload during development:

```bash
uvicorn app.main:app --reload --port 6069
```

Optional — install as a package with a `claude-custom-gateway` console command:

```bash
pip install -e .
claude-custom-gateway
```

Installing the package also adds two commands that choose whether request/response payloads are logged:

| Command          | Payload logging | Use for                                                                                     |
| ---------------- | --------------- | ------------------------------------------------------------------------------------------- |
| `claude-pro`   | Off             | Normal use — same as `python -m app`; only uvicorn's one-line access log is printed        |
| `claude-debug` | On              | Debugging — prints every request body (`-->`) and response body (`<--`), pretty-printed JSON |

```bash
claude-pro     # quiet
claude-debug   # logs full request and response payloads
```

Example `claude-debug` output:

```
INFO:     --> POST /v1/chat/completions
{
  "model": "sonnet",
  "messages": [...]
}
INFO:     <-- POST /v1/chat/completions 200 (5321 ms)
{ ... }
```

Streaming (SSE) responses still reach the client chunk by chunk; the full body is logged once the stream finishes. Debug logs contain full prompts, responses, and base64 image data — cap each logged payload with `CLAUDE_SERVICE_LOG_PAYLOAD_MAX` (e.g. `CLAUDE_SERVICE_LOG_PAYLOAD_MAX=5000 claude-debug`).

### Configuration (environment variables)

| Variable                            | Default     | Description                                                                                                                                                                                                                                                                                                                     |
| ----------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE_SERVICE_HOST`             | `0.0.0.0` | Bind address (all interfaces)                                                                                                                                                                                                                                                                                                   |
| `CLAUDE_SERVICE_PORT`             | `6069`    | Port                                                                                                                                                                                                                                                                                                                            |
| `CLAUDE_SERVICE_TIMEOUT`          | `600`     | Per-request timeout in seconds                                                                                                                                                                                                                                                                                                  |
| `CLAUDE_SERVICE_API_KEY`          | `swaraj`  | API key required on all`/api/*` and `/v1/*` endpoints via `Authorization: Bearer <key>` or `x-api-key` header. Empty = disable                                                                                                                                                                                          |
| `CLAUDE_SERVICE_VISION_MODEL`     | `sonnet`  | Model used for `/v1/chat/completions` requests that contain images and omit `model` |
| `CLAUDE_SERVICE_PROMPT_CACHE_TTL` | `1h`      | Prompt-cache TTL for conversation history on`/v1/chat/completions` (`1h`, `5m`, or `off`). Each turn reads earlier turns from cache instead of re-sending them at full price. Must match the CLI's own cache TTL: `1h` for Claude subscription logins; try `5m` if requests fail with a `cache_control.ttl` error |
| `CLAUDE_SERVICE_EFFORT`           | _(unset)_ | Optional`--effort` level (`low`, `medium`, `high`, `xhigh`, `max`) for `/v1/chat/completions`. Lower effort = fewer thinking/output tokens                                                                                                                                                                        |
| `CLAUDE_SERVICE_LOG_PAYLOADS`     | `0`       | Log every request/response body (`1` to enable). `claude-debug` forces it on, `claude-pro` forces it off; applies to `python -m app` / `claude-custom-gateway` |
| `CLAUDE_SERVICE_LOG_PAYLOAD_MAX`  | `0`       | Truncate each logged payload to this many characters (`0` = no limit)                                                                                     |

**Set a variable before launching — per OS:**

```bash
# Linux / macOS (tested on Linux)
CLAUDE_SERVICE_PORT=9000 python -m app
```

```powershell
# Windows (PowerShell) — untested
$env:CLAUDE_SERVICE_PORT = "9000"
python -m app
```

```bat
:: Windows (Command Prompt) — untested
set CLAUDE_SERVICE_PORT=9000
python -m app
```

See [`.env.example`](.env.example) for reference (the service reads process environment variables; it does not load the file automatically).

---

## Connect Third-Party Coding Agents

The service implements the OpenAI-compatible `/v1/models` and `/v1/chat/completions` endpoints that most tools expect, so **any coding agent that supports a custom OpenAI-compatible provider** can connect — Kilo Code, Cline, Roo Code, Continue, LibreChat, and more.

### Kilo Code (example)

1. **Start the service** and keep it running:

   ```bash
   python -m app
   ```
2. In VS Code, open **Kilo Code**, click the **Settings** gear icon, then go to the **Providers** tab.
3. Scroll to the bottom and click **Custom provider**.
4. Fill in the custom provider dialog:

   | Field                  | Value                                                                                                                     |
   | ---------------------- | ------------------------------------------------------------------------------------------------------------------------- |
   | **Provider ID**  | `claude-cli`                                                                                                            |
   | **Display name** | `Claude CLI (local)`                                                                                                    |
   | **Provider API** | `OpenAI Compatible`                                                                                                     |
   | **Base URL**     | `http://127.0.0.1:6069/v1` (agent on the same machine) or `http://<your-LAN-IP>:6069/v1` (remote machine)             |
   | **API key**      | `swaraj` (default) — or your `CLAUDE_SERVICE_API_KEY` value                                                          |
   | **Models**       | auto-fetched — click the models field and pick from the list (`sonnet`, `opus`, `haiku`) or add model IDs manually |
5. Click **Submit**. The models now appear in Kilo Code's model picker.
6. Select the model (e.g. `sonnet`) and start chatting. Every request is routed through your local `claude` CLI.

### Any other OpenAI-compatible client

Point the client at the base URL `http://<host>:6069/v1` with the API key above, and use any model ID the CLI accepts (`sonnet`, `opus`, `haiku`, or full names like `claude-opus-5`).

### How the mapping works

- The client sends OpenAI-style `messages` (system + user + assistant history).
- **Images are supported:** `user` messages with content-part arrays may include `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}` (JPEG/PNG/GIF/WebP data URLs). When images are present, the service sends the conversation to the CLI as a stream-json user message containing base64 image blocks — so pasting screenshots into Kilo Code works. Remote (`http:///https://`) image URLs are not fetched; they are skipped.
- The service extracts the `system` message and passes it to the CLI via `--system-prompt` (replacing Claude Code's own agent system prompt).
- The remaining messages are flattened into a conversation transcript and sent to `claude -p` via stdin.
- **Raw-model mode:** `/v1/*` requests run the CLI with all tools disabled (`--tools "" --strict-mcp-config`), so the model answers only from the messages the client sends — it never reads or writes files itself. Tool execution is the client's job.
- **Function-calling bridge:** when the request contains `tools`, their JSON schemas are injected into the system prompt with instructions to call them using `<tool_call name="..."><arg name="...">value</arg></tool_call>` blocks. (Claude's native `<function_calls>`/`<invoke>` syntax is deliberately avoided: written as plain text, the API mistakes it for a real tool call and the CLI replies "The model's tool call could not be parsed".) Previous assistant `tool_calls` are rendered back into that format in the transcript, and `tool` role messages become `<tool_result name="...">` blocks. When the model's reply contains `<tool_call>` blocks, they are parsed back into OpenAI `tool_calls` with `finish_reason: "tool_calls"` — the parser tolerates unclosed blocks, markdown code fences, and the legacy `<function_calls>` syntax. Non-string argument values (numbers, booleans, arrays, objects) are converted from JSON form.
- With tools present, streaming responses are buffered until generation completes (tool calls must be parsed whole), so the first chunk arrives after the model finishes. Without tools, chunks stream live.
- The native `/api/*` endpoints keep the CLI's full agent capabilities (it can read/analyze files in its working directory).
- Joined system messages are truncated to 100,000 characters (`SYSTEM_PROMPT_MAX`) — large system prompts are cut silently.
- Streaming responses are converted from the CLI's `stream-json` events into OpenAI `chat.completion.chunk` SSE events.
- **Prompt caching works** (verified live): the CLI marks cache breakpoints and the flattened prompt is append-only, and the gateway places a breakpoint on the last conversation block (TTL set by `CLAUDE_SERVICE_PROMPT_CACHE_TTL`, default `1h`), so consecutive requests reuse the cached prefix. The `/v1` `usage` block reports `prompt_tokens_details.cached_tokens` plus raw `cache_read_input_tokens` / `cache_creation_input_tokens` so cache hits are visible in real sessions.

### Security

The service binds to `0.0.0.0` (all interfaces), so anything on your network can reach it — and through it, your Claude CLI subscription. Auth is enabled by default with the API key `swaraj`. Use a custom key:

```bash
# Linux / macOS
CLAUDE_SERVICE_API_KEY=my-secret python -m app
```

```powershell
# Windows (PowerShell)
$env:CLAUDE_SERVICE_API_KEY = "my-secret"
python -m app
```

Then enter `my-secret` as the API key in the agent's provider settings. Set `CLAUDE_SERVICE_API_KEY=""` to disable auth entirely (not recommended). To bind to localhost only:

```bash
CLAUDE_SERVICE_HOST=127.0.0.1 python -m app   # Linux / macOS
```

```powershell
$env:CLAUDE_SERVICE_HOST = "127.0.0.1"; python -m app   # Windows (PowerShell)
```

### Limitations

- **Tool calling is supported via the bridge** — agent mode (file edits, terminal commands, etc.) works: the client executes the tools, this service provides the model. Verified: single calls, parallel calls, and result continuation.
- With tools present, streaming is buffered — the full generation arrives as one content chunk (plus tool-call chunks) instead of incremental tokens.
- Each `/v1` request spawns a fresh `claude -p` process with no shared state; the client resends the conversation each turn (standard for OpenAI-compatible APIs). Sessions are only supported on the native `/api/chat` endpoints via `session_id`.

---

## Endpoints

| Method   | Path                     | Auth    | Description                                              |
| -------- | ------------------------ | ------- | -------------------------------------------------------- |
| `GET`  | `/`                    | open    | Web UI                                                   |
| `GET`  | `/health`              | open    | Health check                                             |
| `GET`  | `/docs`                | open    | Interactive OpenAPI docs (Swagger UI)                    |
| `POST` | `/api/chat`            | API key | Native chat — full JSON response                        |
| `POST` | `/api/chat/stream`     | API key | Native chat — SSE stream                                |
| `GET`  | `/v1/models`           | API key | OpenAI-compatible model list                             |
| `POST` | `/v1/chat/completions` | API key | OpenAI-compatible chat completions (stream + non-stream) |

`/`, `/health`, and `/docs` are open. All `/api/*` and `/v1/*` endpoints require the API key via `Authorization: Bearer <key>` or `x-api-key` header.

---

## API Examples

### Web UI — `GET /`

Open [http://127.0.0.1:6069/](http://127.0.0.1:6069/) in a browser. Type a prompt, press **Send** (or Ctrl+Enter) and watch the output stream in. The current session ID is tracked automatically so follow-up messages continue the same conversation. **New chat** resets the session.

### Health — `GET /health`

```bash
curl http://127.0.0.1:6069/health
```

```json
{"status": "ok", "claude_cli": "/path/to/claude", "timeout_s": 600}
```

### Native Chat — `POST /api/chat`

**Request body:**

```json
{
  "prompt": "required — the message to send",
  "model": "optional — e.g. sonnet, opus, haiku",
  "session_id": "optional — resume a previous conversation"
}
```

**Example:**

```bash
curl -X POST http://127.0.0.1:6069/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer swaraj" \
  -d '{"prompt": "Explain recursion in one sentence"}'
```

**Response:**

```json
{
  "response": "Recursion is when a function solves a problem by calling itself on smaller inputs...",
  "session_id": "b2f289c9-...",
  "cost_usd": 0.068,
  "duration_ms": 1787,
  "is_error": false
}
```

### Native Stream — `POST /api/chat/stream`

Same request body as `/api/chat`. Returns `text/event-stream` (SSE) with JSON events:

- `{"text": "..."}` — a chunk of Claude's output
- `{"done": true, ...}` — final event with session ID, cost, and duration
- `{"error": "...", "done": true}` — error (CLI failure, timeout, etc.)

```bash
curl -N -X POST http://127.0.0.1:6069/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer swaraj" \
  -d '{"prompt": "Write a haiku about APIs"}'
```

### Multi-turn conversations (native API)

Pass the `session_id` from a previous response to continue the same conversation (uses `claude --resume`):

```bash
SID=$(curl -s -X POST http://127.0.0.1:6069/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer swaraj" \
  -d '{"prompt": "My name is TestUser"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['session_id'])")

curl -X POST http://127.0.0.1:6069/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer swaraj" \
  -d "{\"prompt\": \"What is my name?\", \"session_id\": \"$SID\"}"
```

### OpenAI-compatible — `GET /v1/models`

```bash
curl -H "Authorization: Bearer swaraj" http://127.0.0.1:6069/v1/models
```

```json
{
  "object": "list",
  "data": [
    {"id": "sonnet", "object": "model", "created": 1760000000, "owned_by": "claude-cli"},
    {"id": "opus",   "object": "model", "created": 1760000000, "owned_by": "claude-cli"},
    {"id": "haiku",  "object": "model", "created": 1760000000, "owned_by": "claude-cli"}
  ]
}
```

Model IDs map directly to the CLI's `--model` flag — any alias or full model name the CLI accepts (e.g. `sonnet`, `claude-opus-5`) can be used.

### OpenAI-compatible — `POST /v1/chat/completions`

Standard OpenAI Chat Completions request. `messages` supports `system`, `user`, `assistant`, and `tool` roles; string content or content-part arrays. `tools` and `tool_choice` are supported via the function-calling bridge. Other extra fields (`temperature`, `max_tokens`, ...) are accepted and ignored.

**Non-streaming:**

```bash
curl -X POST http://127.0.0.1:6069/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer swaraj" \
  -d '{
    "model": "sonnet",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "What is 2+2?"}
    ]
  }'
```

**Response:**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1760000000,
  "model": "sonnet",
  "choices": [
    {"index": 0, "message": {"role": "assistant", "content": "4"}, "finish_reason": "stop"}
  ],
  "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}
}
```

**Streaming** (`"stream": true`) returns OpenAI-style SSE chunks:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"4"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{...}}

data: [DONE]
```

**Function calling** — send `tools`, and the response contains standard OpenAI `tool_calls`:

```json
{
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_...",
        "type": "function",
        "function": {"name": "get_weather", "arguments": "{\"city\": \"Tokyo\"}"}
      }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

After executing the tool, send the result back to continue the loop:

```json
{"role": "tool", "tool_call_id": "call_...", "content": "{\"temperature\": 18, \"condition\": \"light rain\"}"}
```

The model then answers using the result. Parallel calls (multiple invokes in one reply) are supported.

---

## How It Works

> See [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) for a detailed step-by-step description of the request process with worked examples.

```
client ──HTTP──> FastAPI (uvicorn) ──stdin──> claude -p --output-format stream-json --verbose
client <──SSE──── FastAPI (uvicorn) <─JSONL── claude
```

- Request bodies are validated by Pydantic.
- The prompt is piped to the CLI via stdin (no shell, no arg-length limits, no injection risk).
- OpenAI `system` messages become the CLI's `--system-prompt`; the rest of the conversation is flattened into a transcript prompt.
- Streaming responses are parsed from the CLI's `stream-json` events and forwarded as SSE (native or OpenAI chunk format).
- Each request spawns its own CLI process; FastAPI's threadpool handles blocking subprocess I/O, so requests run concurrently.
- Requests are killed after `CLAUDE_SERVICE_TIMEOUT` seconds.
- CORS is enabled for all origins.

---

## Troubleshooting

| Problem                                                   | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `claude: command not found` / `claude` not recognized | The CLI is not on PATH. Reopen your terminal after installing, or reinstall via the commands in[Step 1](#step-1--install--authenticate-the-claude-cli). On Windows the CLI may be at `%USERPROFILE%\.local\bin\claude.exe`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `500` from the service — CLI not found                 | Same as above: the service shells out to`claude`, so it must be on the PATH of the shell that started the service. Restart the service after fixing PATH.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `401` from the service                                  | Send the API key:`Authorization: Bearer <key>` or `x-api-key` header. The key is `CLAUDE_SERVICE_API_KEY` (default `swaraj`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| CLI asks for login / requests fail                        | Run`claude` once in a terminal and complete authentication before starting the service.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| PowerShell blocks venv activation                         | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, or use Command Prompt with `.venv\Scripts\activate.bat`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Port already in use                                       | `CLAUDE_SERVICE_PORT=9000 python -m app` (or the PowerShell/CMD equivalents above).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `python` vs `python3`                                 | On many Linux/macOS systems the command is`python3`. Use whichever exists on your machine.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Agent on another machine can't connect                    | Use the LAN IP (not`127.0.0.1`) in the base URL, ensure port 6069 is open in the firewall, and check the service is running (`curl http://<host>:6069/health`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Tool calls fail / stall in Kilo Code                      | The gateway itself supports single, parallel, and multi-round tool calls (verified by the test suite and live). Check, in order: (1) the API key in the Kilo Code provider matches`CLAUDE_SERVICE_API_KEY` (default `swaraj`); (2) the model ID is one of `sonnet`/`opus`/`haiku`; (3) the service process is running and watch its console — mid-stream CLI failures are emitted as `[service error] ...` text; (4) tool-call streaming is buffered (the whole generation arrives at once), so give long agent turns time — don't cancel early. If tools fail on a machine where `pytest` was never run, missing Python deps (`fastapi`, `pydantic`) cause `ModuleNotFoundError` on startup, not tool failures — reinstall with `pip install -r requirements.txt` inside the venv. |

---

## Development

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt   # runtime deps + pytest, httpx, ruff
pytest                                # run the test suite (no `claude` CLI required)
ruff check .                          # lint
```

Auto-reload during development:

```bash
uvicorn app.main:app --reload --port 6069
```

## Errors

Errors are returned as JSON (`{"error": "..."}`; OpenAI-style `{"error": {"message": ...}}` on `/v1/*`). On the native `/api/chat/stream` endpoint, errors arrive as SSE `error` events. On `/v1/chat/completions` with `"stream": true` the HTTP status is always 200 — mid-stream failures are emitted as a content delta prefixed with `[service error]`, followed by a normal `finish_reason: "stop"` chunk and `data: [DONE]`.

| Status  | Meaning                                                                                |
| ------- | -------------------------------------------------------------------------------------- |
| `400` | Invalid request body (missing/blank prompt, empty messages, bad JSON)                  |
| `401` | API key required/invalid (`CLAUDE_SERVICE_API_KEY` is set)                           |
| `500` | `claude` CLI not found on PATH                                                       |
| `502` | CLI exited with an error, returned invalid JSON, or closed the stream without a result |
| `504` | CLI timed out                                                                          |

## License

This project is provided as-is for personal and internal use. Make sure your use of the Claude Code CLI complies with Anthropic's Terms of Service.
