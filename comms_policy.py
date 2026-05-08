"""
Runtime comms / tool policy — set from the Streamlit session so skills and
CommsLink respect what the Director enabled in the UI.
"""

from __future__ import annotations

import os
from typing import Any

# Channels the Director can enable/disable. New entries:
#   chrome           — control the Chrome browser via Playwright / Chrome MCP
#                      (clicks, fills, navigation, screenshot)
#   google_services  — read/write Gmail, Google Calendar, Google Drive,
#                      Google Docs, etc. via Google OAuth APIs
# Defaults flipped to True for these two because the operator explicitly
# pre-approved them; everything else stays opt-in.
_policy: dict[str, bool] = {
    "sms": False,
    "phone": False,
    "email": False,
    "calendar": False,
    "chrome": True,
    "google_services": True,
}

# When False, CommsLink does not block sends (CLI/tests/back-compat).
# Streamlit sets True each turn via set_from_session.
_enforced: bool = False


def policy_enforced() -> bool:
    return _enforced


def set_from_session(state: dict[str, Any]) -> None:
    global _policy, _enforced
    _enforced = True
    _policy = {
        "sms": bool(state.get("tool_sms", False)),
        "phone": bool(state.get("tool_phone_calls", False)),
        "email": bool(state.get("tool_email", False)),
        "calendar": bool(state.get("tool_calendar", False)),
        "chrome": bool(state.get("tool_chrome", True)),                # default ON
        "google_services": bool(state.get("tool_google_services", True)),  # default ON
    }


def get_policy() -> dict[str, bool]:
    """Return a copy of the current policy. Used by /policy GET."""
    return dict(_policy)


def is_allowed(channel: str) -> bool:
    if not _enforced:
        # Default-on channels are allowed even before the UI sets them; default-off stay false
        return _policy.get(channel, False) or channel in ("chrome", "google_services")
    return bool(_policy.get(channel, False))


def build_comms_system_block(state: dict[str, Any]) -> str:
    """Text injected into the system prompt so the model knows what is allowed."""
    chrome_on = state.get("tool_chrome", True)
    google_on = state.get("tool_google_services", True)
    lines = [
        "## Director tool permissions (current session)",
        f"- Text messages (SMS): {'**allowed** — you may use the send_sms skill' if state.get('tool_sms') else '**not allowed** — do not send SMS; offer a draft for the user to send manually.'}",
        f"- Phone calls (outbound): {'**allowed** — you may use place_outbound_call when appropriate' if state.get('tool_phone_calls') else '**not allowed** — do not place calls; offer a call script for the user.'}",
        f"- Email: {'**allowed** — you may use send_email skill' if state.get('tool_email') else '**not allowed** — do not send email; offer a draft only.'}",
        f"- Calendar / booking: {'**allowed** (when integrated)' if state.get('tool_calendar') else '**not allowed** — suggest times; do not claim a booking is confirmed.'}",
        f"- Chrome browser: {'**allowed** — you may navigate, click, type, fill forms, and take screenshots via the Chrome control tools. Always confirm with the Director before submitting forms or clicking irreversible buttons. Never type passwords without explicit confirmation.' if chrome_on else '**not allowed** — describe what to click; do not control the browser.'}",
        f"- Google services (Gmail / Calendar / Drive / Docs): {'**allowed** — you may read/write through the Google OAuth APIs once the Director has linked their account. Treat read access freely; treat sends/deletes as confirm-required.' if google_on else '**not allowed** — describe what to do, do not call Google APIs.'}",
        "",
        "If a channel is not allowed, still help with drafts, checklists, and what the user should say next.",
    ]
    return "\n".join(lines)


def twilio_configured() -> bool:
    return all(
        os.getenv(k)
        for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM")
    )


def smtp_configured() -> bool:
    return bool(os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASS"))
