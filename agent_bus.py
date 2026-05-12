"""
Agent Bus — an explicit, observable message channel between agents.

Replaces implicit CrewAI delegation with a thread-safe publish / inbox
model so specialists can talk to each other (and the Orchestrator) without
being hard-wired through a single manager.  Every message is audit-logged
via safety.audit for replay and forensics.

Concepts:
    channel   — named broadcast bucket (e.g. "morning_briefing", "alerts")
    inbox     — one per agent slug; direct messages land here
    AgentMessage(from_slug, to_slug|channel, kind, payload, correlation_id)

Public API:
    publish(message)                           -> None
    inbox(slug)                                -> queue.Queue[AgentMessage]
    subscribe(channel, slug)                   -> None
    unsubscribe(channel, slug)                 -> None
    drain(slug, limit=100)                     -> list[AgentMessage]
    conversation(goal, participants, ...)      -> ConversationResult
    history(channel=None, limit=50)            -> list[dict]

Built-in channels constants: MORNING_BRIEFING, ALERTS, HANDOFF, APPROVALS.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


# Built-in channel identifiers
MORNING_BRIEFING = "morning_briefing"
ALERTS = "alerts"
HANDOFF = "handoff"
APPROVALS = "approvals"
BUILTIN_CHANNELS: tuple[str, ...] = (MORNING_BRIEFING, ALERTS, HANDOFF, APPROVALS)

BUS_LOG = Path("logs") / "agent_bus.jsonl"


# ── Data ─────────────────────────────────────────────────────────────────────

def _default_correlation_id() -> str:
    """Use the active trace_id if one is bound, else mint a fresh id."""
    try:
        from tracing import current_trace_id
        tid = current_trace_id()
        if tid:
            return tid
    except Exception:
        pass
    return uuid.uuid4().hex[:10]


@dataclass
class AgentMessage:
    from_slug: str = "orchestrator"
    to_slug: str | None = None
    channel: str | None = None
    kind: str = "message"                     # free-form: prompt, reply, done, ask, alert…
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=_default_correlation_id)
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PublishResult:
    """What happened when a message was published.

    `delivered` lists slugs whose inbox accepted the message.
    `dropped` lists slugs whose inbox was full (or otherwise refused it).
    """
    delivered: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    targets: int = 0

    @property
    def ok(self) -> bool:
        return not self.dropped and self.targets > 0


@dataclass
class ConversationResult:
    goal: str
    participants: list[str]
    transcript: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    rounds: int = 0
    duration_ms: int = 0


# ── State ───────────────────────────────────────────────────────────────────

_lock = threading.RLock()
_inboxes: dict[str, queue.Queue] = {}
_subscriptions: dict[str, set[str]] = {c: set() for c in BUILTIN_CHANNELS}


def _ensure_channel(channel: str) -> None:
    with _lock:
        _subscriptions.setdefault(channel, set())


# ── Public primitives ───────────────────────────────────────────────────────

def inbox(slug: str) -> queue.Queue:
    """Return (and create) the inbox queue for `slug`."""
    with _lock:
        q = _inboxes.get(slug)
        if q is None:
            q = queue.Queue(maxsize=1000)
            _inboxes[slug] = q
        return q


def subscribe(channel: str, slug: str) -> None:
    _ensure_channel(channel)
    with _lock:
        _subscriptions[channel].add(slug)


def unsubscribe(channel: str, slug: str) -> None:
    with _lock:
        _subscriptions.get(channel, set()).discard(slug)


def subscribers(channel: str) -> list[str]:
    with _lock:
        return sorted(_subscriptions.get(channel, set()))


def publish(message: AgentMessage) -> PublishResult:
    """Deliver `message` to the target inbox(es) and persist to bus log.

    Returns a PublishResult describing which targets accepted vs dropped
    the message. On backpressure (inbox full) we explicitly audit the drop
    so the failure isn't silent.
    """
    if not isinstance(message, AgentMessage):
        raise TypeError("publish() expects an AgentMessage")
    targets: list[str] = []
    if message.to_slug:
        targets.append(message.to_slug)
    if message.channel:
        _ensure_channel(message.channel)
        with _lock:
            targets.extend(_subscriptions.get(message.channel, set()))
    targets = sorted(set(targets))
    result = PublishResult(targets=len(targets))
    if not targets:
        _persist(message, note="no-targets")
        return result
    for slug in targets:
        try:
            inbox(slug).put_nowait(message)
            result.delivered.append(slug)
        except queue.Full:
            result.dropped.append(slug)
            _persist(message, note=f"inbox-full:{slug}")
            try:
                from safety import audit
                audit({
                    "event": "bus_backpressure_drop",
                    "from": message.from_slug,
                    "to": slug,
                    "channel": message.channel,
                    "kind": message.kind,
                    "cid": message.correlation_id,
                })
            except Exception:
                pass
            continue
    _persist(message)
    try:
        from safety import audit
        audit({
            "event": "bus_publish",
            "from": message.from_slug,
            "to": message.to_slug,
            "channel": message.channel,
            "kind": message.kind,
            "cid": message.correlation_id,
            "delivered": result.delivered,
            "dropped": result.dropped,
        })
    except Exception:
        pass
    return result


def drain(slug: str, limit: int = 100, timeout: float = 0.0) -> list[AgentMessage]:
    """Pull up to `limit` messages off `slug`'s inbox without blocking (or briefly)."""
    q = inbox(slug)
    out: list[AgentMessage] = []
    deadline = time.time() + max(0.0, timeout)
    while len(out) < limit:
        try:
            if timeout <= 0:
                out.append(q.get_nowait())
            else:
                remaining = max(0.0, deadline - time.time())
                out.append(q.get(timeout=remaining or 0.05))
        except Exception:
            break
    return out


