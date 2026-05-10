"""
Browser Agent — Manus / OpenAI Operator style.

A single stateful Playwright session the agents can drive:
    start(), goto(url), click(selector|text), fill(selector, text),
    submit(), screenshot(), extract(selector), wait(ms), close().

Plus an `autonomous_browse(goal, steps=20)` loop that asks the Coder
agent what to do next from the current page snapshot until it decides
the goal is done. Safe mode blocks file://, localhost admin ports, and
form submissions to non-allowlisted hosts by default.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from artifacts import Artifact, save_artifact
from safety import audit, audited, confirm_gate, ConfirmRequired, rate_limit

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # type: ignore
    _PW_OK = True
except Exception:
    _PW_OK = False


# ── Safety config ────────────────────────────────────────────────────────────

BLOCK_HOSTS = {
    "localhost", "127.0.0.1", "0.0.0.0",
    "169.254.169.254",  # cloud metadata
}

BLOCK_SCHEMES = {"file", "chrome", "chrome-extension"}


def _block_hosts_active() -> set[str]:
    """Localhost is blocked by default so agents cannot silently drive loopback admins.
    Set METIS_BROWSER_ALLOW_LOCALHOST=1 to allow automation against 127.0.0.1 (e.g. your own Dev UI).
    """
    blocked = set(BLOCK_HOSTS)
    if os.getenv("METIS_BROWSER_ALLOW_LOCALHOST", "").strip().lower() in {"1", "true", "yes", "on"}:
        blocked -= {"localhost", "127.0.0.1"}
    return blocked

SUBMIT_ALLOWLIST_HOSTS: set[str] = set()  # populated by user via allow_submit()

SCREENSHOTS_DIR = Path("artifacts") / "browser"


def allow_submit(host: str) -> None:
    """Whitelist a host for form submissions this session."""
    SUBMIT_ALLOWLIST_HOSTS.add(host.lower())


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme in BLOCK_SCHEMES:
        raise PermissionError(f"Scheme blocked: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    blocked = _block_hosts_active()
    if any(host == b or host.endswith(f".{b}") for b in blocked):
        raise PermissionError(f"Host blocked: {host}")


# ── Session singleton ────────────────────────────────────────────────────────

class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    def start(self, *, headless: bool = True) -> dict[str, Any]:
        if not _PW_OK:
            return {"ok": False, "error": "playwright not installed"}
        if self._page is not None:
            return {"ok": True, "note": "already running"}
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._ctx = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 860},
        )
        self._page = self._ctx.new_page()
        audit({"event": "browser_started", "headless": headless})
        return {"ok": True}

    def close(self) -> dict[str, Any]:
        try:
            if self._ctx:
                self._ctx.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._ctx = self._page = None
        audit({"event": "browser_closed"})
        return {"ok": True}

    # ── navigation ──────────────────────────────────────────────────────────
    def goto(self, url: str, *, wait_ms: int = 1500) -> dict[str, Any]:
        _check_url(url)
        if not rate_limit("browser.goto", per_minute=30):
            return {"ok": False, "error": "rate-limited"}
        self._ensure()
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(wait_ms)
        return {"ok": True, "url": self._page.url, "title": self._page.title()}

    def wait(self, ms: int = 1000) -> dict[str, Any]:
        self._ensure()
        self._page.wait_for_timeout(ms)
        return {"ok": True}

    # ── interaction ─────────────────────────────────────────────────────────
    def click(self, target: str, *, by_text: bool = False) -> dict[str, Any]:
        self._ensure()
        try:
            locator = self._page.get_by_text(target, exact=False) if by_text \
                      else self._page.locator(target)
            locator.first.click(timeout=8000)
            return {"ok": True, "clicked": target}
        except Exception as e:
            return {"ok": False, "error": str(e), "target": target}

    def fill(self, selector: str, value: str) -> dict[str, Any]:
        self._ensure()
        try:
            self._page.locator(selector).first.fill(value, timeout=8000)
            return {"ok": True, "selector": selector, "bytes": len(value)}
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def submit(self, selector: str | None = None, *, confirm_token: str | None = None) -> dict[str, Any]:
        """Submit a form — confirm-gated unless the host is in SUBMIT_ALLOWLIST_HOSTS."""
        self._ensure()
        host = urlparse(self._page.url).hostname or ""
        if host.lower() not in SUBMIT_ALLOWLIST_HOSTS:
            if confirm_token is None:
                tok = confirm_gate("browser.submit", {"host": host, "selector": selector})
                raise ConfirmRequired(tok)
            confirm_gate("browser.submit", {"host": host, "selector": selector}, token=confirm_token)
        try:
            if selector:
                self._page.locator(selector).first.press("Enter")
            else:
                self._page.keyboard.press("Enter")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── extraction ──────────────────────────────────────────────────────────
    def extract(self, selector: str | None = None, *, max_chars: int = 8000) -> dict[str, Any]:
        self._ensure()
        if selector:
            loc = self._page.locator(selector).first
            text = loc.inner_text(timeout=6000) if loc.count() else ""
            html = loc.inner_html(timeout=6000) if loc.count() else ""
        else:
            text = self._page.inner_text("body")
            html = self._page.content()
        return {
            "ok":    True,
            "url":   self._page.url,
            "title": self._page.title(),
            "text":  (text or "")[:max_chars],
            "html":  (html or "")[:max_chars * 3],
        }

    def screenshot(self, *, full_page: bool = False) -> Artifact:
        self._ensure()
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        out = SCREENSHOTS_DIR / f"browser_{int(time.time()*1000)}.png"
        self._page.screenshot(path=str(out), full_page=full_page)
        return save_artifact(Artifact(
            type="image",
            title=f"Browser · {self._page.title()[:60]}",
            path=str(out),
            metadata={"url": self._page.url, "full_page": full_page},
        ))

    def snapshot(self, *, max_chars: int = 4000) -> dict[str, Any]:
        """A concise page summary the LLM can reason over."""
        self._ensure()
        try:
            text = self._page.inner_text("body")
        except Exception:
            text = ""
        # Extract the first ~20 interactive elements by role+name.
        interactive: list[dict[str, str]] = []
        for role in ("button", "link", "textbox", "combobox", "checkbox", "menuitem"):
            try:
                loc = self._page.get_by_role(role)
                for i in range(min(loc.count(), 8)):
                    try:
                        name = loc.nth(i).inner_text(timeout=800).strip()[:80]
                        if name:
                            interactive.append({"role": role, "name": name})
                    except Exception:
                        continue
            except Exception:
                continue
        return {
            "url":           self._page.url,
            "title":         self._page.title(),
            "text_preview":  (text or "")[:max_chars],
            "interactive":   interactive[:24],
        }

    # ── internals ───────────────────────────────────────────────────────────
    def _ensure(self) -> None:
        if self._page is None:
            self.start(headless=True)


# Module-level singleton.
browser = Browser()


# ── Flat API (for slash commands / CrewAI) ──────────────────────────────────

@audited("browser.start")
def start(headless: bool = True) -> dict[str, Any]:
    return browser.start(headless=headless)


@audited("browser.goto")
def goto(url: str, wait_ms: int = 1500) -> dict[str, Any]:
    return browser.goto(url, wait_ms=wait_ms)


@audited("browser.click")
def click(target: str, by_text: bool = False) -> dict[str, Any]:
    return browser.click(target, by_text=by_text)


@audited("browser.fill")
def fill(selector: str, value: str) -> dict[str, Any]:
    return browser.fill(selector, value)


@audited("browser.extract")
def extract(selector: str | None = None) -> dict[str, Any]:
    return browser.extract(selector)


@audited("browser.snapshot_meta")
def snapshot_meta(*, max_chars: int = 4000) -> dict[str, Any]:
    """LLM-readable page sketch (interactive elements + text preview)."""
    browser.start(headless=True)
    return browser.snapshot(max_chars=max_chars)


@audited("browser.screenshot")
def screenshot(full_page: bool = False) -> Artifact:
    return browser.screenshot(full_page=full_page)


@audited("browser.close")
def close() -> dict[str, Any]:
    return browser.close()


# ── Autonomous browse loop (Manus / Operator) ───────────────────────────────

def autonomous_browse(goal: str, *, start_url: str, steps: int = 20) -> dict[str, Any]:
    """
    Let the Coder agent drive the browser turn-by-turn until `goal` is met.
    Every step: the agent receives the current snapshot + goal, replies with a
    JSON action, we execute it, loop. Stops on FINISH or after `steps`.
    """
    from brain_engine import chat_by_role
    browser.start(headless=True)
    browser.goto(start_url)

    history: list[dict[str, Any]] = []
    for step in range(1, steps + 1):
        snap = browser.snapshot()
        system = (
            "You are Metis's browser pilot. Given the current page snapshot and "
            "the Director's goal, respond with a single JSON action and nothing else.\n"
            "Valid actions: "
            '{"action":"goto","url":"https://..."} | '
            '{"action":"click","target":"selector or text","by_text":true} | '
            '{"action":"fill","selector":"css","value":"text"} | '
            '{"action":"extract","selector":"optional css"} | '
            '{"action":"screenshot"} | '
            '{"action":"finish","answer":"the final answer"}'
        )
        user = (
            f"GOAL: {goal}\n\n"
            f"STEP: {step}/{steps}\n"
            f"CURRENT URL: {snap['url']}\n"
            f"TITLE: {snap['title']}\n"
            f"INTERACTIVE (subset):\n{json.dumps(snap['interactive'], indent=2)}\n\n"
            f"TEXT PREVIEW:\n{snap['text_preview'][:2000]}\n\n"
            "Return one JSON action."
        )
        raw = chat_by_role("coder", [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ])
        action = _extract_action(raw)
        history.append({"step": step, "action": action, "url": snap["url"]})
        audit({"event": "browse_step", "step": step, "action": action})

        kind = (action or {}).get("action")
        if kind == "finish":
            browser.screenshot()
            return {"ok": True, "answer": action.get("answer", ""), "steps": history}
        if kind == "goto":
            browser.goto(action.get("url", ""))
        elif kind == "click":
            browser.click(action.get("target", ""), by_text=bool(action.get("by_text")))
        elif kind == "fill":
            browser.fill(action.get("selector", ""), action.get("value", ""))
        elif kind == "extract":
            browser.extract(action.get("selector"))
        elif kind == "screenshot":
            browser.screenshot()
        else:
            history[-1]["error"] = "unknown action"
            break
    return {"ok": False, "error": f"step cap {steps} reached", "steps": history}


_JSON_RX = re.compile(r"\{[\s\S]*\}")


def _extract_action(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    m = _JSON_RX.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ── CrewAI adapters ──────────────────────────────────────────────────────────

def as_crewai_tools() -> list[Any]:
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return []

    @tool("BrowserGoto")
    def _goto(url: str) -> str:
        """Navigate the shared browser to `url`."""
        return json.dumps(goto(url))

    @tool("BrowserExtract")
    def _extract(selector: str = "") -> str:
        """Extract text from the current browser page (or a CSS selector)."""
        return json.dumps(extract(selector or None))

    @tool("BrowserClick")
    def _click(target: str) -> str:
        """Click an element by CSS selector or visible text."""
        return json.dumps(click(target, by_text=True))

    @tool("BrowserScreenshot")
    def _shot() -> str:
        """Take a screenshot of the current page. Returns the artifact path."""
        art = screenshot()
        return art.path or art.id

    return [_goto, _extract, _click, _shot]
