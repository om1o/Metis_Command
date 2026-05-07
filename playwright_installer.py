"""
Playwright Chromium auto-installer — make the browser engine "just work".

Customers should never have to run `python -m playwright install chromium`
from a terminal. On first launch, Metis detects whether the Chromium
binary Playwright drives is present; if not, it kicks off the install
in a background thread and surfaces progress through /playwright/status
so the splash screen can show "Installing browser engine — first launch
only (about 150 MB)".

Public API:
    is_chromium_installed() -> bool
    install_status() -> dict   {state, started_at, ended_at, ok, message}
    ensure_chromium_async() -> dict   start install if needed, return status

State machine (status["state"]):
    "absent"      package present but no Chromium binary yet
    "installing"  install subprocess running
    "ready"       binary present, ready to drive
    "failed"      install attempted and failed (will retry on next launch)
    "unavailable" the playwright Python package itself isn't importable

The install is idempotent: subsequent calls when the binary is already
installed are a no-op. We never raise — every error degrades to a
status report so the FastAPI server keeps booting.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import playwright  # noqa: F401
    _PW_PACKAGE_OK = True
except Exception:
    _PW_PACKAGE_OK = False


# Module-level status shared across threads. The lock guards writes; reads
# are atomic enough on CPython that we don't need to lock them.
_status: dict[str, Any] = {
    "state": "absent",
    "started_at": None,      # epoch seconds when install kicked off
    "ended_at": None,        # epoch seconds when install finished
    "ok": None,              # bool once install completes
    "message": "",           # last log line / error
    "checked_at": 0.0,
}
_lock = threading.Lock()


# ── Detection ───────────────────────────────────────────────────────────────

def _chromium_cache_dirs() -> list[Path]:
    """
    Standard locations Playwright caches the Chromium download.
    These are the same paths `playwright install` writes to.
    """
    home = Path.home()
    out: list[Path] = []
    # Honour PLAYWRIGHT_BROWSERS_PATH if set.
    explicit = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if explicit:
        out.append(Path(explicit))
    # Per-OS defaults
    if sys.platform == "win32":
        out.append(home / "AppData" / "Local" / "ms-playwright")
    elif sys.platform == "darwin":
        out.append(home / "Library" / "Caches" / "ms-playwright")
    else:
        out.append(home / ".cache" / "ms-playwright")
    return out


def is_chromium_installed() -> bool:
    """
    Return True iff there's a Chromium build Playwright can launch.

    We look for a `chromium-*` folder containing a chrome / Chromium /
    chrome.exe binary. Avoids importing the heavy playwright._impl._driver
    machinery to keep this fast.
    """
    if not _PW_PACKAGE_OK:
        return False
    for root in _chromium_cache_dirs():
        if not root.exists():
            continue
        for child in root.iterdir():
            name = child.name.lower()
            if not name.startswith("chromium"):
                continue
            # Probe each per-OS executable path. Modern Playwright uses
            # chrome-win64 on Windows x64 and chrome-mac-arm64 on Apple
            # Silicon — accept either flavour.
            candidates = [
                child / "chrome-win64" / "chrome.exe",
                child / "chrome-win" / "chrome.exe",
                child / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
                child / "chrome-mac-arm64" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
                child / "chrome-linux" / "chrome",
            ]
            if any(c.exists() for c in candidates):
                return True
    return False


# ── Install ─────────────────────────────────────────────────────────────────

def _set_status(**kwargs: Any) -> None:
    with _lock:
        _status.update(kwargs)
        _status["checked_at"] = time.time()


def _run_install_blocking() -> None:
    """
    Run `python -m playwright install chromium` in a subprocess. Captures
    stdout/stderr line-by-line into the status dict so the splash screen
    has a live message to display.
    """
    if not _PW_PACKAGE_OK:
        _set_status(state="unavailable", ok=False,
                    message="playwright package not installed in this venv",
                    started_at=None, ended_at=None)
        return

    _set_status(state="installing", ok=None,
                started_at=time.time(), ended_at=None,
                message="Downloading Chromium (~150 MB) — first launch only…")

    try:
        # `--with-deps` would also try to apt-get system libs on Linux, which
        # requires sudo. We deliberately skip that — most desktops already
        # have the libs, and the customer doesn't have a sudo password to give.
        proc = subprocess.Popen(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            # Detach the child from any console so closing the launcher
            # doesn't kill the install mid-download on Windows.
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0),
        )
    except Exception as e:
        _set_status(state="failed", ok=False, ended_at=time.time(),
                    message=f"could not spawn installer: {e}")
        return

    last_line = ""
    if proc.stdout is not None:
        for line in proc.stdout:
            line = (line or "").strip()
            if not line:
                continue
            last_line = line[:240]
            _set_status(message=last_line)
    rc = proc.wait()

    if rc == 0 and is_chromium_installed():
        _set_status(state="ready", ok=True, ended_at=time.time(),
                    message="Browser engine installed.")
    else:
        _set_status(state="failed", ok=False, ended_at=time.time(),
                    message=last_line or f"installer exited with code {rc}")


def install_status() -> dict:
    """Read-only view of the current install state."""
    with _lock:
        snap = dict(_status)
    # Self-correct: if we think we're "absent" but the binary is now there,
    # promote to "ready" so the splash unblocks immediately.
    if snap.get("state") in ("absent", None) and is_chromium_installed():
        _set_status(state="ready", ok=True,
                    message="Browser engine ready.")
        with _lock:
            snap = dict(_status)
    return snap


def ensure_chromium_async() -> dict:
    """
    Kick off the install in a background thread if needed. Returns the
    current status dict immediately — caller is expected to poll.
    """
    if not _PW_PACKAGE_OK:
        _set_status(state="unavailable", ok=False,
                    message="playwright package missing")
        return install_status()

    if is_chromium_installed():
        _set_status(state="ready", ok=True,
                    message="Browser engine ready.",
                    started_at=None, ended_at=None)
        return install_status()

    with _lock:
        already = _status.get("state") == "installing"
    if already:
        return install_status()

    threading.Thread(
        target=_run_install_blocking,
        name="playwright-install",
        daemon=True,
    ).start()
    return install_status()
