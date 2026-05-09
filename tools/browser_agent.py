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

import atexit
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

SUBMIT_ALLOWLIST_HOSTS: set[str] = set()  # populated by user via allow_submit()

SCREENSHOTS_DIR = Path("artifacts") / "browser"

# MVP 15: persist cookies + localStorage across sessions so a one-time
# Gmail / Twitter / GitHub login lasts. Single file is simpler than
# per-host and matches Playwright's storage_state shape exactly.
BROWSER_STATE_FILE = Path("identity") / "browser_state.json"
# A real Chrome user-data-dir. login_helper writes here when the
# user signs in; the headless agent reuses the SAME directory so
# Google sees a profile with history, not a fresh sandbox. Solves
# the "this browser may not be secure" rejection that breaks stock
# Playwright Chromium against Gmail.
BROWSER_PROFILE_DIR = Path("identity") / "chrome_profile"


def allow_submit(host: str) -> None:
    """Whitelist a host for form submissions this session."""
    SUBMIT_ALLOWLIST_HOSTS.add(host.lower())


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme in BLOCK_SCHEMES:
        raise PermissionError(f"Scheme blocked: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if any(host == b or host.endswith(f".{b}") for b in BLOCK_HOSTS):
        raise PermissionError(f"Host blocked: {host}")


# ── Session singleton ────────────────────────────────────────────────────────

class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        # MVP 15+: belt-and-suspenders persistence. atexit fires even
        # when the process is killed mid-task (Ctrl-C, kernel OOM,
        # crash inside another tool), so cookies survive the things
        # that .close() can't catch.
        atexit.register(self._safe_snapshot)

    def _safe_snapshot(self) -> None:
        """Best-effort state save. Never raises — used by atexit and
        by every state-changing action so a fresh login is captured
        as soon as it happens, not only on close()."""
        if self._ctx is None:
            return
        try:
            BROWSER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._ctx.storage_state(path=str(BROWSER_STATE_FILE))
        except Exception:
            pass

    def start(self, *, headless: bool = True) -> dict[str, Any]:
        if not _PW_OK:
            return {"ok": False, "error": "playwright not installed"}
        if self._page is not None:
            return {"ok": True, "note": "already running"}
        self._pw = sync_playwright().start()
        # MVP 15: prefer the persistent profile dir login_helper
        # populated. Falls back to an ephemeral context + storage_state
        # if the profile doesn't exist yet (older deployments, or the
        # user never ran login_helper).
        viewport = {"width": 1280, "height": 860}
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/127.0 Safari/537.36")
        if BROWSER_PROFILE_DIR.exists():
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "viewport": viewport,
                "user_agent": ua,
            }
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE_DIR),
                    channel="chrome",
                    **launch_kwargs,
                )
            except Exception:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE_DIR),
                    **launch_kwargs,
                )
            self._browser = None  # persistent_context doesn't expose .browser cleanly
            self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            audit({
                "event": "browser_started",
                "headless": headless,
                "mode": "persistent_profile",
                "profile_dir": str(BROWSER_PROFILE_DIR),
            })
            return {"ok": True, "mode": "persistent_profile"}
        # Legacy path — ephemeral context loading storage_state if present.
        self._browser = self._pw.chromium.launch(headless=headless)
        ctx_kwargs: dict[str, Any] = {
            "user_agent": ua,
            "viewport": viewport,
        }
        if BROWSER_STATE_FILE.exists():
            ctx_kwargs["storage_state"] = str(BROWSER_STATE_FILE)
        self._ctx = self._browser.new_context(**ctx_kwargs)
        self._page = self._ctx.new_page()
        audit({
            "event": "browser_started",
            "headless": headless,
            "mode": "ephemeral",
            "loaded_state": BROWSER_STATE_FILE.exists(),
        })
        return {"ok": True, "mode": "ephemeral", "loaded_state": BROWSER_STATE_FILE.exists()}

    def save_state(self) -> dict[str, Any]:
        """Snapshot cookies + localStorage to disk so the next session
        reuses the same logins."""
        if self._ctx is None:
            return {"ok": False, "error": "browser not running"}
        try:
            BROWSER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._ctx.storage_state(path=str(BROWSER_STATE_FILE))
            audit({"event": "browser_state_saved", "path": str(BROWSER_STATE_FILE)})
            return {"ok": True, "path": str(BROWSER_STATE_FILE)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def clear_state(self) -> dict[str, Any]:
        """Delete the persisted state file. Useful for sign-out."""
        try:
            if BROWSER_STATE_FILE.exists():
                BROWSER_STATE_FILE.unlink()
            audit({"event": "browser_state_cleared"})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self) -> dict[str, Any]:
        # Snapshot before tearing down so cookies survive the next launch.
        try:
            if self._ctx is not None:
                BROWSER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                self._ctx.storage_state(path=str(BROWSER_STATE_FILE))
        except Exception:
            pass
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
        # Most logins hand you a redirect → snapshot here catches the
        # OAuth callback cookies the moment they land.
        self._safe_snapshot()
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
            self._safe_snapshot()
            return {"ok": True, "clicked": target}
        except Exception as e:
            return {"ok": False, "error": str(e), "target": target}

    def click_smart(
        self,
        target: str,
        *,
        retries: int = 2,
        kinds: tuple[str, ...] = ("button", "link", "menuitem", "checkbox", "radio"),
    ) -> dict[str, Any]:
        """Click an element described in natural language.

        Walks Playwright's locator strategies in order of specificity:
            1. role+name (button "Submit") — most reliable
            2. exact label / placeholder
            3. exact text
            4. raw CSS selector (in case the caller passed one)

        Retries on PWTimeout to ride out stale-element / partial-render
        races. Returns ``{ok, used_strategy, target}``.
        """
        self._ensure()
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            for strategy, build in self._locator_candidates(target, kinds):
                try:
                    loc = build()
                    if loc.count() == 0:
                        continue
                    loc.first.click(timeout=4000)
                    self._safe_snapshot()
                    return {"ok": True, "used_strategy": strategy, "target": target}
                except PWTimeout as e:
                    last_err = e
                    continue
                except Exception as e:
                    last_err = e
                    continue
            # Brief settle before next outer retry — handles the
            # "element appears mid-render" race.
            try:
                self._page.wait_for_timeout(400)
            except Exception:
                break
        return {"ok": False, "error": str(last_err) if last_err else "no candidate matched",
                "target": target}

    def _locator_candidates(self, target: str, kinds: tuple[str, ...]):
        """Yield (strategy_name, locator_builder) pairs in priority order."""
        page = self._page
        # 1. role + accessible name — by far the most stable.
        for role in kinds:
            yield (f"role:{role}",
                   lambda r=role: page.get_by_role(r, name=target))
        # 2. label (form fields)
        yield ("label",       lambda: page.get_by_label(target))
        # 3. placeholder (input/textarea)
        yield ("placeholder", lambda: page.get_by_placeholder(target))
        # 4. test id (rare but unambiguous)
        yield ("test-id",     lambda: page.get_by_test_id(target))
        # 5. title attribute (icon-only buttons)
        yield ("title",       lambda: page.get_by_title(target))
        # 6. visible text — broadest, most ambiguous, last.
        yield ("text",        lambda: page.get_by_text(target, exact=False))
        # 7. raw selector — caller may have passed CSS.
        yield ("css",         lambda: page.locator(target))

    def fill(self, selector: str, value: str) -> dict[str, Any]:
        self._ensure()
        try:
            self._page.locator(selector).first.fill(value, timeout=8000)
            self._safe_snapshot()
            return {"ok": True, "selector": selector, "bytes": len(value)}
        except Exception as e:
            return {"ok": False, "error": str(e), "selector": selector}

    def fill_smart(self, label: str, value: str, *, retries: int = 2) -> dict[str, Any]:
        """Fill a form field identified by its label, placeholder, or
        adjacent text. Same locator-cascade pattern as click_smart."""
        self._ensure()
        last_err: Exception | None = None
        page = self._page
        candidates = [
            ("label",       lambda: page.get_by_label(label)),
            ("placeholder", lambda: page.get_by_placeholder(label)),
            ("role:textbox", lambda: page.get_by_role("textbox", name=label)),
            ("role:combobox", lambda: page.get_by_role("combobox", name=label)),
            ("test-id",     lambda: page.get_by_test_id(label)),
            ("css",         lambda: page.locator(label)),
        ]
        for attempt in range(retries + 1):
            for strategy, build in candidates:
                try:
                    loc = build()
                    if loc.count() == 0:
                        continue
                    loc.first.fill(value, timeout=4000)
                    self._safe_snapshot()
                    return {"ok": True, "used_strategy": strategy,
                            "label": label, "bytes": len(value)}
                except PWTimeout as e:
                    last_err = e
                    continue
                except Exception as e:
                    last_err = e
                    continue
            try:
                page.wait_for_timeout(400)
            except Exception:
                break
        return {"ok": False, "error": str(last_err) if last_err else "no field matched",
                "label": label}

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


