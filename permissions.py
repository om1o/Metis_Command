"""
Permission gate at the tool-call boundary.

The composer's Read / Balanced / Full pill is no longer just a string we
inject into the system prompt — it's a real fence enforced where it
matters most: when a tool is about to run a write, a shell command, a
browser action, or a desktop click.

Tiers
-----
- ``read``     — every state-changing tool returns a permission_denied
                 result. Read-only tools (read_file, web_search,
                 screenshot, ...) pass through.
- ``balanced`` — state-changing tools call ``request_approval`` and
                 BLOCK until the user clicks Approve or Deny in the UI.
                 Default deny on timeout.
- ``full``     — pass-through, no prompts.

Cross-thread design
-------------------
Tool execution often happens in a worker thread (autonomous_loop runs
the manager's plan synchronously, sometimes through CrewAI which
spawns its own threads). The /chat HTTP handler runs as an SSE
generator in a different thread again. To make approvals work end-to
-end:

1. The /chat handler sets the active tier + an emit callback for the
   current mission via ``set_session()``. Both are stored in a
   process-wide dict keyed by a session id, so they're reachable from
   any thread the tool ends up in.
2. ``request_approval`` puts an ``approval_required`` event onto the
   session's emit queue and blocks on a threading.Event tied to the
   action id.
3. The /chat SSE generator drains the same emit queue and yields events
   to the browser as they appear.
4. The user clicks Approve / Deny → ``POST /actions/{id}/decision``
   → ``decide()`` sets the decision and fires the event.
5. The blocked tool wakes, reads the decision, runs (or returns
   denied), and the next tool step continues.

Default tier when no session has been registered is ``balanced`` so
ad-hoc test calls don't accidentally execute mutations without the
operator's knowledge.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Literal


Tier = Literal["read", "balanced", "full"]
DEFAULT_TIER: Tier = "balanced"

# Per-session config registered by /chat. Sessions don't strictly need
# unique ids — they're short-lived and the same session_id from the
# user's chat doubles as the key here. A None session falls back to
# whatever was last registered, which is fine for single-user dev.
_LOCK = threading.RLock()
_SESSIONS: dict[str, dict[str, Any]] = {}     # session_id -> {tier, emit}
_LAST_SESSION_ID: str | None = None
_DECISION_EVENTS: dict[str, threading.Event] = {}
_DECISIONS: dict[str, str] = {}               # action_id -> "approve" | "deny"
_PENDING: dict[str, dict[str, Any]] = {}      # action_id -> meta (for late decisions)

# Approval blocks for at most this long before we default-deny so the
# whole turn doesn't hang forever if the browser tab closes.
_APPROVAL_TIMEOUT_S = 120.0


def set_session(session_id: str, *, tier: Tier, emit: Callable[[dict], None]) -> None:
    """Register the active tier + event-emitter for a session."""
    global _LAST_SESSION_ID
    with _LOCK:
        _SESSIONS[session_id] = {"tier": tier, "emit": emit}
        _LAST_SESSION_ID = session_id


def clear_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def _resolve_session() -> tuple[Tier, Callable[[dict], None] | None]:
    """Find the most-likely-active session config. Falls back to the
    last-registered one when called from a worker thread that doesn't
    know its session id."""
    with _LOCK:
        sid = _LAST_SESSION_ID
        if not sid or sid not in _SESSIONS:
            return DEFAULT_TIER, None
        cfg = _SESSIONS[sid]
        return cfg.get("tier", DEFAULT_TIER), cfg.get("emit")


def current_tier() -> Tier:
    tier, _ = _resolve_session()
    return tier


def request_approval(*, tool: str, summary: str, args: dict | None = None) -> bool:
    """Ask the user to approve a state-changing tool call.

    Read tier: instant False. Full tier: instant True. Balanced tier:
    block until the user clicks Approve / Deny (or default-deny on
    timeout).
    """
    tier, emit = _resolve_session()
    if tier == "full":
        return True
    if tier == "read":
        return False

    aid = uuid.uuid4().hex[:12]
    ev = threading.Event()
    with _LOCK:
        _DECISION_EVENTS[aid] = ev
        _PENDING[aid] = {"tool": tool, "summary": summary, "args": args or {}, "ts": time.time()}

    if emit is not None:
        # IMPORTANT: emit BEFORE blocking. The SSE generator reads from
        # the same queue and won't see the event until we yield to it.
        try:
            emit({
                "type": "approval_required",
                "id": aid,
                "tool": tool,
                "summary": summary,
                "args": args or {},
            })
        except Exception:
            pass

    fired = ev.wait(timeout=_APPROVAL_TIMEOUT_S)
    with _LOCK:
        decision = _DECISIONS.pop(aid, None)
        _DECISION_EVENTS.pop(aid, None)
        _PENDING.pop(aid, None)

    if not fired:
        # Timeout — let the UI know the request expired in case the
        # card is still rendered.
        if emit is not None:
            try:
                emit({"type": "approval_expired", "id": aid, "tool": tool})
            except Exception:
                pass
        return False
    return decision == "approve"


def decide(action_id: str, choice: str) -> bool:
    """Called from the HTTP handler when the user clicks Approve/Deny."""
    if choice not in ("approve", "deny"):
        return False
    with _LOCK:
        ev = _DECISION_EVENTS.get(action_id)
        if not ev:
            return False
        _DECISIONS[action_id] = choice
    ev.set()
    return True


def pending_approvals() -> list[dict[str, Any]]:
    """Return pending human approvals for API/UI inspection."""
    with _LOCK:
        return [
            {"id": action_id, **meta}
            for action_id, meta in sorted(
                _PENDING.items(),
                key=lambda item: float(item[1].get("ts", 0) or 0),
            )
        ]


# ── Tool wrapper helper ──────────────────────────────────────────────
# Used by autonomous_loop to gate state-changing tools. Read-only tools
# (read_file, grep, web_search, screenshot, ...) skip the gate entirely.

_DENIED_RESULT = {
    "ok": False,
    "error": "permission_denied",
    "reason": "Director declined or current permission tier blocks this.",
}


def _short_str(v: Any, n: int = 80) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def gate(tool_name: str, fn: Callable[..., Any], *, summary_args: list[str] | None = None) -> Callable[..., Any]:
    """Wrap a tool callable so it consults the active tier before running.

    ``summary_args`` (optional) names the positional args we should put
    in the human-readable summary. Default: name + first arg only,
    truncated to 80 chars.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Build a short, readable summary the UI can show on the card.
        bits: list[str] = []
        if summary_args:
            for i, label in enumerate(summary_args):
                if i < len(args):
                    bits.append(f"{label}={_short_str(args[i])}")
                elif label in kwargs:
                    bits.append(f"{label}={_short_str(kwargs[label])}")
        elif args:
            bits.append(_short_str(args[0]))
        summary = f"{tool_name}({', '.join(bits)})" if bits else f"{tool_name}()"

        ok = request_approval(
            tool=tool_name,
            summary=summary,
            args={"args": [_short_str(a, 200) for a in args],
                  "kwargs": {k: _short_str(v, 200) for k, v in kwargs.items()}},
        )
        if not ok:
            return dict(_DENIED_RESULT, tool=tool_name, summary=summary)
        return fn(*args, **kwargs)

    wrapper.__name__ = f"gated_{tool_name}"
    wrapper.__qualname__ = f"gated_{tool_name}"
    return wrapper
