"""
Distributed tracing — correlate tool calls, agent handoffs, and bus messages.

Usage:
    from tracing import start_trace, current_trace_id

    with start_trace(label="chat_turn"):
        run_tool(...)        # tool_runtime tags events with trace_id
        publish_msg(...)     # agent_bus uses trace_id as correlation_id
        # any safety.audit() call also picks it up automatically

Public API:
    start_trace(label=None) -> context manager yielding trace_id
    current_trace_id()      -> str | None — current active trace, if any
    new_trace_id()          -> str        — fresh id without binding context
"""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from typing import Iterator


# Single contextvar — survives across asyncio tasks and threads (per-thread default).
_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "metis_trace_id", default=None
)
_trace_label_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "metis_trace_label", default=None
)


def new_trace_id() -> str:
    """Return a fresh 12-char hex trace id without binding context."""
    return uuid.uuid4().hex[:12]


def current_trace_id() -> str | None:
    """Return the currently bound trace id (or None if outside a trace)."""
    return _trace_id_var.get()


def current_trace_label() -> str | None:
    """Return the human-readable label for the current trace (if any)."""
    return _trace_label_var.get()


@contextmanager
def start_trace(label: str | None = None, *, trace_id: str | None = None) -> Iterator[str]:
    """
    Bind a trace_id to the current context for the duration of the with-block.

    If `trace_id` is provided we adopt it (useful for inheriting one across
    process or RPC boundaries). Otherwise we mint a fresh one.
    """
    tid = (trace_id or new_trace_id()).strip()
    token_id = _trace_id_var.set(tid)
    token_label = _trace_label_var.set(label or "")
    try:
        yield tid
    finally:
        _trace_id_var.reset(token_id)
        _trace_label_var.reset(token_label)


def attach_trace(payload: dict) -> dict:
    """
    Stamp a payload dict with the current trace_id (if any).

    Returns the same dict for chaining. Safe to call when no trace is active.
    """
    tid = current_trace_id()
    if tid and "trace_id" not in payload:
        payload["trace_id"] = tid
    return payload
