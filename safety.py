"""
Metis Safety Layer.

The single module every tool goes through before it does anything the user
could regret. Provides:

    - secret_scan(text)           catches API keys, bearer tokens, private keys
    - redact(text)                returns `text` with secrets replaced by [REDACTED]
    - confirm_gate(action, args)  blocks side-effects until approved
    - rate_limit(key, per_minute) simple token-bucket per tool
    - audit(event_dict)           append-only JSONL audit log at logs/audit.jsonl
    - is_path_safe(path, roots)   prevents path-traversal out of workspace

Every public tool in tools/ goes through at least `audit()` and, for any
side-effecting operation, either `confirm_gate()` or an explicit allowlist.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable


LOGS_DIR = Path("logs")
AUDIT_LOG = LOGS_DIR / "audit.jsonl"
CONFIRM_TOKEN_FILE = LOGS_DIR / "confirmed.jsonl"

# ── Secret detection ─────────────────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai",            re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("anthropic",         re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github",            re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("stripe",            re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("stripe_restricted", re.compile(r"rk_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("aws_access",        re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack",             re.compile(r"xox[abpos]-[A-Za-z0-9-]{10,}")),
    ("google_api",        re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("jwt",               re.compile(r"eyJ[A-Za-z0-9_-]+?\.eyJ[A-Za-z0-9_-]+?\.[A-Za-z0-9_-]+")),
    ("private_key_pem",   re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PGP) PRIVATE KEY-----")),
    ("bearer",            re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}")),
    ("password_kv",       re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]{6,})")),
]


def secret_scan(text: str) -> list[dict[str, str]]:
    """Return a list of hits describing any secrets found in `text`."""
    hits: list[dict[str, str]] = []
    if not text:
        return hits
    for kind, pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            hits.append({"kind": kind, "match": m.group(0)[:8] + "…"})
    return hits


def redact(text: str) -> str:
    """Return `text` with any detected secrets replaced by `[REDACTED:kind]`."""
    out = text or ""
    for kind, pat in _SECRET_PATTERNS:
        out = pat.sub(f"[REDACTED:{kind}]", out)
    return out


def ensure_no_secrets(text: str, *, where: str = "outgoing") -> None:
    """Raise PermissionError if `text` contains any secret. Use before sending to cloud APIs."""
    hits = secret_scan(text)
    if hits:
        audit({"event": "secret_blocked", "where": where, "kinds": [h["kind"] for h in hits]})
        raise PermissionError(
            f"Refused to send — detected {len(hits)} secret(s): "
            + ", ".join(h["kind"] for h in hits)
        )


# ── Path safety ──────────────────────────────────────────────────────────────

def is_path_safe(path: str | Path, *, roots: Iterable[str | Path] | None = None) -> bool:
    """
    Return True if `path` resolves inside one of the allowed `roots`.
    Default roots: the current working directory.
    """
    target = Path(path).resolve()
    allowed = [Path(r).resolve() for r in (roots or [Path.cwd()])]
    return any(str(target).startswith(str(root)) for root in allowed)


def require_safe_path(path: str | Path, *, roots: Iterable[str | Path] | None = None) -> Path:
    p = Path(path)
    if not is_path_safe(p, roots=roots):
        audit({"event": "path_blocked", "path": str(p)})
        raise PermissionError(f"Path escapes workspace: {p}")
    return p.resolve()


# ── Confirm gate ─────────────────────────────────────────────────────────────

class ConfirmRequired(Exception):
    """Raised when a destructive tool runs without an explicit confirm token."""


_pending_confirms: dict[str, dict[str, Any]] = {}
_pending_lock = threading.Lock()


def confirm_gate(action: str, args: dict[str, Any], *, token: str | None = None) -> str:
    """
    Destructive-tool gate.

    First call:  returns a short confirm_token and records {action, args, ts}.
    Second call: if `token` matches, the action is allowed.

    Usage inside a tool:
        token = confirm_gate("shell_run", {"cmd": cmd})
        raise ConfirmRequired(token)   # user reviews, passes token back
        # on retry with the matching token, just continue
    """
    if token:
        with _pending_lock:
            entry = _pending_confirms.pop(token, None)
        if not entry:
            audit({"event": "confirm_bad_token", "action": action})
            raise PermissionError("Confirm token invalid or expired.")
        if entry["action"] != action:
            audit({"event": "confirm_action_mismatch", "expected": entry["action"], "got": action})
            raise PermissionError("Confirm token/action mismatch.")
        audit({"event": "confirm_accepted", "action": action, "args": _redact_args(args)})
        return ""

    import secrets
    new_token = secrets.token_urlsafe(12)
    with _pending_lock:
        _pending_confirms[new_token] = {
            "action": action,
            "args": args,
            "created_at": time.time(),
        }
    audit({"event": "confirm_requested", "action": action, "token": new_token, "args": _redact_args(args)})
    return new_token


def _redact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Walk args and redact any suspicious strings so audit logs stay clean."""
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str):
            out[k] = redact(v)
        else:
            out[k] = v
    return out


# ── Rate limiting ────────────────────────────────────────────────────────────

_rl_lock = threading.Lock()
_rl_hits: dict[str, deque[float]] = {}


def rate_limit(key: str, *, per_minute: int = 30) -> bool:
    """Return True if under the limit; False if the caller should back off."""
    now = time.time()
    window = 60.0
    with _rl_lock:
        q = _rl_hits.setdefault(key, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= per_minute:
            audit({"event": "rate_limited", "key": key, "limit": per_minute})
            return False
        q.append(now)
    return True


# ── Audit log ────────────────────────────────────────────────────────────────

_audit_lock = threading.Lock()


def audit(event: dict[str, Any]) -> None:
    """Append a structured event to logs/audit.jsonl. Never raises."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        record = {"ts": int(time.time() * 1000), **event}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _audit_lock, AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tail_audit(n: int = 50) -> list[dict[str, Any]]:
    if not AUDIT_LOG.exists():
        return []
    lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-n:]
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


# ── Decorator helpers ────────────────────────────────────────────────────────

def audited(action: str) -> Callable:
    """Wrap any function so its calls land in the audit log."""
    def wrap(fn: Callable) -> Callable:
        def inner(*args, **kwargs):
            audit({"event": "tool_call", "action": action,
                   "args": _redact_args(kwargs), "arity": len(args)})
            try:
                result = fn(*args, **kwargs)
                audit({"event": "tool_ok", "action": action})
                return result
            except Exception as e:
                audit({"event": "tool_error", "action": action, "error": str(e)})
                raise
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return inner
    return wrap
