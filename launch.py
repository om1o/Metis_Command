"""
Metis Command - one-command launcher.

Usage:
    python launch.py                  full auto setup + open desktop window
    python launch.py --tier Lite      tiny models only
    python launch.py --skip-models    skip Ollama pulls
    python launch.py --no-window      headless - just start the services
    python launch.py --reset          nuke venv + stamp and start fresh

On first run: creates venv, installs pinned deps, copies .env, creates
runtime dirs, detects/starts Ollama, pulls the tier's models, then opens
a native window.

On subsequent runs: skips everything already done, launches services,
opens the window in ~3 seconds.

The UI is served by FastAPI (api_bridge) on METIS_API_PORT (default 7331),
including static HTML under ./frontend. There is no separate Streamlit process.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scripts import bootstrap  # noqa: E402  stdlib-only

DEFAULT_API_PORT = int(os.getenv("METIS_API_PORT", "7331"))


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _pick_port(start: int, *, host: str = "127.0.0.1", span: int = 50) -> int:
    """
    Pick the first free port in [start, start+span).

    Avoids failing when the default API port is already in use.
    """
    for p in range(int(start), int(start) + int(span)):
        if _port_free(p, host=host):
            return p
    raise RuntimeError(f"No free port found in range {start}-{start + span - 1}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch Metis Command")
    p.add_argument("--tier", choices=["Lite", "Pro", "Sovereign"],
                   default="Pro")
    p.add_argument("--skip-models", action="store_true",
                   help="don't pull Ollama models")
    p.add_argument("--force-deps", action="store_true",
                   help="re-run pip install even if deps look fresh")
    p.add_argument("--no-window", action="store_true",
                   help="don't open the desktop window (run headless)")
    p.add_argument("--reset", action="store_true",
                   help="delete venv + setup stamp and start over")
    p.add_argument("--inside-venv", action="store_true",
                   help=argparse.SUPPRESS)
    return p.parse_args()


def _reset() -> None:
    for target in (bootstrap.VENV_DIR, bootstrap.STAMP_FILE):
        if target.exists():
            print(f"[reset] removing {target}")
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)


def _run_bootstrap(args: argparse.Namespace) -> None:
    bootstrap.run(
        tier=args.tier,
        skip_models=args.skip_models,
        force_deps=args.force_deps,
    )


def _reexec_in_venv(args: argparse.Namespace) -> None:
    """Re-launch under the venv python so uvicorn and deps resolve correctly."""
    py = bootstrap.venv_python()
    if not py.exists():
        raise RuntimeError("venv python missing after bootstrap.")
    if Path(sys.executable).resolve() == py.resolve():
        return
    argv = [str(py), str(Path(__file__).resolve()), "--inside-venv"]
    for flag in ("tier", "skip_models", "force_deps", "no_window"):
        value = getattr(args, flag, None)
        if value is True:
            argv.append("--" + flag.replace("_", "-"))
        elif isinstance(value, str) and flag == "tier":
            argv.extend(["--tier", value])
    print(f"[launch] re-executing under venv python -> {py}")
    os.execv(str(py), argv)


def _start_api() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_bridge:app",
         "--host", "127.0.0.1", "--port", str(int(os.environ["METIS_API_PORT"])), "--log-level", "warning"],
        cwd=str(ROOT),
    )


def _terminate(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    deadline = time.time() + 5
    for p in procs:
        try:
            remaining = max(0.2, deadline - time.time())
            p.wait(timeout=remaining)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def _ping(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            return 200 <= r.status < 400
    except Exception:
        return False


def _wait_for_api(url: str, *, retries: int = 60, delay: float = 1.0) -> bool:
    # Use /health to avoid heavier endpoints.
    target = url.rstrip("/") + "/health"
    for _ in range(retries):
        if _ping(target):
            return True
        time.sleep(delay)
    return False


def _early_exit(proc: subprocess.Popen) -> tuple[bool, int]:
    code = proc.poll()
    if code is None:
        return False, 0
    try:
        return True, int(code)
    except Exception:
        return True, 1


def _run_services(args: argparse.Namespace) -> int:
    from scripts import desktop_shell

    api_port = int(os.environ.get("METIS_API_PORT", str(DEFAULT_API_PORT)))
    if not _port_free(api_port):
        picked = _pick_port(api_port)
        print(f"[launch] API port {api_port} in use; switching to {picked}", flush=True)
        api_port = picked
        os.environ["METIS_API_PORT"] = str(api_port)

    api_url = f"http://127.0.0.1:{api_port}"
    # Splash is the HTML entry the desktop shell waits on; `/` may return JSON for API clients.
    splash_url = f"{api_url}/splash"

    print(f"[launch] starting API + UI -> {api_url}", flush=True)
    api = _start_api()

    procs: list[subprocess.Popen] = [api]

    def _handler(signum, _frame):
        print(f"\n[launch] signal {signum} - shutting down.")
        _terminate(procs)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)

    time.sleep(0.8)
    api_exited, api_code = _early_exit(api)
    if api_exited:
        print(f"[launch] API exited early (code={api_code}).", file=sys.stderr, flush=True)
        _terminate(procs)
        return 3

    if not _wait_for_api(api_url):
        print(f"[launch] API never came up at {api_url}", file=sys.stderr, flush=True)
        _terminate(procs)
        return 1

    if not desktop_shell.wait_for_ui(splash_url):
        print(f"[launch] Splash never became reachable at {splash_url}", file=sys.stderr, flush=True)
        _terminate(procs)
        return 1

    # Non-blocking update probe - result is cached for the UI to read.
    try:
        import threading
        from scripts import updater
        threading.Thread(
            target=updater.cached_check, kwargs={"max_age_s": 3600},
            daemon=True, name="MetisUpdateCheck",
        ).start()
    except Exception as e:
        print(f"[launch] update probe skipped: {e}")

    if args.no_window:
        print(f"[launch] headless mode - open {splash_url} (api_pid={api.pid})", flush=True)
        try:
            while True:
                time.sleep(5)
                if api.poll() is not None:
                    print("[launch] API died - restarting.", flush=True)
                    api = _start_api()
                    procs[0] = api
        except KeyboardInterrupt:
            pass
        finally:
            _terminate(procs)
        return 0

    try:
        desktop_shell.open_window(splash_url)
    finally:
        _terminate(procs)
    return 0


def main() -> int:
    args = _parse_args()

    if args.reset:
        _reset()

    if not args.inside_venv:
        _run_bootstrap(args)
        _reexec_in_venv(args)
        # If we didn't os.execv (because we're already running inside the venv),
        # continue normally.
        args.inside_venv = True

    return _run_services(args)


if __name__ == "__main__":
    sys.exit(main())
