"""
Windowless Metis launcher.

Starts:
    1. Streamlit UI       (dynamic_ui.py on METIS_UI_PORT, default 8501)
    2. FastAPI bridge     (api_bridge.py on METIS_API_PORT, default 7331)
    3. System-tray daemon (metis_daemon.py)

Graceful Ctrl+C / tray-quit stops all three.  Health-checks restart the
UI subprocess if it dies.  Use `.pyw` so double-clicking opens nothing.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


ROOT = Path(__file__).parent
UI_PORT = os.getenv("METIS_UI_PORT", "8501")
API_PORT = os.getenv("METIS_API_PORT", "7331")
HEALTH_INTERVAL = 5.0


def _spawn_ui() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(ROOT / "dynamic_ui.py"),
            "--server.port", UI_PORT,
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
            "--server.address", "127.0.0.1",
        ],
        cwd=str(ROOT),
    )


def _spawn_api() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "api_bridge:app",
            "--host", "127.0.0.1",
            "--port", API_PORT,
            "--log-level", "warning",
        ],
        cwd=str(ROOT),
    )


def _spawn_daemon() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(ROOT / "metis_daemon.py")],
        cwd=str(ROOT),
    )


def main() -> None:
    ui = _spawn_ui()
    api = _spawn_api()
    daemon = _spawn_daemon()

    print(f"[Metis] UI     http://localhost:{UI_PORT}")
    print(f"[Metis] API    http://localhost:{API_PORT}")
    print(f"[Metis] Daemon pid={daemon.pid}")

    try:
        while True:
            time.sleep(HEALTH_INTERVAL)
            if ui.poll() is not None:
                print("[Metis] UI died, restarting…")
                ui = _spawn_ui()
            if api.poll() is not None:
                print("[Metis] API died, restarting…")
                api = _spawn_api()
            if daemon.poll() is not None:
                print("[Metis] Daemon exited — shutting down.")
                break

            # Restart flag from metis_daemon.py
            flag = ROOT / "logs" / "restart.flag"
            if flag.exists():
                flag.unlink(missing_ok=True)
                print("[Metis] restart flag set — restarting UI…")
                try:
                    ui.terminate()
                except Exception:
                    pass
                ui = _spawn_ui()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (daemon, api, ui):
            try:
                proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
