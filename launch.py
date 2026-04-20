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
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scripts import bootstrap  # noqa: E402  stdlib-only

UI_PORT = os.getenv("METIS_UI_PORT", "8501")
API_PORT = os.getenv("METIS_API_PORT", "7331")
UI_URL = f"http://127.0.0.1:{UI_PORT}"
API_URL = f"http://127.0.0.1:{API_PORT}"


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
    """Re-launch under the venv python so we can import streamlit etc."""
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
         "--host", "127.0.0.1", "--port", API_PORT, "--log-level", "warning"],
        cwd=str(ROOT),
    )


def _start_ui() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "dynamic_ui.py"),
         "--server.port", UI_PORT,
         "--server.headless", "true",
         "--server.address", "127.0.0.1",
         "--browser.gatherUsageStats", "false"],
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


def _run_services(args: argparse.Namespace) -> int:
    from scripts import desktop_shell

    print(f"[launch] starting API  -> {API_URL}")
    api = _start_api()
    print(f"[launch] starting UI   -> {UI_URL}")
    ui = _start_ui()

    procs: list[subprocess.Popen] = [api, ui]

    def _handler(signum, _frame):
        print(f"\n[launch] signal {signum} - shutting down.")
        _terminate(procs)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)

    if not desktop_shell.wait_for_ui(UI_URL):
        print(f"[launch] UI never came up at {UI_URL}", file=sys.stderr)
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
        print(f"[launch] headless mode - UI at {UI_URL}")
        try:
            while True:
                time.sleep(5)
                if ui.poll() is not None:
                    print("[launch] UI died - restarting.")
                    ui = _start_ui()
                    procs[1] = ui
                if api.poll() is not None:
                    print("[launch] API died - restarting.")
                    api = _start_api()
                    procs[0] = api
        except KeyboardInterrupt:
            pass
        finally:
            _terminate(procs)
        return 0

    try:
        desktop_shell.open_window(UI_URL)
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
        return 0  # os.execv replaces the process; this is just a safety net

    return _run_services(args)


if __name__ == "__main__":
    sys.exit(main())