def history(channel: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not BUS_LOG.exists():
        return []
    lines = BUS_LOG.read_text(encoding="utf-8").splitlines()[-5000:]
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            row = json.loads(ln)
        except Exception:
            continue
        if channel and row.get("channel") != channel:
            continue
        out.append(row)
    return out[-limit:]


# ── Multi-agent conversation driver ─────────────────────────────────────────

def conversation(
    goal: str,
    participants: Iterable[str],
    *,
    max_rounds: int = 4,
    channel: str = HANDOFF,
    opener: str = "orchestrator",
) -> ConversationResult:
    """
    Round-robin conversation: we publish the goal to `participants` on
    `channel`, collect their direct replies (each publishes back to the
    opener's inbox), and collate the outputs.  Agents that publish
    `kind="done"` short-circuit the loop with their answer.

    Returns a ConversationResult with transcript, final_answer, and timing.
    This is synchronous but relies on persistent agents (started via
    `agent_roster.spawn_persistent`) to reply; missing agents just time out.
    """
    participants = [p for p in participants if p]
    result = ConversationResult(goal=goal, participants=list(participants))
    started = time.time()
    cid = uuid.uuid4().hex[:10]

    # Clear the opener's inbox of stale traffic.
    _ = drain(opener, limit=10_000)

    for rnd in range(1, max_rounds + 1):
        result.rounds = rnd
        # Broadcast to each participant with the evolving transcript.
        transcript_text = "\n".join(
            f"- {t.get('from')}: {str(t.get('payload', {}).get('text',''))[:400]}"
            for t in result.transcript[-8:]
        )
        for slug in participants:
            publish(AgentMessage(
                from_slug=opener,
                to_slug=slug,
                channel=channel,
                kind="prompt",
                payload={
                    "goal": goal,
                    "round": rnd,
                    "transcript": transcript_text,
                    "instructions": "Reply via the bus with kind='reply' or kind='done'.",
                },
                correlation_id=cid,
            ))

        # Collect replies (best-effort wait up to 30s per round).
        deadline = time.time() + 30.0
        seen: dict[str, AgentMessage] = {}
        done_answer: str | None = None
        while time.time() < deadline and len(seen) < len(participants):
            msgs = drain(opener, limit=20, timeout=0.5)
            for m in msgs:
                if m.correlation_id != cid:
                    continue
                if m.from_slug in participants and m.from_slug not in seen:
                    seen[m.from_slug] = m
                    result.transcript.append(m.to_dict())
                    if m.kind == "done":
                        done_answer = str(m.payload.get("text") or m.payload.get("answer") or "")
                        break
            if done_answer:
                break

        if done_answer:
            result.final_answer = done_answer
            break

        # If no one answered this round, give up.
        if not seen:
            break

    result.duration_ms = int((time.time() - started) * 1000)
    if not result.final_answer and result.transcript:
        # Synthesize a lightweight summary from the last replies.
        pieces = [
            str(t.get("payload", {}).get("text", ""))[:400]
            for t in result.transcript[-len(participants):]
        ]
        result.final_answer = "\n\n".join(p for p in pieces if p)

    try:
        from safety import audit
        audit({
            "event": "bus_conversation",
            "goal": goal[:160],
            "participants": list(participants),
            "rounds": result.rounds,
            "duration_ms": result.duration_ms,
        })
    except Exception:
        pass
    return result


# ── Persistence ─────────────────────────────────────────────────────────────

def _persist(message: AgentMessage, *, note: str = "") -> None:
    try:
        BUS_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = message.to_dict()
        if note:
            row["_note"] = note
        with BUS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
