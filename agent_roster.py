"""
Agent Roster — data-driven registry of the swarm's specialist subagents.

Lives on disk at `identity/roster.json`.  Every entry describes a named
subagent (slug, role, system prompt, wallet category, default tags).
`list_roster()` loads the JSON, seeding the canonical default roster if the
file is missing.  `spawn_persistent()` starts a long-running inbox-watching
worker backed by `agent_bus` so the agent keeps responding until stopped.

Rationale for this split: `subagents.spawn` handles one-shot invocations;
everything here is about persistent, nameable agents that can be summoned
into conversations, schedules, and daily briefings.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROSTER_FILE = Path("identity") / "roster.json"
PERSISTENT_FILE = Path("identity") / "persistent_agents.json"
HEALTH_FILE = Path("identity") / "agent_health.json"

# Heartbeat windows (seconds) used by get_agent_health() to colorize status.
HEARTBEAT_FRESH_S = 60     # 🟢 healthy
HEARTBEAT_STALE_S = 300    # 🟡 lagging beyond this; 🔴 if older still
HEARTBEAT_WRITE_INTERVAL_S = 15  # min seconds between heartbeat writes per agent


# ── Default roster ──────────────────────────────────────────────────────────

_DEFAULT_ROSTER: list[dict[str, Any]] = [
    {
        "slug": "scheduler",
        "name": "Scheduler",
        "role": "manager",
        "system": "You manage the Director's calendar. Receive events and "
                  "produce time-boxed plans. Flag conflicts, propose moves.",
        "wallet_category": None,
        "tags": ["planning", "calendar"],
    },
    {
        "slug": "inbox_triage",
        "name": "Inbox Triage",
        "role": "scholar",
        "system": "You read batches of emails/messages and return a triaged "
                  "list: urgent / reply-today / FYI / delete. Extract "
                  "action items and suggested replies.",
        "wallet_category": None,
        "tags": ["email", "ops"],
    },
    {
        "slug": "news_digest",
        "name": "News Digest",
        "role": "researcher",
        "system": "You pull the day's most important headlines relevant to "
                  "the Director's tags (tech, markets, geopolitics). "
                  "Return 5-8 bullets with source URLs.",
        "wallet_category": "cloud_api",
        "tags": ["news", "research"],
    },
    {
        "slug": "shopper",
        "name": "Shopper",
        "role": "manager",
        "system": "You find and recommend products the Director needs. "
                  "Never purchase above the wallet's plugin cap without "
                  "explicit approval. Always show price, source, and "
                  "alternative options.",
        "wallet_category": "plugin",
        "tags": ["commerce"],
    },
    {
        "slug": "finance_watch",
        "name": "Finance Watch",
        "role": "thinker",
        "system": "You monitor the Director's watchlist and wallet. Flag "
                  "unusual spend, opportunities, and budget drift. Present "
                  "numbers, then interpretation.",
        "wallet_category": None,
        "tags": ["finance", "risk"],
    },
    {
        "slug": "fitness_coach",
        "name": "Fitness Coach",
        "role": "scholar",
        "system": "You track fitness goals and nudge the Director. Tailor "
                  "plans to declared constraints (time, injuries, gear).",
        "wallet_category": None,
        "tags": ["health"],
    },
    {
        "slug": "calendar_planner",
        "name": "Calendar Planner",
        "role": "thinker",
        "system": "You take today's meetings, tasks, and priorities and "
                  "produce a time-boxed schedule.  Mark focus blocks and "
                  "buffer zones.",
        "wallet_category": None,
        "tags": ["planning"],
    },
    {
        "slug": "home_automation",
        "name": "Home Automation",
        "role": "manager",
        "system": "You coordinate smart-home skills. Never run destructive "
                  "actions (lock changes, door openings) without explicit "
                  "confirmation.",
        "wallet_category": None,
        "tags": ["home", "iot"],
    },
    {
        "slug": "code_reviewer",
        "name": "Code Reviewer",
        "role": "coder",
        "system": "You review diffs for correctness, style, and safety. "
                  "Return a ranked list of issues with file:line citations.",
        "wallet_category": None,
        "tags": ["eng"],
    },
    {
        "slug": "security_auditor",
        "name": "Security Auditor",
        "role": "thinker",
        "system": "You audit Metis artifacts for secrets, unsafe shell calls, "
                  "and over-broad permissions.  Return findings with severity.",
        "wallet_category": None,
        "tags": ["security"],
    },
    {
        "slug": "designer",
        "name": "Designer",
        "role": "scholar",
        "system": "You produce UX and visual design recommendations with "
                  "rationale. When asked for mockups, describe them "
                  "precisely enough to hand to an image model.",
        "wallet_category": None,
        "tags": ["design"],
    },
    {
        "slug": "travel_agent",
        "name": "Travel Agent",
        "role": "researcher",
        "system": "You plan travel: flights, hotels, ground transport, "
                  "visa/entry requirements.  Respect budget and comfort "
                  "constraints.  Never purchase without approval.",
        "wallet_category": "plugin",
        "tags": ["travel"],
    },
]


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class AgentSpec:
    slug: str
    name: str = ""
    role: str = "manager"
    system: str = ""
    wallet_category: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Persistence ─────────────────────────────────────────────────────────────

_lock = threading.Lock()


def list_roster() -> list[AgentSpec]:
    ROSTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ROSTER_FILE.exists():
        ROSTER_FILE.write_text(json.dumps(_DEFAULT_ROSTER, indent=2), encoding="utf-8")
    try:
        raw = json.loads(ROSTER_FILE.read_text(encoding="utf-8"))
    except Exception:
        raw = list(_DEFAULT_ROSTER)
    out: list[AgentSpec] = []
    for row in raw:
        try:
            out.append(AgentSpec(**row))
        except Exception:
            continue
    return out


def get(slug: str) -> AgentSpec | None:
    for spec in list_roster():
        if spec.slug == slug:
            return spec
    return None


def upsert(spec: AgentSpec | dict[str, Any]) -> AgentSpec:
    if isinstance(spec, dict):
        spec = AgentSpec(**spec)
    with _lock:
        rows = [s.to_dict() for s in list_roster() if s.slug != spec.slug]
        rows.append(spec.to_dict())
        ROSTER_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return spec


def delete(slug: str) -> bool:
    with _lock:
        before = list_roster()
        after = [s.to_dict() for s in before if s.slug != slug]
        if len(after) == len(before):
            return False
        ROSTER_FILE.write_text(json.dumps(after, indent=2), encoding="utf-8")
    return True


# ── Persistent agent workers (bus-driven) ───────────────────────────────────

_WORKERS: dict[str, "_WorkerHandle"] = {}


@dataclass
class _WorkerHandle:
    slug: str
    thread: threading.Thread
    stop_event: threading.Event

    def stop(self) -> None:
        self.stop_event.set()


def _load_persistent() -> list[str]:
    if not PERSISTENT_FILE.exists():
        return []
    try:
        return [str(s) for s in json.loads(PERSISTENT_FILE.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _save_persistent(slugs: list[str]) -> None:
    PERSISTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERSISTENT_FILE.write_text(
        json.dumps(sorted(set(slugs)), indent=2),
        encoding="utf-8",
    )


# ── Heartbeat tracking ─────────────────────────────────────────────────────
_health_lock = threading.Lock()


def _read_health() -> dict[str, dict[str, Any]]:
    if not HEALTH_FILE.exists():
        return {}
    try:
        data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_health(data: dict[str, dict[str, Any]]) -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def heartbeat(slug: str, *, status: str = "alive", error: str | None = None) -> None:
    """Record a heartbeat for `slug` (called from the agent loop)."""
    now = time.time()
    with _health_lock:
        data = _read_health()
        prev = data.get(slug, {})
        # Throttle writes — agents tick fast, but disk doesn't need to.
        last_write = float(prev.get("last_heartbeat_at", 0) or 0)
        if status == "alive" and now - last_write < HEARTBEAT_WRITE_INTERVAL_S:
            return
        entry: dict[str, Any] = {
            "slug": slug,
            "last_heartbeat_at": now,
            "status": status,
            "messages_handled": int(prev.get("messages_handled", 0) or 0),
        }
        if error:
            entry["last_error"] = error[:240]
            entry["last_error_at"] = now
        if status == "handled":
            entry["messages_handled"] = int(prev.get("messages_handled", 0) or 0) + 1
        data[slug] = {**prev, **entry}
        _write_health(data)


def get_agent_health() -> list[dict[str, Any]]:
    """Return a list of {slug, status_color, last_heartbeat_at, age_s, ...}.

    status_color is one of 🟢 (healthy), 🟡 (lagging), 🔴 (stale or dead).
    Only agents that the user has marked persistent are surfaced.
    """
    now = time.time()
    persistent_set = set(list_persistent())
    data = _read_health()
    out: list[dict[str, Any]] = []
    for slug in sorted(persistent_set):
        entry = data.get(slug, {})
        last = float(entry.get("last_heartbeat_at", 0) or 0)
        age = now - last if last else None
        if age is None:
            color = "🔴"
            label = "never"
        elif age < HEARTBEAT_FRESH_S:
            color = "🟢"
            label = f"{int(age)}s ago"
        elif age < HEARTBEAT_STALE_S:
            color = "🟡"
            label = f"{int(age)}s ago"
        else:
            color = "🔴"
            label = f"{int(age)}s ago"
        out.append({
            "slug": slug,
            "status_color": color,
            "label": label,
            "last_heartbeat_at": last or None,
            "age_s": age,
            "messages_handled": entry.get("messages_handled", 0),
            "last_error": entry.get("last_error"),
            "alive_thread": slug in _WORKERS and _WORKERS[slug].thread.is_alive(),
        })
    return out


def _run_agent_loop(spec: AgentSpec, stop_event: threading.Event) -> None:
    """
    Pull messages off the agent's inbox, consult the active Brain for long-
    term context, call the agent's LLM, publish the reply, and (episodic)
    remember the exchange so the next caller sees continuity.
    """
    import agent_bus as _bus
    from brain_engine import chat_by_role

    try:
        from memory_loop import inject_context as _inject_context
    except Exception:
        _inject_context = None  # type: ignore[assignment]
    try:
        import brains as _brains
    except Exception:
        _brains = None  # type: ignore[assignment]

    inbox = _bus.inbox(spec.slug)
    session_id = f"agent:{spec.slug}"

    # Initial heartbeat so the dashboard immediately sees the agent alive.
    try:
        heartbeat(spec.slug, status="started")
    except Exception:
        pass

    while not stop_event.is_set():
        try:
            msg = inbox.get(timeout=1.0)
        except Exception:
            # Idle tick — refresh heartbeat so the dashboard knows we're alive
            # even if no messages have arrived.
            try:
                heartbeat(spec.slug, status="alive")
            except Exception:
                pass
            continue
        try:
            system = spec.system or "You are a Metis specialist agent."
            # Ground every reply in the active Brain + recent session history.
            active_slug = None
            context: list[dict] = []
            if _brains is not None:
                try:
                    b = _brains.active()
                    active_slug = b.slug if b else None
                except Exception:
                    active_slug = None
            if _inject_context is not None:
                try:
                    probe = json.dumps(msg.payload, ensure_ascii=False)[:800]
                    context = _inject_context(
                        session_id=session_id,
                        user_prompt=probe,
                        brain=active_slug,
                    ) or []
                except Exception:
                    context = []

            user = (
                f"From: {msg.from_slug}\n"
                f"Kind: {msg.kind}\n"
                f"Payload: {json.dumps(msg.payload, ensure_ascii=False)[:4000]}"
            )
            messages = [
                {"role": "system", "content": system},
                *context,
                {"role": "user", "content": user},
            ]
            reply = chat_by_role(spec.role, messages) or ""

            # Remember the exchange so future messages have continuity.
            if _brains is not None and active_slug:
                try:
                    _brains.remember(
                        f"[{spec.slug}] answered {msg.from_slug}: {reply[:400]}",
                        kind="episodic",
                        brain=active_slug,
                        tags=("agent", spec.slug),
                    )
                except Exception:
                    pass

            _bus.publish(_bus.AgentMessage(
                from_slug=spec.slug,
                to_slug=msg.from_slug,
                channel=msg.channel,
                kind="reply",
                payload={"text": reply, "re": msg.kind},
                correlation_id=msg.correlation_id,
            ))
            try:
                heartbeat(spec.slug, status="handled")
            except Exception:
                pass
        except Exception as e:
            try:
                import safety
                safety.audit({"event": "agent_worker_error",
                              "slug": spec.slug, "error": str(e)})
            except Exception:
                pass
            try:
                heartbeat(spec.slug, status="error", error=str(e))
            except Exception:
                pass


def spawn_persistent(slug: str) -> bool:
    """Start a long-running worker for `slug`. Safe to call multiple times."""
    spec = get(slug)
    if spec is None:
        return False
    if slug in _WORKERS and _WORKERS[slug].thread.is_alive():
        return True
    stop = threading.Event()
    t = threading.Thread(
        target=_run_agent_loop,
        args=(spec, stop),
        daemon=True,
        name=f"MetisAgent:{slug}",
    )
    t.start()
    _WORKERS[slug] = _WorkerHandle(slug=slug, thread=t, stop_event=stop)
    slugs = _load_persistent()
    if slug not in slugs:
        slugs.append(slug)
        _save_persistent(slugs)
    try:
        from safety import audit
        audit({"event": "agent_persistent_start", "slug": slug})
    except Exception:
        pass
    return True


def stop_persistent(slug: str) -> bool:
    h = _WORKERS.pop(slug, None)
    if h is None:
        return False
    h.stop()
    slugs = [s for s in _load_persistent() if s != slug]
    _save_persistent(slugs)
    try:
        from safety import audit
        audit({"event": "agent_persistent_stop", "slug": slug})
    except Exception:
        pass
    return True


def list_persistent() -> list[str]:
    live = [s for s, h in _WORKERS.items() if h.thread.is_alive()]
    # Merge disk list so UI can offer "resume" after restart.
    return sorted(set(live) | set(_load_persistent()))


def resume_persistent_from_disk() -> list[str]:
    """Called once on boot to re-spawn persistent agents from the last run."""
    started: list[str] = []
    for slug in _load_persistent():
        if spawn_persistent(slug):
            started.append(slug)
    return started
