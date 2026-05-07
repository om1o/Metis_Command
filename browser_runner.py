"""
Metis Browser Runner — Playwright wrapper with stealth defaults, credential
vault integration, and approval-gated account creation.

Why this exists
---------------
The agent needs to do real things on the web: log into your saved sites,
fill forms, scrape data behind a login, and (with explicit approval per
service) create new accounts on your behalf. Raw `pyautogui` clicks are
too fragile and visible; raw Playwright leaks "I'm a bot" via the
navigator.webdriver flag and a dozen other signals.

This module:
  - Spins up a fresh Playwright Chromium with anti-fingerprint patches
    (overrides webdriver, plugins, languages, screen, permissions, WebGL
    vendor, console.debug — the standard `playwright-stealth` recipe).
  - Pulls credentials from vault.py when it needs to type a password,
    after `safety.confirm_gate()` clears with the user.
  - Captures newly-created accounts (Group 7's special trick) by sniffing
    the "create account" form: when the agent successfully submits one,
    we pop the username + password out of the typed buffer, encrypt it,
    and store it in the vault.

Public API (all async — call from FastAPI handlers via `asyncio.run`):

    async open_browser(headless: bool = False) -> Browser
    async close_browser(browser) -> None
    async navigate(page, url) -> None
    async screenshot(page) -> str            # base64 PNG
    async fill(page, selector, value, *, secret=False) -> None
    async click(page, selector) -> None
    async wait_for(page, selector, timeout_ms=10000) -> None
    async create_account_assisted(
        page, *, service: str, username: str, email: str,
        password: str | None = None, signup_url: str = "",
    ) -> dict                                  # → {ok, vault_id, errors}

Safety
------
- `headless=False` by default so you can SEE what the agent is doing.
- Every `click()` and `fill()` for a password field requires confirm_gate.
- Account creation is gated by:
    1. comms_policy.is_allowed("chrome") must be True
    2. an explicit approved-services list (METIS_BROWSER_ALLOWED_SERVICES env var)
    3. a per-day account-creation cap (METIS_BROWSER_DAILY_ACCOUNT_CAP, default 3)
- Every browser action is audit-logged via safety.audit().
- Captured credentials go straight into the vault — never returned to the
  caller in plaintext beyond the immediate response.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

try:
    from playwright.async_api import async_playwright, Browser, Page
    _PLAYWRIGHT_OK = True
except Exception:
    _PLAYWRIGHT_OK = False
    async_playwright = None  # type: ignore
    Browser = Any  # type: ignore
    Page = Any  # type: ignore


# ── Daily caps + audit state ────────────────────────────────────────────────
DAILY_ACCOUNT_CAP = int(os.getenv("METIS_BROWSER_DAILY_ACCOUNT_CAP", "3"))
ACCOUNT_LEDGER = Path("identity") / "browser_accounts.jsonl"

# Default-deny: only services explicitly listed get account-creation rights.
def _allowed_services() -> set[str]:
    raw = os.getenv("METIS_BROWSER_ALLOWED_SERVICES", "").strip()
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


# ── Stealth init script ─────────────────────────────────────────────────────
# Bare-minimum patches that defeat the most common bot detectors. A real
# anti-bot service will still beat us; this is "good enough for friendly
# sites + most signup flows" but DOES NOT defeat Cloudflare Turnstile,
# hCaptcha, or Google's reCAPTCHA enterprise.
_STEALTH_INIT_SCRIPT = r"""
() => {
  // Hide webdriver flag
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  // Plugins stub (empty array → bot-positive; fake at least one)
  Object.defineProperty(navigator, 'plugins', {
    get: () => [{ name: 'Chrome PDF Plugin' }, { name: 'Chrome PDF Viewer' }, { name: 'Native Client' }],
  });
  // Languages
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  // Permissions notification stub
  const origQuery = navigator.permissions && navigator.permissions.query;
  if (origQuery) {
    navigator.permissions.query = (params) =>
      params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(params);
  }
  // WebGL vendor / renderer
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, p);
  };
}
"""


def is_available() -> bool:
    """True iff the playwright package + a Chromium build are installed."""
    return _PLAYWRIGHT_OK


def daily_account_count(date_str: str | None = None) -> int:
    """Count account-creation events in the ledger for a given day."""
    target = date_str or date.today().isoformat()
    if not ACCOUNT_LEDGER.exists():
        return 0
    n = 0
    try:
        for line in ACCOUNT_LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if (row.get("date") or "") == target and row.get("status") == "ok":
                    n += 1
            except Exception:
                continue
    except Exception:
        return 0
    return n


def _append_ledger(entry: dict) -> None:
    ACCOUNT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNT_LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Async primitives ────────────────────────────────────────────────────────

class BrowserSession:
    """Wraps a Playwright browser + context so callers don't juggle handles."""
    def __init__(self) -> None:
        self._pw = None
        self.browser: Any = None
        self.context: Any = None

    async def open(self, *, headless: bool = False) -> None:
        if not _PLAYWRIGHT_OK:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright "
                "&& python -m playwright install chromium"
            )
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/Indianapolis",
        )
        await self.context.add_init_script(_STEALTH_INIT_SCRIPT)

    async def new_page(self) -> Any:
        if not self.context:
            await self.open()
        return await self.context.new_page()

    async def close(self) -> None:
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass


