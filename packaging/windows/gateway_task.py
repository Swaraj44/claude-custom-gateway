"""Task Scheduler entry point: load config.env, log to logs\\gateway.log, run the gateway, restart on failure."""

import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_MAX_BYTES = 10 * 1024 * 1024
RESTART_DELAY_S = 5


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ[key] = value


def open_log():
    log_dir = HERE / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "gateway.log"
    if log_path.exists() and log_path.stat().st_size > LOG_MAX_BYTES:
        log_path.replace(log_dir / "gateway.log.1")
    return open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)


def stamp(message: str) -> None:
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message), flush=True)


def main() -> None:
    log = open_log()
    sys.stdout = sys.stderr = log
    load_env(HERE / "config.env")
    from app.main import main as run_gateway

    while True:
        stamp("starting gateway")
        try:
            run_gateway()
            stamp("gateway stopped")
            return
        except KeyboardInterrupt:
            return
        except BaseException:
            traceback.print_exc()
        stamp("gateway exited unexpectedly; restarting in %ds" % RESTART_DELAY_S)
        time.sleep(RESTART_DELAY_S)


if __name__ == "__main__":
    main()
