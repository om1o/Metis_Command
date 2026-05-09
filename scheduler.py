"""
Mission Scheduler — Manus-style recurring autonomous tasks.

Schedule kinds:
    interval   — every N minutes
    daily      — HH:MM every day
    once       — run once at a specific ISO timestamp
    cron-like  — simple m/h/dom/mon/dow syntax (e.g. "0 9 * * mon-fri")

Schedules persist to `identity/schedules.json` so they survive restarts.
A daemon thread started via `start_scheduler()` wakes up every 30 seconds
to check due jobs and enqueue missions via `concurrency.submit()`.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    from croniter import croniter as _croniter  # type: ignore
except ImportError:
    _croniter = None  # type: ignore

from safety import audit, audited


from safety import PATHS, file_lock  # noqa: E402

SCHEDULES_FILE = PATHS.identity / "schedules.json"
_CHECK_INTERVAL = 30.0


def _notify_inbox_fired(s: "Schedule", *, body: str) -> None:
    """Best-effort notification when a schedule fires.

    Imports lazily so headless environments without the inbox module
    (e.g. tests stubbing the scheduler) keep working.
    """
    try:
        import inbox as _inbox
        _inbox.append(
            title=f"Job fired — {(s.goal or s.action or 'scheduled job')[:80]}",
            body=body,
            source=f"schedule:{s.id}",
            schedule_id=s.id,
        )
    except Exception:
        pass


@dataclass
class Schedule:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    kind: str = "interval"      # "interval" | "daily" | "once" | "cron"
    spec: str = "60"            # kind-dependent string
    goal: str = ""              # what mission to run (when action is empty)
    action: str = ""            # if set, run a handler from daily_tasks.ACTIONS instead
    enabled: bool = True
    project_slug: str | None = None
    auto_approve: bool = True   # scheduled tasks usually run unattended
    last_run: float | None = None
    next_run: float | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Persistence ──────────────────────────────────────────────────────────────

_lock = threading.Lock()


def _load() -> list[Schedule]:
    if not SCHEDULES_FILE.exists():
        return []
    try:
        return [Schedule(**row) for row in json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _save(schedules: list[Schedule]) -> None:
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(
        json.dumps([s.to_dict() for s in schedules], indent=2),
        encoding="utf-8",
    )


# ── Public API ───────────────────────────────────────────────────────────────

@audited("schedule.add")
def add(
    goal: str,
    *,
    kind: str = "interval",
    spec: str = "60",
    project_slug: str | None = None,
    auto_approve: bool = True,
    action: str = "",
) -> Schedule:
    sched = Schedule(
        kind=kind,
        spec=spec,
        goal=goal,
        action=action,
        project_slug=project_slug,
        auto_approve=auto_approve,
    )
    sched.next_run = _compute_next(sched, reference=time.time())
    with file_lock("scheduler"), _lock:
        schedules = _load()
        schedules.append(sched)
        _save(schedules)
    return sched


def seed_default_schedules() -> list[Schedule]:
    """
    Install the opinionated defaults on first boot:
      * daily_briefing       at DAILY_BRIEFING_TIME or 07:00
      * nightly_brain_compact at 02:00
      * weekly_brain_backup  via cron  0 3 * * sun

    Idempotent: checks by `action` so calling this repeatedly is safe.
    """
    import os
    with _lock:
        existing = _load()
    have_actions = {s.action for s in existing if s.action}
    added: list[Schedule] = []
    briefing_time = (os.getenv("DAILY_BRIEFING_TIME") or "07:00").strip() or "07:00"
    if "daily_briefing" not in have_actions:
        added.append(add(
            goal="Compile the Director's morning briefing from the roster.",
            kind="daily",
            spec=briefing_time,
            action="daily_briefing",
        ))
    if "nightly_brain_compact" not in have_actions:
        added.append(add(
            goal="Fold the oldest entries in every brain into higher-level facts.",
            kind="daily",
            spec="02:00",
            action="nightly_brain_compact",
        ))
    if "weekly_brain_backup" not in have_actions:
        added.append(add(
            goal="Export every brain to identity/backups/ for disaster recovery.",
            kind="cron",
            spec="0 3 * * sun",
            action="weekly_brain_backup",
        ))
    return added


@audited("schedule.remove")
def remove(schedule_id: str) -> bool:
    with file_lock("scheduler"), _lock:
        schedules = _load()
        before = len(schedules)
        schedules = [s for s in schedules if s.id != schedule_id]
        _save(schedules)
        return len(schedules) < before


@audited("schedule.toggle")
def toggle(schedule_id: str) -> bool:
    with file_lock("scheduler"), _lock:
        schedules = _load()
        for s in schedules:
            if s.id == schedule_id:
                s.enabled = not s.enabled
                _save(schedules)
                return s.enabled
    return False


def list_schedules() -> list[Schedule]:
    with _lock:
        return _load()


# ── Next-run computation ─────────────────────────────────────────────────────

def _compute_next(s: Schedule, *, reference: float) -> float | None:
    now = datetime.fromtimestamp(reference)
    kind = s.kind.lower()

    if kind == "interval":
        try:
            minutes = max(1, int(s.spec))
        except Exception:
            minutes = 60
        return reference + minutes * 60

    if kind == "daily":
        try:
            hh, mm = [int(x) for x in s.spec.split(":", 1)]
        except Exception:
            hh, mm = 9, 0
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # If today's slot already passed, move to the same time tomorrow.
        # Using timedelta avoids the edge case where day+1 lands on day 29-31
        # of a short month (the previous code used a `day < 28` heuristic).
        if target.timestamp() <= reference:
            target = target + timedelta(days=1)
        return target.timestamp()

    if kind == "once":
        try:
            ts = datetime.fromisoformat(s.spec).timestamp()
        except Exception:
            return None
        return ts if ts > reference else None

    if kind == "cron":
        return _next_cron(s.spec, reference)

    return None


_CRON_RX = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def _next_cron(expr: str, reference: float) -> float | None:
    """
    5-field cron: minute hour dom month dow.

    Uses `croniter` when installed (full cron syntax including step values,
    ranges, and named days). Falls back to a small bespoke parser that
    supports '*', comma lists, dashes, and '*/N' so the scheduler still
    works in environments where croniter isn't installed.
    """
    if _croniter is not None:
        try:
            it = _croniter(expr, datetime.fromtimestamp(reference))
            return float(it.get_next(float))
        except Exception:
            return None

    m = _CRON_RX.match(expr or "")
    if not m:
        return None
    fields = list(m.groups())
    days_text = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

    def matches(value: int, field: str, max_val: int, lookup: dict | None = None) -> bool:
        for part in field.split(","):
            part = part.strip().lower()
            if part == "*":
                return True
            if part.startswith("*/"):
                try:
                    step = int(part[2:])
                    if step > 0 and value % step == 0:
                        return True
                except Exception:
                    pass
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                a_v = lookup.get(a, int(a) if a.isdigit() else -1) if lookup else int(a)
                b_v = lookup.get(b, int(b) if b.isdigit() else -1) if lookup else int(b)
                if a_v <= value <= b_v:
                    return True
                continue
            try:
                target = lookup.get(part, int(part)) if lookup else int(part)
            except Exception:
                continue
            if value == target:
                return True
        return False

    # Walk forward minute-by-minute up to 7 days.
    probe = datetime.fromtimestamp(reference).replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 7):
        probe_ts = probe.timestamp() + 60
        probe = datetime.fromtimestamp(probe_ts)
        if (matches(probe.minute, fields[0], 59)
                and matches(probe.hour,   fields[1], 23)
                and matches(probe.day,    fields[2], 31)
                and matches(probe.month,  fields[3], 12)
                and matches(probe.weekday() + 1 if probe.weekday() != 6 else 0,  # dow 0=sun
                            fields[4], 6, days_text)):
            return probe.timestamp()
    return None


# ── Daemon thread ────────────────────────────────────────────────────────────

_running = threading.Event()
_thread: threading.Thread | None = None


def start_scheduler(runner: Callable[[Schedule], None] | None = None) -> None:
    """
    Start the background check loop. `runner` receives a Schedule when it's due.
    Default runner imports `concurrency.submit_mission` to run asynchronously.
    """
    global _thread
    if _thread and _thread.is_alive():
        return

    if runner is None:
        def runner(s: Schedule) -> None:
            # Action schedules call directly into daily_tasks — no mission loop.
            if s.action:
                try:
                    from daily_tasks import ACTIONS
                    handler = ACTIONS.get(s.action)
                    if not handler:
                        audit({"event": "scheduler_unknown_action",
                               "action": s.action, "schedule_id": s.id})
                        return
                    status = handler()
                    audit({"event": "scheduler_action_ran",
                           "action": s.action, "schedule_id": s.id, "status": status})
                    _notify_inbox_fired(s, body=f"Action `{s.action}` finished with status: {status}.")
                except Exception as e:
                    audit({"event": "scheduler_action_failed",
                           "action": s.action, "schedule_id": s.id, "error": str(e)})
                    _notify_inbox_fired(s, body=f"Action `{s.action}` failed: {e}")
                return

            try:
                from concurrency import submit_mission
                submit_mission(
                    goal=s.goal,
                    tag=f"scheduled:{s.id}",
                    auto_approve=s.auto_approve,
                    project_slug=s.project_slug,
                )
                _notify_inbox_fired(s, body="Mission queued. Check the chat or workspace for the result.")
            except Exception as e:
                audit({"event": "scheduler_submit_failed", "schedule_id": s.id, "error": str(e)})
                _notify_inbox_fired(s, body=f"Could not queue mission: {e}")

    _running.set()

    def loop() -> None:
        while _running.is_set():
            try:
                _tick(runner)
            except Exception as e:
                audit({"event": "scheduler_tick_error", "error": str(e)})
            time.sleep(_CHECK_INTERVAL)

    _thread = threading.Thread(target=loop, daemon=True, name="MetisScheduler")
    _thread.start()
    audit({"event": "scheduler_started"})


def stop_scheduler() -> None:
    _running.clear()
    audit({"event": "scheduler_stopped"})


def _tick(runner: Callable[[Schedule], None]) -> None:
    now = time.time()
    with file_lock("scheduler"), _lock:
        schedules = _load()
        dirty = False
        for s in schedules:
            if not s.enabled:
                continue
            if s.next_run is None:
                s.next_run = _compute_next(s, reference=now)
                dirty = True
                continue
            if s.next_run <= now:
                audit({"event": "schedule_fire", "id": s.id, "kind": s.kind, "goal": s.goal[:120]})
                try:
                    runner(s)
                finally:
                    s.last_run = now
                    s.next_run = _compute_next(s, reference=now)
                    if s.kind == "once":
                        s.enabled = False
                dirty = True
        if dirty:
            _save(schedules)
