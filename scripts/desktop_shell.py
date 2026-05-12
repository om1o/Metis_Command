"""
pywebview native-window wrapper for Metis Command.

Falls back to the system browser if pywebview is not installed.
"""
from __future__ import annotations

import time
import urllib.request


def wait_for_ui(url: str, *, timeout: float = 90.0, interval: float = 1.0) -> bool:
    """Block until ``url`` responds 2xx, or ``timeout`` seconds elapse."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                if 200 <= r.status < 400:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def open_window(url: str) -> None:
    """Open Metis in a native desktop window (pywebview) or browser fallback."""
    try:
        import webview  # type: ignore[import]
        window = webview.create_window(
            "Metis Command",
            url,
            width=1280,
            height=800,
            min_size=(800, 600),
            resizable=True,
        )
        webview.start(debug=False)
    except ImportError:
        import webbrowser
        print("[desktop_shell] pywebview not installed — opening browser", flush=True)
        webbrowser.open(url)
    except Exception as e:
        import webbrowser
        print(f"[desktop_shell] pywebview failed ({e}) — opening browser", flush=True)
        webbrowser.open(url)
