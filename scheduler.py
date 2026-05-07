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
EVENTS_FILE = PATHS.identity / "automation_events.jsonl"
_CHECK_INTERVAL = 30.0


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

    # Group 5 additions —
    name: str = ""              # human-readable label (defaults to a slice of goal)
    description: str = ""       # longer "why" the user wrote in the wizard
    agents_md: str = ""         # per-automation AGENTS.md the spawned subagent reads
    last_status: str = ""       # "ok" | "failed" | "" (never run)
    last_error: str = ""        # short failure note when last_status == failed
    run_count: int = 0          # total fires

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Persistence ──────────────────────────────────────────────────────────────

_lock = threading.Lock()


def _load() -> list[Schedule]:
    if not SCHEDULES_FILE.exists():
        return []
    try:
        rows = json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
        # Self-heal: drop unknown keys, default missing ones (for upgrades).
        out: list[Schedule] = []
        valid = {f.name for f in __import__("dataclasses").fields(Schedule)}
        for row in rows:
            filtered = {k: v for k, v in (row or {}).items() if k in valid}
            try:
                out.append(Schedule(**filtered))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _save(schedules: list[Schedule]) -> None:
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(
        json.dumps([s.to_dict() for s in schedules], indent=2),
        encoding="utf-8",
    )


def _append_event(event: dict[str, Any]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock("scheduler_events"):
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")


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
    name: str = "",
    description: str = "",
    agents_md: str = "",
) -> Schedule:
    sched = Schedule(
        kind=kind,
        spec=spec,
        goal=goal,
        action=action,
        project_slug=project_slug,
        auto_approve=auto_approve,
        name=name or (goal[:60].strip() or f"Automation @ {time.strftime('%H:%M')}"),
        description=description,
        agents_md=agents_md,
    )
    sched.next_run = _compute_next(sched, reference=time.time())
    with file_lock("scheduler"), _lock:
        schedules = _load()
        schedules.append(sched)
        _save(schedules)
    return sched


@audited("schedule.patch")
def patch(schedule_id: str, updates: dict) -> Schedule | None:
    """Partial update — only the keys provided are merged."""
    with file_lock("scheduler"), _lock:
        schedules = _load()
        for s in schedules:
            if s.id != schedule_id:
                continue
            for k in ("name", "description", "agents_md", "goal", "kind",
                      "spec", "auto_approve", "enabled"):
                if k in updates and updates[k] is not None:
                    setattr(s, k, updates[k])
            # Re-compute next_run if schedule shape changed.
            if any(k in updates for k in ("kind", "spec", "enabled")):
                s.next_run = _compute_next(s, reference=time.time()) if s.enabled else None
            _save(schedules)
            return s
    return None


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
                s.next_run = _compute_next(s, reference=time.time()) if s.enabled else None
                _save(schedules)
                return s.enabled
    return False


def list_schedules() -> list[Schedule]:
    with _lock:
        return _load()


def get_schedule(schedule_id: str) -> Schedule | None:
    with _lock:
        for schedule in _load():
            if schedule.id == schedule_id:
                return schedule
    return None


def list_events(limit: int = 100, schedule_id: str | None = None) -> list[dict[str, Any]]:
    if limit <= 0 or not EVENTS_FILE.exists():
        return []
    try:
        rows = EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(rows):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if schedule_id and row.get("schedule_id") != schedule_id:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _record_run(
    schedule_id: str,
    *,
    status: str,
    trigger: str,
    detail: str = "",
    error: str = "",
    finished_at: float | None = None,
    advance_schedule: bool = False,
) -> dict[str, Any] | None:
    finished_at = finished_at or time.time()
    with file_lock("scheduler"), _lock:
        schedules = _load()
        for schedule in schedules:
            if schedule.id != schedule_id:
                continue
            schedule.last_run = finished_at
            schedule.last_status = status
            schedule.last_error = error[:300]
            schedule.run_count = int(schedule.run_count or 0) + 1
            if advance_schedule:
                schedule.next_run = _compute_next(schedule, reference=finished_at)
                if schedule.kind == "once":
                    schedule.enabled = False
            _save(schedules)
            event = {
                "id": uuid.uuid4().hex[:12],
                "schedule_id": schedule.id,
                "schedule_name": schedule.name or (schedule.goal[:60].strip() or "Untitled automation"),
                "goal": schedule.goal,
                "action": schedule.action,
                "status": status,
                "trigger": trigger,
                "detail": detail[:500],
                "error": error[:300],
                "kind": schedule.kind,
                "spec": schedule.spec,
                "enabled": schedule.enabled,
                "run_count": schedule.run_count,
                "created_at": finished_at,
            }
            _append_event(event)
            return event
    return None


