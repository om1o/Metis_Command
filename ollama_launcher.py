"""
Ollama auto-launcher — make the AI brain "just work" for end users.

Customers don't want to run `ollama serve` in another terminal. This module
detects whether Ollama is reachable; if not, it locates the binary in the
standard install paths, spawns `ollama serve` as a detached subprocess, and
waits for the server to come online.

Public API:
    is_running(timeout=2.0)    -> bool
    locate_binary()            -> Optional[Path]
    start_if_needed(wait=True) -> dict  {ok, started, already_running, binary, port, message}
    ensure_ready(max_wait_s=20) -> bool

Designed to be safe to call from FastAPI startup. Any failure degrades to
returning False/error info — never raises so the API server still boots.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Default Ollama listen address. Mirrors brain_engine.OLLAMA_BASE.
_DEFAULT_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")


def _http_url() -> str:
    return _DEFAULT_BASE.rstrip("/")


def is_running(timeout: float = 2.0) -> bool:
    """Quick probe: is Ollama answering on its HTTP port?"""
    try:
        # Local import so importing this module doesn't pull in requests.
        import requests
        r = requests.get(f"{_http_url()}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _candidate_paths() -> list[Path]:
    """Standard install locations to probe, in order of likelihood."""
    home = Path.home()
    out: list[Path] = []
    if sys.platform.startswith("win"):
        out.extend([
            home / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
            Path("C:/Program Files (x86)/Ollama/ollama.exe"),
        ])
    elif sys.platform == "darwin":
        out.extend([
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            Path("/usr/local/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
            home / ".local" / "bin" / "ollama",
        ])
    else:
        out.extend([
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
            home / ".local" / "bin" / "ollama",
            Path("/snap/bin/ollama"),
        ])
    return out


def locate_binary() -> Optional[Path]:
    """Return the path to the ollama executable or None if missing."""
    on_path = shutil.which("ollama") or shutil.which("ollama.exe")
    if on_path:
        return Path(on_path)
    for p in _candidate_paths():
        if p.exists():
            return p
    return None


def _spawn_serve(binary: Path) -> bool:
    """Spawn `<binary> serve` detached so it survives parent exits."""
    try:
        if sys.platform.startswith("win"):
            # CREATE_NEW_PROCESS_GROUP = 0x00000200 — detached but keeps a session.
            # DETACHED_PROCESS = 0x00000008 — fully decoupled from parent console.
            flags = 0x00000008 | 0x00000200
            subprocess.Popen(
                [str(binary), "serve"],
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                [str(binary), "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        return True
    except Exception as e:
        print(f"[ollama_launcher] spawn failed: {e}")
        return False


def ensure_ready(max_wait_s: float = 20.0, poll_interval_s: float = 0.5) -> bool:
    """Block until Ollama answers /api/tags or `max_wait_s` elapses."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        if is_running(timeout=1.0):
            return True
        time.sleep(poll_interval_s)
    return is_running(timeout=2.0)


def start_if_needed(wait: bool = True, max_wait_s: float = 20.0) -> dict:
    """
    Make sure Ollama is running. Returns a status dict with details suitable
    for the splash screen / a JSON endpoint.
    """
    out: dict = {
        "ok": False,
        "started": False,
        "already_running": False,
        "binary": None,
        "port": _http_url(),
        "message": "",
    }
    if is_running(timeout=1.5):
        out.update(ok=True, already_running=True, message="Ollama already running.")
        return out

    binary = locate_binary()
    out["binary"] = str(binary) if binary else None
    if not binary:
        out["message"] = (
            "Ollama not installed. Visit https://ollama.com/download to install — "
            "the rest of the app still works with cloud models."
        )
        return out

    spawned = _spawn_serve(binary)
    if not spawned:
        out["message"] = "Found Ollama binary but could not start it."
        return out

    out["started"] = True
    if not wait:
        out.update(ok=True, message="Spawned ollama serve (not waiting).")
        return out

    if ensure_ready(max_wait_s=max_wait_s):
        out.update(ok=True, message=f"Ollama is up at {_http_url()}.")
    else:
        out["message"] = f"Spawned ollama serve but it didn't respond within {max_wait_s:.0f}s."
    return out
