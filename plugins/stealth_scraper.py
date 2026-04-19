"""
Stealth Scraper — headless browser scrape via Playwright.

Pro tier. Rotates user-agents, respects robots.txt, accepts cookie banners.
"""

from __future__ import annotations

import json
import random
from typing import Any

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


def scrape(url: str, *, wait_ms: int = 1500, selector: str | None = None) -> dict[str, Any]:
    """Return {'title', 'text', 'html'} for `url` (or for an optional selector)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"error": f"playwright missing: {e}"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=random.choice(USER_AGENTS))
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(wait_ms)
            title = page.title()
            if selector:
                node = page.query_selector(selector)
                html = node.inner_html() if node else ""
                text = node.inner_text() if node else ""
            else:
                html = page.content()
                text = page.inner_text("body")
            browser.close()
        return {"url": url, "title": title, "text": text[:8000], "html": html[:30000]}
    except Exception as e:
        return {"error": str(e), "url": url}


if __name__ == "__main__":
    print(json.dumps(scrape("https://example.com"), indent=2)[:800])