def _default_runner() -> Callable[[Schedule], dict[str, Any]]:
    def runner(s: Schedule) -> dict[str, Any]:
        def _notify_done(status: str, error: str = "") -> None:
            try:
                from notifier import notify as _n
                label = s.name or (s.goal or s.action)[:60]
                if status == "ok":
                    _n(
                        f"Automation done - {label}",
                        f"Schedule '{label}' just finished successfully.\n\n"
                        f"Goal: {s.goal or '(no goal)'}\n"
                        f"Schedule: {s.kind} {s.spec}",
                        urgency="low",
                    )
                else:
                    _n(
                        f"Automation FAILED - {label}",
                        f"Schedule '{label}' failed.\n\nError: {error}\n\n"
                        f"Goal: {s.goal or '(no goal)'}",
                        urgency="high",
                    )
            except Exception:
                pass

        if s.action:
            try:
                from daily_tasks import ACTIONS
                handler = ACTIONS.get(s.action)
                if not handler:
                    msg = f"unknown action: {s.action}"
                    audit({"event": "scheduler_unknown_action", "action": s.action, "schedule_id": s.id})
                    _notify_done("failed", error=msg)
                    return {"status": "failed", "error": msg}
                detail = handler()
                audit({
                    "event": "scheduler_action_ran",
                    "action": s.action,
                    "schedule_id": s.id,
                    "status": detail,
                })
                _notify_done("ok")
                return {"status": "ok", "detail": str(detail or f"action {s.action} ran")}
            except Exception as e:
                audit({
                    "event": "scheduler_action_failed",
                    "action": s.action,
                    "schedule_id": s.id,
                    "error": str(e),
                })
                _notify_done("failed", error=str(e)[:300])
                return {"status": "failed", "error": str(e)}

        try:
            from concurrency import submit_mission
            submit_mission(
                goal=s.goal,
                tag=f"scheduled:{s.id}",
                auto_approve=s.auto_approve,
                project_slug=s.project_slug,
            )
            _notify_done("ok")
            return {"status": "ok", "detail": "mission submitted"}
        except Exception as e:
            audit({"event": "scheduler_submit_failed", "schedule_id": s.id, "error": str(e)})
            _notify_done("failed", error=str(e)[:300])
            return {"status": "failed", "error": str(e)}

    return runner


def run_now(schedule_id: str, runner: Callable[[Schedule], dict[str, Any]] | None = None) -> dict[str, Any]:
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise KeyError(schedule_id)
    runner = runner or _default_runner()
    finished_at = time.time()
    try:
        result = runner(schedule) or {}
        status = result.get("status") or "ok"
        detail = result.get("detail") or ""
        error = result.get("error") or ""
    except Exception as e:
        status = "failed"
        detail = ""
        error = str(e)
    event = _record_run(
        schedule.id,
        status=status,
        trigger="manual",
        detail=detail,
        error=error,
        finished_at=finished_at,
        advance_schedule=False,
    )
    return {
        "ok": status == "ok",
        "status": status,
        "detail": detail,
        "error": error,
        "event": event,
        "schedule": get_schedule(schedule_id).to_dict() if get_schedule(schedule_id) else None,
    }


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


def start_scheduler(runner: Callable[[Schedule], dict[str, Any] | None] | None = None) -> None:
    """
    Start the background check loop. `runner` receives a Schedule when it's due.
    Default runner imports `concurrency.submit_mission` to run asynchronously.
    """
    global _thread
    if _thread and _thread.is_alive():
        return

    if runner is None:
        runner = _default_runner()

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


def _tick(runner: Callable[[Schedule], dict[str, Any] | None]) -> None:
    now = time.time()
    due: list[Schedule] = []
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
                due.append(s)
        if dirty:
            _save(schedules)

    for s in due:
        audit({"event": "schedule_fire", "id": s.id, "kind": s.kind, "goal": s.goal[:120]})
        try:
            result = runner(s) or {}
            status = result.get("status") or "ok"
            detail = result.get("detail") or ""
            error = result.get("error") or ""
        except Exception as e:
            status = "failed"
            detail = ""
            error = str(e)
        _record_run(
            s.id,
            status=status,
            trigger="schedule",
            detail=detail,
            error=error,
            finished_at=now,
            advance_schedule=True,
        )
