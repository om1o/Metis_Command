"""
Metis Notifier — single entrypoint for "tell the Director something happened".

Routes a notification through the Director's preferred channels (set via
.env METIS_NOTIFY_PREFER, default "email,sms,voice") with hard daily caps
on Twilio-billable channels so a runaway loop can't burn the trial credit.

Public API:
    notify(subject, body, *, urgency="normal", user_id="default") -> dict

The shape of the return:
    {
      "delivered": ["email"],          # which channel actually succeeded
      "skipped":   ["sms (cap reached)", "voice (no number)"],
      "ok":        True,
    }

Urgency levels:
    "low"      → email only
    "normal"   → email; SMS only if email channel fails or isn't configured
    "high"     → email + SMS in parallel (both)
    "critical" → email + SMS + outbound voice call

Daily caps (env-overridable):
    METIS_NOTIFY_SMS_DAILY_CAP   default 20
    METIS_NOTIFY_VOICE_DAILY_CAP default 3

State (per-day counters) lives in identity/notify_log.jsonl, gitignored.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any


_LOG = Path("identity") / "notify_log.jsonl"


def _today() -> str:
    return date.today().isoformat()


def _read_today_counts() -> dict[str, int]:
    """Count how many of each channel we've used today."""
    if not _LOG.exists():
        return {}
    target = _today()
    counts: dict[str, int] = {}
    try:
        for line in _LOG.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if (row.get("date") or "") != target:
                continue
            if row.get("ok"):
                ch = row.get("channel") or ""
                counts[ch] = counts.get(ch, 0) + 1
    except Exception:
        return {}
    return counts


def _append(entry: dict) -> None:
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def daily_caps() -> dict[str, int]:
    return {
        "sms":   int(os.getenv("METIS_NOTIFY_SMS_DAILY_CAP", "20")),
        "voice": int(os.getenv("METIS_NOTIFY_VOICE_DAILY_CAP", "3")),
        "email": int(os.getenv("METIS_NOTIFY_EMAIL_DAILY_CAP", "200")),
    }


def daily_used(channel: str) -> int:
    return _read_today_counts().get(channel, 0)


def _under_cap(channel: str) -> bool:
    caps = daily_caps()
    cap = caps.get(channel)
    if cap is None or cap <= 0:
        return True
    return daily_used(channel) < cap


# ── Channel handlers ────────────────────────────────────────────────────────

def _send_email(to_email: str, subject: str, body: str, *, user_id: str) -> bool:
    if not to_email:
        return False
    if not _under_cap("email"):
        return False
    try:
        from comms_link import CommsLink
        ok = CommsLink().send_human_email(to_email, subject, body, user_id=user_id)
    except Exception as e:
        _append({"date": _today(), "ts": time.time(), "channel": "email",
                 "to": to_email, "ok": False, "err": str(e)[:160]})
        return False
    _append({"date": _today(), "ts": time.time(), "channel": "email",
             "to": to_email, "ok": bool(ok), "subject": subject[:80]})
    return bool(ok)


def _send_sms(phone: str, subject: str, body: str) -> bool:
    if not phone:
        return False
    if not _under_cap("sms"):
        return False
    text = (subject + "\n\n" + body)[:1500]   # SMS hard limit — Twilio splits at 1600
    try:
        from comms_link import CommsLink
        ok = CommsLink().send_text_message(phone, text)
    except Exception as e:
        _append({"date": _today(), "ts": time.time(), "channel": "sms",
                 "to": phone, "ok": False, "err": str(e)[:160]})
        return False
    _append({"date": _today(), "ts": time.time(), "channel": "sms",
             "to": phone, "ok": bool(ok), "subject": subject[:80]})
    return bool(ok)


def _place_call(phone: str, subject: str) -> bool:
    if not phone:
        return False
    if not _under_cap("voice"):
        return False
    try:
        from comms_link import CommsLink
        ok = CommsLink().place_outbound_call(phone)
    except Exception as e:
        _append({"date": _today(), "ts": time.time(), "channel": "voice",
                 "to": phone, "ok": False, "err": str(e)[:160]})
        return False
    _append({"date": _today(), "ts": time.time(), "channel": "voice",
             "to": phone, "ok": bool(ok), "subject": subject[:80]})
    return bool(ok)


# ── Main entrypoint ─────────────────────────────────────────────────────────

def notify(
    subject: str,
    body: str,
    *,
    urgency: str = "normal",
    user_id: str = "default",
) -> dict:
    """
    Route a notification to the Director through their preferred channels.

    Honors:
      - Per-user notification_email + notification_phone from manager_config
      - Per-user notify_on_complete + notify_on_question (auto-skip if False)
      - METIS_NOTIFY_PREFER env var ("email,sms,voice" by default)
      - Daily caps on each Twilio-billable channel
    """
    delivered: list[str] = []
    skipped: list[str] = []

    try:
        import manager_config as _mc
        cfg = _mc.get_config(user_id)
    except Exception:
        cfg = None

    email_to = (cfg.notification_email if cfg else "") or ""
    phone_to = (cfg.notification_phone if cfg else "") or ""

    # Master switches: if Director turned off complete notifications and
    # this is not high/critical, bail.
    if cfg and not cfg.notify_on_complete and urgency in ("low", "normal"):
        return {"delivered": [], "skipped": ["all (notify_on_complete=False)"], "ok": False}

    pref = (os.getenv("METIS_NOTIFY_PREFER") or "email,sms,voice").lower()
    pref_order = [c.strip() for c in pref.split(",") if c.strip()]

    # Decide which channels to try based on urgency.
    if urgency == "low":
        channels = ["email"]
    elif urgency == "normal":
        # Try the first preferred channel that's actually configured; SMS as
        # a fallback only if the first one fails.
        channels = pref_order[:2]
    elif urgency == "high":
        # Email + SMS in parallel (both succeed independently).
        channels = ["email", "sms"]
    elif urgency == "critical":
        # Hit everything available, in priority order.
        channels = pref_order[:3]
    else:
        channels = ["email"]

    fallback_attempted = False
    for ch in channels:
        ok = False
        if ch == "email":
            if not email_to:
                skipped.append("email (no address)"); continue
            ok = _send_email(email_to, subject, body, user_id=user_id)
            if not ok:
                skipped.append("email (send failed or capped)")
        elif ch == "sms":
            if not phone_to:
                skipped.append("sms (no phone)"); continue
            # For "normal" urgency, only fall back to SMS if email failed.
            if urgency == "normal" and "email" in delivered:
                skipped.append("sms (skipped — email already delivered)"); continue
            ok = _send_sms(phone_to, subject, body)
            if not ok:
                skipped.append("sms (send failed or capped)")
        elif ch == "voice":
            if not phone_to:
                skipped.append("voice (no phone)"); continue
            if urgency != "critical":
                skipped.append("voice (skipped — only critical uses voice)"); continue
            ok = _place_call(phone_to, subject)
            if not ok:
                skipped.append("voice (call failed or capped)")
        else:
            skipped.append(f"{ch} (unknown channel)")
            continue
        if ok:
            delivered.append(ch)

    return {
        "delivered": delivered,
        "skipped": skipped,
        "ok": bool(delivered),
    }


def status() -> dict:
    """Read-only summary used by the UI / status page."""
    used = _read_today_counts()
    caps = daily_caps()
    return {
        "today": _today(),
        "used":  used,
        "caps":  caps,
        "remaining": {ch: max(0, caps.get(ch, 0) - used.get(ch, 0)) for ch in caps},
    }