@audited("browser.click_smart")
def click_smart(target: str, retries: int = 2) -> dict[str, Any]:
    """Semantic click. Pass natural-language descriptions like
    "Submit", "Sign in", "Save changes" — we walk role/label/text
    strategies until something matches."""
    return browser.click_smart(target, retries=retries)


@audited("browser.fill_smart")
def fill_smart(label: str, value: str, retries: int = 2) -> dict[str, Any]:
    """Semantic fill. Identifies form fields by their label,
    placeholder, or accessible name — no CSS selector required."""
    return browser.fill_smart(label, value, retries=retries)


@audited("browser.extract")
def extract(selector: str | None = None) -> dict[str, Any]:
    return browser.extract(selector)


@audited("browser.screenshot")
def screenshot(full_page: bool = False) -> Artifact:
    return browser.screenshot(full_page=full_page)


@audited("browser.close")
def close() -> dict[str, Any]:
    return browser.close()


@audited("browser.save_state")
def save_state() -> dict[str, Any]:
    """Snapshot the active session's cookies + localStorage."""
    return browser.save_state()


@audited("browser.clear_state")
def clear_state() -> dict[str, Any]:
    """Wipe persisted cookies — equivalent to logging the agent out
    of every site it remembered."""
    return browser.clear_state()


def _find_chrome_exe() -> str | None:
    """Locate the user's installed Chrome binary."""
    import shutil
    cand = shutil.which("chrome") or shutil.which("google-chrome")
    if cand:
        return cand
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def _launch_chrome_with_debug_port(
    port: int, user_data_dir: str, start_url: str | None = None,
) -> dict[str, Any]:
    """Spawn the user's real Chrome with --remote-debugging-port set.
    Chrome boots as a normal browser, NOT an automated one — that's
    the whole point: navigator.webdriver stays false, Google trusts
    the sign-in. We attach via CDP afterwards.

    If start_url is given it's passed as a command-line argument so
    Chrome opens it itself — no Playwright-driven navigation, which
    helps bypass the strictest checks.
    """
    import socket
    import subprocess
    import time as _t

    chrome = _find_chrome_exe()
    if not chrome:
        return {"ok": False, "error": "Chrome binary not found"}
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    # Quick port-already-up check — if user already started Chrome
    # with debug port, skip the launch.
    def _port_open() -> bool:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.4)
            s.close()
            return True
        except OSError:
            return False

    if _port_open():
        return {"ok": True, "note": "debug port already up", "port": port}

    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if start_url and start_url != "about:blank":
        args.append(start_url)
    proc = subprocess.Popen(args)
    # Wait up to 15s for Chrome to start serving the CDP endpoint.
    for _ in range(60):
        if _port_open():
            return {"ok": True, "pid": proc.pid, "port": port}
        _t.sleep(0.25)
    return {"ok": False, "error": "Chrome started but debug port never opened"}