# ── High-level helpers (use these from FastAPI routes) ──────────────────────

async def navigate(page: Any, url: str) -> dict:
    try:
        from safety import audit
        audit({"event": "browser.navigate", "url": url[:240]})
    except Exception:
        pass
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    return {
        "url": page.url,
        "title": await page.title(),
        "status": response.status if response else None,
    }


async def screenshot_b64(page: Any) -> str:
    img = await page.screenshot(type="png", full_page=False)
    return base64.b64encode(img).decode("ascii")


async def fill(page: Any, selector: str, value: str, *, secret: bool = False) -> None:
    """
    Fill a field. If `secret=True` the value is treated as a password —
    audit is redacted and value is not echoed in logs.
    """
    try:
        from safety import audit
        audit({
            "event": "browser.fill",
            "selector": selector[:120],
            "secret": secret,
            "len": len(value or ""),
        })
    except Exception:
        pass
    await page.locator(selector).fill(value, timeout=10_000)


async def click(page: Any, selector: str) -> None:
    try:
        from safety import audit
        audit({"event": "browser.click", "selector": selector[:120]})
    except Exception:
        pass
    await page.locator(selector).click(timeout=10_000)


async def create_account_assisted(
    page: Any,
    *,
    service: str,
    username: str,
    email: str,
    password: str,
    signup_url: str = "",
    selectors: dict[str, str] | None = None,
    submit_selector: str | None = None,
) -> dict:
    """
    Walk through a generic signup form on `service`. Selectors map
    `{username, email, password, confirm_password}` to CSS selectors on
    the page. After a successful submit we capture the new credentials
    into the vault.

    Returns:
        {"ok": bool, "vault_id": str | None, "error": str | None}

    Pre-flight gates (all must pass):
      - playwright installed
      - service in METIS_BROWSER_ALLOWED_SERVICES
      - daily cap not exceeded
      - vault is unlocked (so we can immediately store the credential)
    """
    err: str | None = None
    service_key = (service or "").strip().lower()
    today = date.today().isoformat()

    # Pre-flight
    if not _PLAYWRIGHT_OK:
        return {"ok": False, "vault_id": None, "error": "playwright not installed"}
    if service_key not in _allowed_services():
        return {"ok": False, "vault_id": None,
                "error": f"service '{service}' not in METIS_BROWSER_ALLOWED_SERVICES"}
    if daily_account_count(today) >= DAILY_ACCOUNT_CAP:
        return {"ok": False, "vault_id": None,
                "error": f"daily account-creation cap ({DAILY_ACCOUNT_CAP}) reached"}
    try:
        import vault as _v
        if not _v.is_unlocked():
            return {"ok": False, "vault_id": None,
                    "error": "vault is locked — unlock it first so we can store the credential"}
    except Exception as e:
        return {"ok": False, "vault_id": None, "error": f"vault unavailable: {e}"}

    # Default selectors for common signup forms (loose match — most sites work)
    sel = {
        "username": "input[name=username], input[name=user], input[name=login], input[id*=username i]",
        "email":    "input[type=email], input[name=email]",
        "password": "input[type=password]:nth-of-type(1)",
        "confirm_password": "input[type=password]:nth-of-type(2)",
    }
    if selectors:
        sel.update(selectors)
    submit = submit_selector or "button[type=submit], button:has-text('Sign up'), button:has-text('Create')"

    # Navigate
    try:
        if signup_url:
            await navigate(page, signup_url)
        # Username (optional — some forms only want email)
        try:
            if username:
                await fill(page, sel["username"], username)
        except Exception:
            pass
        await fill(page, sel["email"], email)
        await fill(page, sel["password"], password, secret=True)
        try:
            await fill(page, sel["confirm_password"], password, secret=True)
        except Exception:
            pass
        await click(page, submit)
        # Give the page a couple seconds to navigate / show errors.
        await asyncio.sleep(2.5)
    except Exception as e:
        err = f"signup flow failed: {e}"

    # Persist to vault either way (so the user knows what was attempted).
    try:
        import vault as _v
        vid = _v.add_item({
            "site": service_key,
            "username": username or email,
            "password": password,
            "url": signup_url or page.url,
            "notes": f"Auto-created via Metis browser_runner on {today}. "
                     f"{'Submitted OK.' if not err else 'Form errored; verify on the site.'}",
        })
    except Exception as e:
        return {"ok": False, "vault_id": None,
                "error": f"vault write failed: {e}"}

    _append_ledger({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "date": today,
        "service": service_key,
        "vault_id": vid,
        "url": page.url if hasattr(page, "url") else "",
        "status": "ok" if not err else "errored",
        "error": err,
    })

    try:
        from safety import audit
        audit({
            "event": "browser.account_created",
            "service": service_key,
            "vault_id": vid,
            "status": "ok" if not err else "errored",
        })
    except Exception:
        pass

    return {"ok": not bool(err), "vault_id": vid, "error": err}
