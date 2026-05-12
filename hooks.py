"""
Hooks — Claude Code style lifecycle callbacks.

Register Python callables to fire on named events:
    pre_tool           before any tool invocation (can block by raising)
    post_tool          after success
    tool_error         after failure
    pre_mission        before autonomous_loop starts
    post_mission       after autonomous_loop finishes
    chat_turn          after every chat turn persists
    confirm_requested  when a destructive tool asks for confirmation

Hooks can also be declared in `hooks.json` at the repo root:
    [{"event": "post_tool", "command": "python scripts/notify.py"}]
Command strings are executed through the allowlisted shell runner.

Errors inside a hook never kill the caller — they're audited and swallowed.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from safety import audit


HOOKS_CONFIG = Path("hooks.json")


@dataclass
class Hook:
    event: str
    callback: Callable[[dict[str, Any]], None] | None = None
    command: str | None = None  # shell command (runs via tools.shell.run_trusted)
    name: str = ""

    def fire(self, payload: dict[str, Any]) -> None:
        try:
            if self.callback is not None:
                self.callback(payload)
            elif self.command:
                from tools.shell import run_trusted, ShellBlocked
                try:
                    run_trusted(self.command, timeout=20)
                except ShellBlocked as e:
                    audit({"event": "hook_blocked", "name": self.name, "error": str(e)})
        except Exception as e:
            audit({"event": "hook_error", "name": self.name or self.event, "error": str(e)})


_lock = threading.Lock()
_hooks: dict[str, list[Hook]] = {}
_loaded_config = False


def register(event: str, callback: Callable[[dict[str, Any]], None], *, name: str = "") -> None:
    """Register a Python callback for `event`."""
    with _lock:
        _hooks.setdefault(event, []).append(
            Hook(event=event, callback=callback, name=name or callback.__name__)
        )


def unregister_all(event: str | None = None) -> None:
    with _lock:
        if event is None:
            _hooks.clear()
        else:
            _hooks.pop(event, None)


def fire(event: str, payload: dict[str, Any] | None = None) -> None:
    """Trigger all hooks registered for `event`. Never raises."""
    _ensure_config_loaded()
    payload = payload or {}
    payload = {"event": event, **payload}
    with _lock:
        handlers = list(_hooks.get(event, []))
    for hook in handlers:
        hook.fire(payload)


def list_hooks() -> dict[str, list[dict[str, str]]]:
    _ensure_config_loaded()
    with _lock:
        return {
            event: [
                {"name": h.name, "kind": "callback" if h.callback else "command",
                 "command": h.command or ""}
                for h in hooks
            ]
            for event, hooks in _hooks.items()
        }


# ── Config file loading ─────────────────────────────────────────────────────

def _ensure_config_loaded() -> None:
    global _loaded_config
    if _loaded_config:
        return
    with _lock:
        if _loaded_config:
            return
        _loaded_config = True
    if not HOOKS_CONFIG.exists():
        return
    try:
        rows = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        audit({"event": "hooks_config_invalid", "error": str(e)})
        return
    for row in rows or []:
        event = row.get("event")
        command = row.get("command")
        name = row.get("name") or (command or event)
        if not event or not command:
            continue
        with _lock:
            _hooks.setdefault(event, []).append(
                Hook(event=event, command=command, name=name)
            )
        audit({"event": "hook_loaded", "from": "hooks.json", "hook_event": event, "name": name})
