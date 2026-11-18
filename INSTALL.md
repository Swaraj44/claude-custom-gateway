# Installing Claude Custom Gateway

- [Windows (Task Scheduler)](#windows-task-scheduler)
- [Ubuntu (.deb)](#installing-claude-custom-gateway-on-ubuntu-deb)

Running from source instead? See the [README](README.md).

## Windows (Task Scheduler)

Prerequisites: **Python 3.9+** and the **Claude Code CLI** installed and logged in as your user (run `claude` once).

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1              # start at logon
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1 -AtStartup   # start at boot (run as admin)
```

The installer creates a virtualenv in `%LOCALAPPDATA%\claude-custom-gateway` and installs the gateway there.
It registers the `ClaudeCustomGateway` scheduled task, which runs as your user, has no console window, and restarts on failure.
It then starts the task and checks `/health`.

- Config: `%LOCALAPPDATA%\claude-custom-gateway\config.env`. The first install generates a random API key and binds to
  `127.0.0.1`. Set `CLAUDE_SERVICE_HOST=0.0.0.0` and open the port in Windows Firewall for network access.
- Logs: `%LOCALAPPDATA%\claude-custom-gateway\logs\gateway.log`
- Restart after config changes: `Stop-ScheduledTask ClaudeCustomGateway; Start-ScheduledTask ClaudeCustomGateway`
- Upgrade: re-run `install.ps1`. Your `config.env` is kept.
- Uninstall: `powershell -ExecutionPolicy Bypass -File packaging\windows\uninstall.ps1` (add `-KeepConfig` to keep the config)

Installer options:

- `-AtStartup`: start at boot instead of logon. Needs an elevated PowerShell and prompts for your Windows password.
- `-NoStart`: register the task without starting it.
- `-Python <path>`, `-InstallDir <dir>`, `-TaskName <name>`: override the detected Python, install location, or task name.

Run the installer from a checkout of this repo: it pip-installs the gateway from the repo root.

Windows troubleshooting:

- **Gateway does not answer on the port**: read `%LOCALAPPDATA%\claude-custom-gateway\logs\gateway.log`.
- **"claude CLI not found"**: set `CLAUDE_SERVICE_CLAUDE_BIN=C:\Users\<user>\.local\bin\claude.exe` in `config.env` and restart the task.
- **Not authenticated**: run `claude` as the same Windows user the task runs as, then restart the task.
- **Port in use**: change `CLAUDE_SERVICE_PORT` in `config.env` and restart the task.

Connect a client: use `http://127.0.0.1:6069/v1` with the API key from `config.env` (see [Connect Third-Party Coding Agents](README.md#connect-third-party-coding-agents)).

## Installing Claude Custom Gateway on Ubuntu (.deb)

Tested layout: Ubuntu 24.04 (Python 3.12), amd64.

### Prerequisites

- Ubuntu/Debian with systemd and **Python 3.12+** (`python3 --version`).
- The **Claude Code CLI** installed and **logged in** as the user that will run the service
  (run `claude` once in a terminal and complete login). The service uses that user's `~/.claude`.

### 1. Build the package (once, on a machine with internet)

```bash
git clone <repo> && cd claude-custom-gateway
python3 -m venv .venv && . .venv/bin/activate   # any Python with pip works
./packaging/build-deb.sh
# -> dist/claude-custom-gateway_<version>_amd64.deb
```

The package bundles the app and all dependency wheels, so installing it does not need internet
(if the target's Python differs from the build machine's, it falls back to PyPI).
Build on the same Ubuntu release you deploy to.

### 2. Install

```bash
sudo apt install ./dist/claude-custom-gateway_1.5.0_amd64.deb
```

Running from source instead? See the [README](README.md).

`apt` pulls in `python3-venv` and `python3-pip` automatically. The install creates a virtualenv in
`/opt/claude-custom-gateway/venv`.

### 3. Configure

```bash
sudo nano /etc/default/claude-custom-gateway
```

At minimum, **change `CLAUDE_SERVICE_API_KEY`**. Set `CLAUDE_SERVICE_HOST=127.0.0.1` to accept
local connections only. The full list of `CLAUDE_SERVICE_*` settings and their defaults is in the
[README configuration table](README.md#configuration-environment-variables); the config file uses plain
`KEY=value` lines (no `export`). Edits survive package upgrades.

### 4. Start the service

The service runs as a user you choose (that user must be logged in to `claude`):

```bash
sudo systemctl enable --now claude-custom-gateway@$USER
```

Check it:

```bash
systemctl status claude-custom-gateway@$USER
journalctl -u claude-custom-gateway@$USER -f
curl http://127.0.0.1:6069/health
```

Web UI: [http://127.0.0.1:6069/](http://127.0.0.1:6069/) - OpenAI-compatible base URL: `http://127.0.0.1:6069/v1`.

After changing the config: `sudo systemctl restart claude-custom-gateway@$USER`.

### Commands installed

| Command                   | What it does                                   |
| ------------------------- | ---------------------------------------------- |
| `claude-custom-gateway` | Run the gateway in the foreground              |
| `claude-pro`            | Same, with payload logging off                 |
| `claude-debug`          | Same, with request/response payload logging on |

### Troubleshooting

- **Requests fail with "claude CLI not found"**: the service looks in `PATH`
  (`~/.local/bin`, `/usr/local/bin`, `/usr/bin`), then `~/.claude/local`, `~/.npm-global/bin` and the
  Claude Code VS Code extension's bundled binary. If yours is elsewhere, set
  `CLAUDE_SERVICE_CLAUDE_BIN=/path/to/claude` in `/etc/default/claude-custom-gateway` and restart.
  `curl localhost:6069/health` shows which binary the service is using.
- **`claude` disappeared after an auto-update** (npm installs; `npm install -g` then fails with
  `ENOTEMPTY ... .claude-code-XXXX`): an interrupted update left stale files. Run
  `rm -rf ~/.npm-global/lib/node_modules/@anthropic-ai/.claude-code-* ~/.npm-global/bin/.claude-*`,
  then `npm install -g @anthropic-ai/claude-code`, and restart the service.
- **Not authenticated**: run `claude` as the service user and log in, then restart the service.
- **Port in use**: change `CLAUDE_SERVICE_PORT` in `/etc/default/claude-custom-gateway`.

### Connect a client

Point any OpenAI-compatible client (e.g. Kilo Code) at `http://127.0.0.1:6069/v1` with your `CLAUDE_SERVICE_API_KEY`.
See [Connect Third-Party Coding Agents](README.md#connect-third-party-coding-agents).

### Upgrade

Rebuild with a bumped `version` in `pyproject.toml`, then `sudo apt install ./dist/<new>.deb`.
The service keeps its enabled state; restart it with `systemctl restart`.

### Uninstall

```bash
sudo systemctl disable --now claude-custom-gateway@$USER
sudo apt remove claude-custom-gateway      # keeps /etc/default config
sudo apt purge claude-custom-gateway       # also removes the config
```
