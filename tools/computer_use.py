"""
Computer Use — Metis's kill-shot vs. cloud-only AI.

These tools let the Coder / Manager agent actually SEE the screen and
control the mouse and keyboard. Every action that produces side effects
on the real desktop (click, type, key_combo) goes through a confirm gate
unless the caller passes confirm=False explicitly.
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Any

from artifacts import Artifact, save_artifact

try:
    import mss  # type: ignore
    import mss.tools  # type: ignore
    _MSS_OK = True
except Exception:
    _MSS_OK = False

try:
    import pyautogui  # type: ignore
    _PYAG_OK = True
    pyautogui.FAILSAFE = True  # flick mouse to (0,0) to abort
except Exception:
    _PYAG_OK = False

try:
    import pyperclip  # type: ignore
    _CLIP_OK = True
except Exception:
    _CLIP_OK = False


SCREENSHOTS_DIR = Path("artifacts") / "screenshots"


# ── Vision ───────────────────────────────────────────────────────────────────

def screenshot(region: tuple[int, int, int, int] | None = None) -> Artifact:
    """
    Capture the screen (or a region x,y,w,h) and save a PNG Artifact.
    """
    if not _MSS_OK:
        return save_artifact(Artifact(
            type="doc",
            title="Screenshot unavailable",
            content="mss is not installed; run `pip install mss`.",
            metadata={"error": "mss-missing"},
        ))

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    out = SCREENSHOTS_DIR / f"shot_{ts}.png"

    with mss.mss() as sct:
        if region:
            x, y, w, h = region
            monitor = {"left": x, "top": y, "width": w, "height": h}
        else:
            monitor = sct.monitors[1]
        shot = sct.grab(monitor)
        mss.tools.to_png(shot.rgb, shot.size, output=str(out))

    return save_artifact(Artifact(
        type="image",
        title=f"Screenshot {ts}",
        path=str(out),
        metadata={
            "region": list(region) if region else None,
            "size": [shot.size[0], shot.size[1]],
        },
    ))


# ── Mouse + keyboard (confirm-gated) ─────────────────────────────────────────

def _require_pyautogui() -> None:
    if not _PYAG_OK:
        raise RuntimeError("pyautogui is not installed; run `pip install pyautogui`.")


def click_xy(x: int, y: int, *, button: str = "left", confirm: bool = True) -> dict:
    """Move + click at screen coordinates. Confirm-gated by default."""
    _require_pyautogui()
    if confirm:
        print(f"[ComputerUse] Confirm-gated click at ({x},{y}) — pass confirm=False to execute.")
        return {"ok": False, "reason": "confirm-required", "x": x, "y": y}
    pyautogui.moveTo(x, y, duration=0.1)
    pyautogui.click(x=x, y=y, button=button)
    return {"ok": True, "x": x, "y": y, "button": button}


def double_click_xy(x: int, y: int, *, confirm: bool = True) -> dict:
    _require_pyautogui()
    if confirm:
        return {"ok": False, "reason": "confirm-required", "x": x, "y": y}
    pyautogui.doubleClick(x=x, y=y)
    return {"ok": True, "x": x, "y": y}


def type_text(text: str, *, interval: float = 0.02, confirm: bool = True) -> dict:
    _require_pyautogui()
    if confirm:
        return {"ok": False, "reason": "confirm-required", "preview": text[:40]}
    pyautogui.typewrite(text, interval=interval)
    return {"ok": True, "typed_chars": len(text)}


def key_combo(keys: list[str], *, confirm: bool = True) -> dict:
    _require_pyautogui()
    if confirm:
        return {"ok": False, "reason": "confirm-required", "keys": keys}
    pyautogui.hotkey(*keys)
    return {"ok": True, "keys": keys}


def scroll(amount: int, *, x: int | None = None, y: int | None = None,
           confirm: bool = True) -> dict:
    """Wheel-scroll by ``amount`` clicks (positive = up, negative = down).
    Optional ``(x, y)`` anchors the scroll on a specific spot — useful
    when the OS picks up scroll events on the focused window only."""
    _require_pyautogui()
    if confirm:
        return {"ok": False, "reason": "confirm-required", "amount": amount}
    if x is not None and y is not None:
        pyautogui.moveTo(x, y, duration=0.05)
    pyautogui.scroll(int(amount))
    return {"ok": True, "amount": amount, "x": x, "y": y}


def drag_xy(from_x: int, from_y: int, to_x: int, to_y: int, *,
            button: str = "left", duration: float = 0.4,
            confirm: bool = True) -> dict:
    """Press at (from_x, from_y), drag to (to_x, to_y), release.
    Useful for sliders, file-manager moves, drawing-app strokes."""
    _require_pyautogui()
    if confirm:
        return {"ok": False, "reason": "confirm-required",
                "from": [from_x, from_y], "to": [to_x, to_y]}
    pyautogui.moveTo(from_x, from_y, duration=0.1)
    pyautogui.dragTo(to_x, to_y, duration=float(duration), button=button)
    return {"ok": True, "from": [from_x, from_y], "to": [to_x, to_y], "button": button}


def right_click_xy(x: int, y: int, *, confirm: bool = True) -> dict:
    """Right-click at the given screen coordinates (open context menu)."""
    _require_pyautogui()
    if confirm:
        return {"ok": False, "reason": "confirm-required", "x": x, "y": y}
    pyautogui.rightClick(x=x, y=y)
    return {"ok": True, "x": x, "y": y, "button": "right"}


def mouse_move(x: int, y: int, *, duration: float = 0.1) -> dict:
    """Move the mouse without clicking. Triggers hover effects (menus
    that open on hover, tooltips, hover-based dropdowns). Read-only —
    no confirm needed."""
    _require_pyautogui()
    pyautogui.moveTo(int(x), int(y), duration=float(duration))
    return {"ok": True, "x": x, "y": y}


def open_application(name: str) -> dict:
    """Launch a desktop app by name or path.

    Cross-platform: uses os.startfile on Windows, ``open -a`` on
    macOS, and ``xdg-open`` on Linux. Returns the resolved command
    that was run so the caller can audit it.
    """
    import os as _os
    import platform as _plat
    import shutil as _shutil
    import subprocess as _subp

    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}

    system = _plat.system()
    try:
        if system == "Windows":
            # If it looks like an absolute path, run it directly; else
            # delegate to the shell so "Cursor" / "Notepad" / "Chrome"
            # resolve via App Paths or PATH.
            if _os.path.exists(name):
                _os.startfile(name)  # type: ignore[attr-defined]
            else:
                _subp.Popen(["cmd", "/c", "start", "", name], shell=False)
            return {"ok": True, "platform": system, "launched": name}
        if system == "Darwin":
            _subp.Popen(["open", "-a", name])
            return {"ok": True, "platform": system, "launched": name}
        # Linux / *nix
        opener = _shutil.which("xdg-open") or _shutil.which("gio")
        if not opener:
            return {"ok": False, "error": "no xdg-open / gio on PATH"}
        _subp.Popen([opener, name])
        return {"ok": True, "platform": system, "launched": name, "opener": opener}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Clipboard ────────────────────────────────────────────────────────────────

def read_clipboard() -> str:
    if not _CLIP_OK:
        return ""
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""


def write_clipboard(text: str) -> bool:
    if not _CLIP_OK:
        return False
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


# ── CrewAI tool registration ─────────────────────────────────────────────────

def as_crewai_tools() -> list[Any]:
    """Return these helpers wrapped as CrewAI tools for the Coder/Manager."""
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return []

    @tool("Screenshot")
    def _screenshot_tool() -> str:
        """Capture the screen and return the saved artifact path."""
        art = screenshot()
        return art.path or art.id

    @tool("ReadClipboard")
    def _read_clipboard_tool() -> str:
        """Return the current clipboard contents."""
        return read_clipboard()

    @tool("WriteClipboard")
    def _write_clipboard_tool(text: str) -> str:
        """Copy the provided text into the clipboard. Returns 'ok' on success."""
        return "ok" if write_clipboard(text) else "failed"

    return [_screenshot_tool, _read_clipboard_tool, _write_clipboard_tool]


def encode_png_b64(path: str) -> str:
    """Small helper to embed a screenshot in an HTML/img tag if needed."""
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
