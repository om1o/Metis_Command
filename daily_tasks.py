"""
Daily tasks — handlers for the seeded scheduler jobs.

These are plain functions the scheduler can invoke by name.  They are kept
out of scheduler.py so hot-reloading the handlers doesn't require touching
the scheduler daemon.  Each handler returns a short status string that the
scheduler logs.

Registered actions (see ACTIONS mapping):
    daily_briefing       — morning plan bundled from the roster
    nightly_brain_compact — fold oldest entries in every brain
    weekly_brain_backup  — export every brain to identity/backups/<date>.json
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable


ARTIFACTS_DIR = Path("artifacts")
BACKUPS_DIR = Path("identity") / "backups"


def _today() -> str:
    return date.today().isoformat()


# ── Daily briefing ──────────────────────────────────────────────────────────

def daily_briefing() -> str:
    """Run a morning briefing conversation and write a markdown plan."""
    try:
        import agent_bus as bus
        import agent_roster as roster
        import wallet
        from brain_engine import chat_by_role
        import brains as _brains
    except Exception as e:
        return f"briefing:deps-missing:{e}"

    participants = [
        s.slug for s in roster.list_roster()
        if s.slug in ("news_digest", "calendar_planner", "finance_watch", "inbox_triage")
    ]
    # Make sure persistent workers exist so they can answer via the bus.
    started_here: list[str] = []
    for slug in participants:
        if slug not in roster.list_persistent():
            if roster.spawn_persistent(slug):
                started_here.append(slug)

    goal = (
        "Prepare the Director's morning briefing. Each specialist reports its "
        "slice succinctly; the Orchestrator will collate at the end."
    )
    result = bus.conversation(goal=goal, participants=participants,
                              max_rounds=1, channel=bus.MORNING_BRIEFING)

    wallet_summary = wallet.summary()
    active_brain = _brains.active()
    brain_name = active_brain.name if active_brain else "(none)"

    # Ask the Genius to collate. Falls back to thinker if genius unavailable.
    role_for_collate = "genius"
    collated = chat_by_role(role_for_collate, [
        {"role": "system", "content":
            "You collate a morning briefing for the Director. Return "
            "Markdown with these sections: Today's Priorities, Schedule, "
            "Headlines, Financial Pulse, Actions. Be terse, no filler."},
        {"role": "user", "content":
            f"DATE: {_today()}\n"
            f"BRAIN: {brain_name}\n"
            f"WALLET: ${wallet_summary['balance_cents']/100:.2f} balance, "
            f"cap ${wallet_summary['monthly_cap_cents']/100:.2f}, "
            f"mode {wallet_summary['mode']}\n\n"
            f"SPECIALIST INPUTS (round-robin):\n{result.final_answer[:4000]}"},
    ]) or result.final_answer or ""

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / f"daily_plan_{_today()}.md"
    out_path.write_text(
        f"# Daily Plan — {_today()}\n\n{collated.strip()}\n",
        encoding="utf-8",
    )

    # Optional email delivery.
    try:
        import os
        to_addr = os.getenv("DAILY_PLAN_EMAIL", "").strip()
        if to_addr:
            from comms_link import CommsLink
            CommsLink().send_human_email(
                to_addr,
                f"Metis Daily Plan — {_today()}",
                collated,
            )
    except Exception:
        pass

    # Clean up agents we auto-started just for this run.
    for slug in started_here:
        try:
            roster.stop_persistent(slug)
        except Exception:
            pass

    try:
        from safety import audit
        audit({"event": "daily_briefing_written", "path": str(out_path)})
    except Exception:
        pass
    return f"briefing:ok:{out_path}"


# ── Nightly brain compact ───────────────────────────────────────────────────

def nightly_brain_compact() -> str:
    try:
        import brains
    except Exception as e:
        return f"compact:deps-missing:{e}"
    total = 0
    for b in brains.list_brains():
        try:
            total += brains.compact(brain=b, window=50)
        except Exception:
            continue
    return f"compact:ok:folded={total}"


# ── Weekly brain backup ─────────────────────────────────────────────────────

def weekly_brain_backup() -> str:
    try:
        import brains
    except Exception as e:
        return f"backup:deps-missing:{e}"
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    wrote: list[str] = []
    for b in brains.list_brains():
        out = BACKUPS_DIR / f"{b.slug}_{stamp}.json"
        try:
            brains.backup(str(out), brain=b)
            wrote.append(out.name)
        except Exception:
            continue
    return f"backup:ok:{len(wrote)}"


ACTIONS: dict[str, Callable[[], str]] = {
    "daily_briefing":       daily_briefing,
    "nightly_brain_compact": nightly_brain_compact,
    "weekly_brain_backup":  weekly_brain_backup,
}
