# Packaging: How It Works

The `packaging/` folder turns the Python project into a Debian package (`.deb`). Once installed, the gateway runs as a systemd service under a chosen user account.

```
packaging/
├── build-deb.sh                      # Builds the .deb
├── claude-custom-gateway@.service    # systemd template unit
└── debian/
    ├── default                       # Config file -> /etc/default/claude-custom-gateway
    ├── postinst                      # Runs after install/upgrade
    ├── prerm                         # Runs before removal
    └── postrm                        # Runs after removal
```

---

## Part 1: Building the package (`build-deb.sh`)

Run it from anywhere:

```bash
./packaging/build-deb.sh
```

**Requirements:** `dpkg-deb`, `python3` with `pip`, and network access, because pip downloads the dependency wheels.

### Step 1: Gather build metadata

| Variable  | Source                                   | Example                 |
|-----------|------------------------------------------|-------------------------|
| `ROOT`    | Parent directory of `packaging/`         | project root            |
| `VERSION` | `version = "..."` in `pyproject.toml`    | `0.3.1`                 |
| `ARCH`    | `dpkg --print-architecture`              | `amd64`                 |
| `PYMM`    | Major.minor version of the build Python  | `3.12`                  |
| `STAGE`   | A temporary directory                    | `/tmp/tmp.XXXX`         |

A `trap` deletes the temporary staging directory when the script exits, including when it fails (`set -euo pipefail`).

### Step 2: Create the package filesystem layout

Inside `$STAGE/pkg`, the script creates the directories that will be laid onto `/` at install time:

```
pkg/
├── DEBIAN/                         # Package metadata and maintainer scripts
├── opt/claude-custom-gateway/wheels/
├── usr/bin/
├── lib/systemd/system/
└── etc/default/
```

It also creates `$ROOT/dist/` to hold the output.

### Step 3: Bundle the wheels

```bash
python3 -m pip wheel "$ROOT" -w "$PKG/opt/claude-custom-gateway/wheels"
```

This builds a wheel for the app itself and downloads or builds a wheel for every dependency. The wheels are resolved for the **build machine's Python version and architecture**. This lets the target machine install the app offline.

### Step 4: Generate command wrappers

For each of `claude-custom-gateway`, `claude-pro`, and `claude-debug`, the script writes a small shell script into `/usr/bin/`:

```sh
#!/bin/sh
exec /opt/claude-custom-gateway/venv/bin/<cmd> "$@"
```

The virtual environment does not exist yet. The `postinst` script creates it during installation, as described in Part 2. The wrappers only forward the command to it.

### Step 5: Copy in the service, config, and maintainer scripts

| Source                              | Destination in package                              | Mode |
|-------------------------------------|-----------------------------------------------------|------|
| `claude-custom-gateway@.service`    | `/lib/systemd/system/claude-custom-gateway@.service`| 644  |
| `debian/default`                    | `/etc/default/claude-custom-gateway`                | 644  |
| `debian/postinst`, `prerm`, `postrm`| `DEBIAN/`                                           | 755  |

`DEBIAN/conffiles` lists `/etc/default/claude-custom-gateway`. As a result, dpkg treats it as a user-editable config file. Your edits survive upgrades, and dpkg prompts you if the packaged version changes.

### Step 6: Write `DEBIAN/control`

1. All directories are set to mode `755`.
2. `Installed-Size` is calculated with `du -sk`.
3. The control file declares the package name, version, architecture, maintainer, and description.
4. The control file declares these dependencies:
   ```
   Depends: python3 (>= PYMM), python3-venv, python3-pip
   ```

### Step 7: Build the `.deb`

```bash
dpkg-deb --root-owner-group --build "$PKG" dist/claude-custom-gateway_<version>_<arch>.deb
```

`--root-owner-group` makes every file owned by `root:root`, regardless of which user ran the build.

---

## Part 2: Installing (`sudo apt install ./dist/claude-custom-gateway_*.deb`)

### Step 1: dpkg unpacks the files

- `/opt/claude-custom-gateway/wheels/*.whl`
- `/usr/bin/claude-custom-gateway`, `claude-pro`, `claude-debug` (the wrappers)
- `/lib/systemd/system/claude-custom-gateway@.service`
- `/etc/default/claude-custom-gateway`

### Step 2: `postinst configure` runs

