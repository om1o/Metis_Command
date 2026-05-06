"""
Metis background daemon — system tray + global hotkey + pywebview window.

Targets the FastAPI-served web UI (default /splash on METIS_API_PORT).
Summoned via Ctrl+Space. System-tray menu: Open / Pause / Restart / Quit.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pystray  # type: ignore
    from pystray import Menu, MenuItem
except Exception:
    pystray = None  # type: ignore

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None  # type: ignore

try:
    from pynput import keyboard  # type: ignore
except Exception:
    keyboard = None  # type: ignore

try:
    import webview  # pywebview  # type: ignore
except Exception:
    webview = None  # type: ignore


API_PORT = int(os.getenv("METIS_API_PORT", "7331"))
# Single local web server: FastAPI serves HTML + API on METIS_API_PORT.
UI_URL = f"http://localhost:{API_PORT}/splash"
ROOT = Path(__file__).parent


# ── Tray icon ────────────────────────────────────────────────────────────────

def _build_tray_icon() -> "Image.Image | None":
    if Image is None:
        return None
    img = Image.new("RGBA", (64, 64), (11, 12, 16, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), outline=(102, 252, 241, 255), width=3)
    draw.polygon([(32, 16), (48, 32), (32, 48), (16, 32)], fill=(102, 252, 241, 255))
    return img


# ── Window controller ────────────────────────────────────────────────────────

class Metis:
    def __init__(self) -> None:
        self.window = None
        self.paused = False

    def show_window(self) -> None:
        if webview is None:
            print("[Daemon] pywebview missing — open", UI_URL, "in any browser.")
            return
        if self.window is None:
            self.window = webview.create_window(
                "Metis",
                UI_URL,
                width=1280,
                height=860,
                frameless=False,
                resizable=True,
                background_color="#0B0C10",
                on_top=False,
            )
            # webview.start() blocks; run it in a thread so the tray stays alive.
            threading.Thread(target=webview.start, daemon=True).start()
        else:
            try:
                self.window.show()
            except Exception:
                pass

    def hide_window(self) -> None:
        if self.window is not None:
            try:
                self.window.hide()
            except Exception:
                pass

    def toggle_window(self) -> None:
        if self.window is None:
            self.show_window()
            return
        try:
            self.window.hide() if not self.paused else self.window.show()
        except Exception:
            self.show_window()

    def pause(self) -> None:
        self.paused = not self.paused
        print(f"[Daemon] paused={self.paused}")

    def restart(self) -> None:
        print("[Daemon] restart flag written (launch / supervisor should pick up)…")
        # start_metis.pyw owns the subprocess lifecycle; signal by touching a file.
        (ROOT / "logs" / "restart.flag").parent.mkdir(parents=True, exist_ok=True)
        (ROOT / "logs" / "restart.flag").write_text(str(time.time()))


def _global_hotkey(metis: Metis) -> None:
    if keyboard is None:
        return
    combo = "<ctrl>+<space>"
    try:
        with keyboard.GlobalHotKeys({combo: metis.toggle_window}) as h:
            h.join()
    except Exception as e:
        print(f"[Daemon] hotkey thread exited: {e}")


def _tray_menu(metis: Metis, stop_event: threading.Event):
    def _on_quit(_icon=None, _item=None) -> None:
        stop_event.set()
        try:
            _icon.stop()
        except Exception:
            pass

    return Menu(
        MenuItem("Open Metis",  lambda _i=None, _it=None: metis.show_window(), default=True),
        MenuItem("Pause",       lambda _i=None, _it=None: metis.pause()),
        MenuItem("Restart UI",  lambda _i=None, _it=None: metis.restart()),
        MenuItem("Quit",        _on_quit),
    )


def run() -> None:
    metis = Metis()
    stop_event = threading.Event()

    # Global hotkey runs in its own thread.
    if keyboard is not None:
        threading.Thread(target=_global_hotkey, args=(metis,), daemon=True).start()
    else:
        print("[Daemon] pynput missing — global hotkey disabled.")

    # Tray icon runs in the main thread.
    if pystray is not None:
        icon_img = _build_tray_icon()
        icon = pystray.Icon(
            "metis",
            icon_img,
            "Metis — click to open",
            menu=_tray_menu(metis, stop_event),
        )

        def _on_click(_i=None, _it=None) -> None:
            metis.show_window()

        icon.menu = _tray_menu(metis, stop_event)
        # Auto-show window once the tray starts up.
        threading.Thread(
            target=lambda: (time.sleep(0.8), metis.show_window()),
            daemon=True,
        ).start()
        icon.run()
    else:
        print("[Daemon] pystray missing — running in console mode.")
        metis.show_window()
        while not stop_event.is_set():
            time.sleep(1.0)


if __name__ == "__main__":
    run()
