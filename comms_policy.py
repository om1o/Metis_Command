"""
Runtime comms / tool policy — set from the Streamlit session so skills and
CommsLink respect what the Director enabled in the UI.
"""

from __future__ import annotations

import os
from typing import Any

_policy: dict[str, bool] = {
    "sms": False,
    "phone": False,
    "email": False,
    "calendar": False,
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
    }


def is_allowed(channel: str) -> bool:
    if not _enforced:
        return True
    return bool(_policy.get(channel, False))


def build_comms_system_block(state: dict[str, Any]) -> str:
    """Text injected into the system prompt so the model knows what is allowed."""
    lines = [
        "## Director tool permissions (current session)",
        f"- Text messages (SMS): {'**allowed** — you may use the send_sms skill' if state.get('tool_sms') else '**not allowed** — do not send SMS; offer a draft for the user to send manually.'}",
        f"- Phone calls (outbound): {'**allowed** — you may use place_outbound_call when appropriate' if state.get('tool_phone_calls') else '**not allowed** — do not place calls; offer a call script for the user.'}",
        f"- Email: {'**allowed** — you may use send_email skill' if state.get('tool_email') else '**not allowed** — do not send email; offer a draft only.'}",
        f"- Calendar / booking: {'**allowed** (when integrated)' if state.get('tool_calendar') else '**not allowed** — suggest times; do not claim a booking is confirmed.'}",
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
