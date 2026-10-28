# Installing Claude Custom Gateway on Ubuntu (.deb)

Tested layout: Ubuntu 24.04 (Python 3.12), amd64.

## Prerequisites

- Ubuntu/Debian with systemd and **Python 3.12+** (`python3 --version`).
- The **Claude Code CLI** installed and **logged in** as the user that will run the service
  (run `claude` once in a terminal and complete login). The service uses that user's `~/.claude`.

## 1. Build the package (once, on a machine with internet)

```bash
git clone <repo> && cd claude-custom-gateway
python3 -m venv .venv && . .venv/bin/activate   # any Python with pip works
./packaging/build-deb.sh
# -> dist/claude-custom-gateway_<version>_amd64.deb
```

The package bundles the app and all dependency wheels, so installing it does not need internet
(if the target's Python differs from the build machine's, it falls back to PyPI).
Build on the same Ubuntu release you deploy to.

## 2. Install

```bash
sudo apt install ./dist/claude-custom-gateway_1.3.0_amd64.deb
```

`apt` pulls in `python3-venv` and `python3-pip` automatically. The install creates a virtualenv in
`/opt/claude-custom-gateway/venv`.

## 3. Configure

```bash
sudo nano /etc/default/claude-custom-gateway
```

At minimum, **change `CLAUDE_SERVICE_API_KEY`**. Set `CLAUDE_SERVICE_HOST=127.0.0.1` to accept
local connections only. Settings are listed in `.env.example`. Edits survive package upgrades.

## 4. Start the service

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

## Commands installed

| Command                   | What it does                                   |
| ------------------------- | ---------------------------------------------- |
| `claude-custom-gateway` | Run the gateway in the foreground              |
| `claude-pro`            | Same, with payload logging off                 |
| `claude-debug`          | Same, with request/response payload logging on |

## Troubleshooting

- **Requests fail with "claude not found"**: the CLI must be in `~/.local/bin`, `/usr/local/bin` or
  `/usr/bin`. Otherwise add its directory to `PATH` via a unit override:
  `sudo systemctl edit claude-custom-gateway@$USER`.
- **Not authenticated**: run `claude` as the service user and log in, then restart the service.
- **Port in use**: change `CLAUDE_SERVICE_PORT` in `/etc/default/claude-custom-gateway`.

## Upgrade

Rebuild with a bumped `version` in `pyproject.toml`, then `sudo apt install ./dist/<new>.deb`.
The service keeps its enabled state; restart it with `systemctl restart`.

## Uninstall

```bash
sudo systemctl disable --now claude-custom-gateway@$USER
sudo apt remove claude-custom-gateway      # keeps /etc/default config
sudo apt purge claude-custom-gateway       # also removes the config
```
