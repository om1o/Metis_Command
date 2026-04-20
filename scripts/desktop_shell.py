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
        print(f"[shell] pywebview missing; opening in default browser: {url}",
              flush=True)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            return
        return

    print(f"[shell] opening desktop window -> {url}", flush=True)
    webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        resizable=True,
        fullscreen=False,
        min_size=(1100, 720),
    )
    webview.start(gui=os.getenv("METIS_WEBVIEW_GUI") or None, debug=False)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8501"
    if not wait_for_ui(target):
        print(f"[shell] UI never came up at {target}", file=sys.stderr)
        sys.exit(1)
    open_window(target)
