"""
Metis desktop shell - opens a native window pointing at the Streamlit UI.

Graceful fallback order:
    1. pywebview native window (Windows WebView2 / macOS WKWebView / Linux WebKit)
    2. system default browser
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
import webbrowser


def _ping(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def wait_for_ui(url: str, *, retries: int = 60, delay: float = 1.0) -> bool:
    for _ in range(retries):
        if _ping(url):
            return True
        time.sleep(delay)
    return False


_BANNER = r"""
   __  __      _   _     _____                                          _
  |  \/  | ___| |_(_)___|  ___|__  _ __ _ __   __ _ _ __ __| | ___  _ __ ___
  | |\/| |/ _ \ __| / __| |_ / _ \| '__| '_ \ / _` | '__/ _` |/ _ \| '__/ _ \
  | |  | |  __/ |_| \__ \  _| (_) | |  | | | | (_| | | | (_| | (_) | | |  __/
  |_|  |_|\___|\__|_|___/_|  \___/|_|  |_| |_|\__,_|_|  \__,_|\___/|_|  \___|
"""


def open_window(
    url: str,
    *,
    title: str = "Metis Command",
    width: int = 1400,
    height: int = 900,
) -> None:
    try:
        import webview  # pywebview
    except ImportError:
        print(_BANNER)
        print(f"[shell] pywebview missing; opening in default browser: {url}",
              flush=True)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            return
        return

    print(_BANNER)
    print(f"[shell] opening desktop window -> {url}", flush=True)
    # Ship an icon when one is available next to the repo root.
    from pathlib import Path as _P
    icon_candidates = [
        _P(__file__).resolve().parent.parent / "assets" / "metis_icon.svg",
        _P(__file__).resolve().parent.parent / "logo.png",
    ]
    icon: str | None = None
    for cand in icon_candidates:
        if cand.exists():
            icon = str(cand)
            break

    window_kwargs: dict = dict(
        title=title, url=url, width=width, height=height,
        resizable=True, fullscreen=False, min_size=(1100, 720),
    )
    webview.create_window(**window_kwargs)
    start_kwargs: dict = {"debug": False}
    if os.getenv("METIS_WEBVIEW_GUI"):
        start_kwargs["gui"] = os.getenv("METIS_WEBVIEW_GUI")
    if icon:
        # pywebview only supports `icon=` on some GUI backends; ignore if
        # it raises.
        try:
            webview.start(icon=icon, **start_kwargs)
            return
        except TypeError:
            pass
    webview.start(**start_kwargs)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8501"
    if not wait_for_ui(target):
        print(f"[shell] UI never came up at {target}", file=sys.stderr)
        sys.exit(1)
    open_window(target)