def login_helper(
    start_url: str = "about:blank",
    *,
    wait_seconds: int = 180,
    channel: str | None = "chrome",
    use_cdp: bool = True,
    port: int = 9222,
) -> dict[str, Any]:
    """Open a HEADED browser pointed at start_url, give the human up
    to wait_seconds to log into Gmail/Twitter/whatever, then snapshot
    the state and close. After this runs once per provider, the
    headless agent reuses those cookies forever.

    Persistence is opportunistic: we snapshot every 5s during the
    wait window so a sign-in that completes at second 30 is captured
    even if the user closes the browser at second 31. The final
    snapshot at the end is still authoritative.

    ``channel="chrome"`` uses the user's installed Chrome binary
    rather than Playwright's bundled Chromium — necessary for Gmail,
    which blocks stock Chromium with "this browser may not be
    secure". Falls back to chromium if real Chrome isn't installed.
    """
    if not _PW_OK:
        return {"ok": False, "error": "playwright not installed"}
    pw = sync_playwright().start()
    try:
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        ctx = None
        cdp_browser = None
        if use_cdp:
            # CDP attach: spawn real Chrome WITHOUT any Playwright
            # automation flags, then connect to its DevTools port.
            # Google's "this browser is not secure" check looks for
            # navigator.webdriver and CDP startup flags — neither is
            # set in this mode, so sign-in proceeds normally.
            # Pass start_url to Chrome itself so navigation happens
            # in the browser, not through Playwright.
            launch_res = _launch_chrome_with_debug_port(
                port, str(BROWSER_PROFILE_DIR), start_url=start_url,
            )
            if not launch_res.get("ok"):
                # CDP route failed; fall through to launch_persistent_context.
                use_cdp = False
            else:
                cdp_browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                # Reuse the default context Chrome started with.
                ctx = cdp_browser.contexts[0] if cdp_browser.contexts else cdp_browser.new_context()
        if ctx is None:
            # Fallback: persistent context (won't bypass bot detection
            # on Google but still works for non-Google sign-ins).
            launch_kwargs: dict[str, Any] = {
                "headless": False,
                "viewport": {"width": 1280, "height": 860},
            }
            if channel:
                launch_kwargs["channel"] = channel
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE_DIR), **launch_kwargs,
                )
            except Exception:
                launch_kwargs.pop("channel", None)
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE_DIR), **launch_kwargs,
                )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # Skip Playwright-driven navigation when we're in CDP mode —
        # Chrome already opened start_url via its command line, so
        # any further nav from us would just leave a Playwright
        # fingerprint Google can detect.
        if not use_cdp and start_url and start_url != "about:blank":
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
        BROWSER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Periodic snapshot. We use time.sleep instead of
        # page.wait_for_timeout because the user may close/reload
        # the page mid-sign-in, which would invalidate the page
        # handle but not the context we're snapshotting from.
        import time as _t
        slice_s = 5
        elapsed = 0
        while elapsed < wait_seconds:
            _t.sleep(min(slice_s, wait_seconds - elapsed))
            elapsed += slice_s
            try:
                ctx.storage_state(path=str(BROWSER_STATE_FILE))
            except Exception:
                pass
        # Final authoritative snapshot.
        try:
            ctx.storage_state(path=str(BROWSER_STATE_FILE))
        except Exception:
            pass
        # In CDP mode we don't close ctx — that would close the user's
        # Chrome session. Just disconnect Playwright; Chrome stays up.
        try:
            if cdp_browser is not None:
                cdp_browser.close()
            else:
                ctx.close()
        except Exception:
            pass
        return {
            "ok": True,
            "saved_to": str(BROWSER_STATE_FILE),
            "profile_dir": str(BROWSER_PROFILE_DIR),
            "waited_s": wait_seconds,
            "mode": "cdp" if cdp_browser is not None else "persistent",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try: pw.stop()
        except Exception: pass


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