1. The script deletes any old virtual environment at `/opt/claude-custom-gateway/venv`.
2. The script creates a fresh one with `python3 -m venv`.
3. The script tries an **offline** install from the bundled wheels first:
   ```
   pip install --no-index --find-links /opt/claude-custom-gateway/wheels claude-custom-gateway
   ```
4. If the offline install fails, the script falls back to PyPI and still prefers the local wheels. A common cause is that the target machine has a different Python version than the build machine, so compiled wheels don't match.
5. The script prints instructions for the next steps.

The service is **not** started automatically.

---

## Part 3: Configuring and running

### Step 1: Edit the config

```bash
sudo nano /etc/default/claude-custom-gateway
```

| Key                               | Default    | Purpose                                     |
|-----------------------------------|------------|---------------------------------------------|
| `CLAUDE_SERVICE_HOST`             | `0.0.0.0`  | Bind address (`127.0.0.1` = local only)     |
| `CLAUDE_SERVICE_PORT`             | `6069`     | Listen port                                 |
| `CLAUDE_SERVICE_TIMEOUT`          | `600`      | Request timeout (seconds)                   |
| `CLAUDE_SERVICE_API_KEY`          | `change-me`| **Change this before exposing to a network**|
| `CLAUDE_SERVICE_VISION_MODEL`     | `sonnet`   | Model used for vision requests              |
| `CLAUDE_SERVICE_PROMPT_CACHE_TTL` | `1h`       | Prompt cache TTL                            |
| `CLAUDE_SERVICE_EFFORT`           | (unset)    | Optional effort level                       |
| `CLAUDE_SERVICE_LOG_PAYLOADS`     | (unset)    | Optional payload logging                    |

Use plain `KEY=value` lines. Do not add `export`.

### Step 2: Enable the service for a user

```bash
sudo systemctl enable --now claude-custom-gateway@<username>
```

### How the template unit works (`claude-custom-gateway@.service`)

The `@` makes it a **template**. When you enable it, whatever follows `@` becomes `%i`, the instance name, which here is a username.

| Directive                                  | Effect                                                                 |
|--------------------------------------------|------------------------------------------------------------------------|
| `After=` / `Wants=network-online.target`   | Starts after the network is up                                         |
| `User=%i`                                  | Runs as that user. systemd sets `HOME`, so `claude` finds `~/.claude`  |
| `Environment=PATH=/home/%i/.local/bin:...` | Lets the service find a `claude` CLI installed in the user's home      |
| `EnvironmentFile=-/etc/default/...`        | Loads the config. The leading `-` means a missing file is not an error |
| `ExecStart=/usr/bin/claude-custom-gateway` | Wrapper, then the venv entry point                                     |
| `Restart=on-failure`, `RestartSec=3`       | Restarts automatically after a crash                                   |
| `WantedBy=multi-user.target`               | Starts at boot when enabled                                            |

**Prerequisite:** the `claude` CLI must be installed and logged in **as that user**.

Call chain at runtime:

```
systemd -> /usr/bin/claude-custom-gateway -> /opt/claude-custom-gateway/venv/bin/claude-custom-gateway -> Python app -> claude CLI
```

After editing the config, restart the service:

```bash
sudo systemctl restart claude-custom-gateway@<username>
```

---

## Part 4: Upgrading

When you install a newer `.deb`:

1. dpkg replaces the wheels, wrappers, and unit file.
2. `/etc/default/claude-custom-gateway` is kept, because it is a conffile.
3. `postinst configure` rebuilds the venv from the new wheels.
4. A running service keeps using the old code until you restart it.

---

## Part 5: Removing (`sudo apt remove` / `purge`)

### Step 1: `prerm remove|purge`

The script lists all running `claude-custom-gateway@*.service` units and stops each one. A failure to stop does not stop the removal.

### Step 2: dpkg deletes the packaged files

The wheels, wrappers, and unit file are deleted.

### Step 3: `postrm remove|purge`

The script deletes `/opt/claude-custom-gateway/venv`. The package does not own the venv, so dpkg would not remove it on its own.

- `apt remove` keeps `/etc/default/claude-custom-gateway`.
- `apt purge` also deletes the config file.

---

## Lifecycle summary

```
build-deb.sh ──► dist/*.deb
                     │
        apt install  ▼
   unpack files ─► postinst: create venv, pip install from wheels
                     │
   edit /etc/default/claude-custom-gateway
   systemctl enable --now claude-custom-gateway@USER
                     │
        apt remove   ▼
   prerm: stop units ─► delete files ─► postrm: delete venv
```