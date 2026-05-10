"""
MVP-15 dogfood: open a headed browser, let the user sign into Gmail
once, then re-open headless using the saved state and extract the
inbox so the manager LLM can summarize it.

Usage:
    python scripts/demo_gmail_summary.py login        # one-time sign-in
    python scripts/demo_gmail_summary.py extract      # headless inbox dump
    python scripts/demo_gmail_summary.py both         # login → extract
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the worktree importable regardless of CWD.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import browser_agent as ba


def login(wait_seconds: int = 60) -> dict:
    print("[demo] opening HEADED browser to mail.google.com")
    print(f"[demo] please sign in within {wait_seconds}s; the helper")
    print("[demo] auto-snapshots every 5s, so even if you close the")
    print("[demo] window early the cookies are already saved.\n")
    res = ba.login_helper(start_url="https://mail.google.com", wait_seconds=wait_seconds)
    print(f"[demo] login_helper returned: {json.dumps(res, indent=2)}")
    return res


def extract() -> dict:
    print("[demo] launching HEADLESS browser using saved state")
    ba.start(headless=True)
    nav = ba.goto("https://mail.google.com/mail/u/0/#inbox", wait_ms=4000)
    print(f"[demo] navigated to: {nav.get('url')}")
    print(f"[demo] page title: {nav.get('title')}")
    # Snapshot the viewport so we can confirm visually what was loaded.
    art = ba.screenshot(full_page=False)
    print(f"[demo] screenshot saved: {getattr(art, 'path', None)}")
    # Try the inbox-list role first; fall back to body text.
    out = ba.extract(selector='[role="main"]')
    if not out.get("text"):
        out = ba.extract()
    text = (out.get("text") or "")[:6000]
    print("\n[demo] -- inbox text (first 6k chars) --")
    print(text)
    print("[demo] -- end --")
    ba.close()
    return {"ok": True, "url": nav.get("url"), "title": nav.get("title"), "text": text}


def main() -> int:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    if cmd == "login":
        login()
    elif cmd == "extract":
        extract()
    elif cmd == "both":
        login()
        extract()
    else:
        print(f"unknown command: {cmd}; use login | extract | both")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
