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
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterable


# ── Path roots + cross-process file lock + structured log ───────────────────
#
# Every module that reads or writes state should use PATHS.* so Metis behaves
# the same whether launched from the repo root, a desktop shortcut, or a tray
# icon.  `file_lock` is a cross-process advisory lock (msvcrt on Windows,
# fcntl elsewhere) used to protect JSON state files from torn writes when
# the UI and API bridge run as separate processes.

from types import SimpleNamespace as _NS  # noqa: E402
from contextlib import contextmanager     # noqa: E402

_ROOT = Path(__file__).resolve().parent
PATHS = _NS(
    root=_ROOT,
    logs=_ROOT / "logs",
    identity=_ROOT / "identity",
    artifacts=_ROOT / "artifacts",
    metis_db=_ROOT / "metis_db",
)
for _p in (PATHS.logs, PATHS.identity, PATHS.artifacts, PATHS.metis_db):
    try:
        _p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

LOGS_DIR = PATHS.logs
AUDIT_LOG = LOGS_DIR / "audit.jsonl"
CONFIRM_TOKEN_FILE = LOGS_DIR / "confirmed.jsonl"

_LOCK_DIR = PATHS.logs / "locks"
_LOCK_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def file_lock(key: str, *, timeout: float = 10.0):
    """
    Acquire a cross-process advisory lock keyed by `key`.

    Usage:
        with file_lock("wallet"):
            data = read()
            data["x"] += 1
            write(data)
    """
    import time as _t
    lock_path = _LOCK_DIR / f"{key}.lock"
    fh = open(lock_path, "a+")
    try:
        deadline = _t.time() + timeout
        acquired = False
        if os.name == "nt":
            import msvcrt
            while not acquired:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    if _t.time() > deadline:
                        _file_lock_audit("file_lock_timeout", key)
                        raise TimeoutError(f"file_lock({key}) timed out")
                    _t.sleep(0.05)
        else:
            import fcntl
            while not acquired:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if _t.time() > deadline:
                        _file_lock_audit("file_lock_timeout", key)
                        raise TimeoutError(f"file_lock({key}) timed out")
                    _t.sleep(0.05)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            fh.close()


def _file_lock_audit(event: str, key: str) -> None:
    """Deferred helper so file_lock can audit without referring to `audit`
    before it's defined in the import order."""
    try:
        audit({"event": event, "key": key})
    except Exception:
        pass


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
    Default roots: the current working directory and PATHS.root.  On this
    Windows machine the visible checkout can be a compatibility path while
    resolved child paths point at the canonical Projects_Local checkout.
    """
    raw_path = Path(path)
    if roots is None and not raw_path.is_absolute() and ".." not in raw_path.parts:
        return True
    target = raw_path.resolve()
    base_roots = list(roots) if roots is not None else [Path.cwd(), PATHS.root]
    allowed = [Path(r).resolve() for r in base_roots]
    return any(target == root or target.is_relative_to(root) for root in allowed)


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

# Confirm tokens stop being valid after this many seconds. Five minutes is
# generous enough for a human-in-the-loop reviewer but short enough that an
# accidentally-leaked token can't be used to authorize destructive ops hours
# later. Override with METIS_CONFIRM_TTL_S if needed.
CONFIRM_TTL_S = float(os.getenv("METIS_CONFIRM_TTL_S", "300"))


def _sweep_expired_confirms() -> int:
    """Drop expired confirm tokens. Returns how many were swept."""
    now = time.time()
    swept = 0
    with _pending_lock:
        expired = [
            tok for tok, entry in _pending_confirms.items()
            if now - float(entry.get("created_at", 0) or 0) > CONFIRM_TTL_S
        ]
        for tok in expired:
            entry = _pending_confirms.pop(tok, None)
            if entry:
                swept += 1
                try:
                    audit({"event": "confirm_token_expired",
                           "action": entry.get("action"),
                           "age_s": int(now - float(entry.get("created_at", 0) or 0))})
                except Exception:
                    pass
    return swept


def confirm_gate(action: str, args: dict[str, Any], *, token: str | None = None) -> str:
    """
    Destructive-tool gate.

    First call:  returns a short confirm_token and records {action, args, ts}.
    Second call: if `token` matches, the action is allowed.

    Tokens that haven't been redeemed within CONFIRM_TTL_S (default 5 min)
    are swept on every call so a leaked token can't authorize an op hours
    after it was issued.

    Usage inside a tool:
        token = confirm_gate("shell_run", {"cmd": cmd})
        raise ConfirmRequired(token)   # user reviews, passes token back
        # on retry with the matching token, just continue
    """
    # Always sweep first so this call sees a clean view.
    _sweep_expired_confirms()

    if token:
        with _pending_lock:
            entry = _pending_confirms.pop(token, None)
        if not entry:
            audit({"event": "confirm_bad_token", "action": action})
            raise PermissionError("Confirm token invalid or expired.")
        # Defense-in-depth — token+age check (sweep should have caught it).
        age = time.time() - float(entry.get("created_at", 0) or 0)
        if age > CONFIRM_TTL_S:
            audit({"event": "confirm_token_late", "action": action, "age_s": int(age)})
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
    audit({"event": "confirm_requested", "action": action, "token": new_token,
           "args": _redact_args(args), "ttl_s": int(CONFIRM_TTL_S)})
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
    """Append a structured event to logs/audit.jsonl. Never raises.

    If a trace is active (see tracing.start_trace), the trace_id is stamped
    on the record so events can be correlated across tool calls, agent
    handoffs, and bus messages.
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        record = {"ts": int(time.time() * 1000), **event}
        # Best-effort trace stamping — never fails the audit.
        try:
            from tracing import current_trace_id
            tid = current_trace_id()
            if tid and "trace_id" not in record:
                record["trace_id"] = tid
        except Exception:
            pass
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _audit_lock, AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log(event: str, **fields: Any) -> None:
    """Structured audit + optional stdout echo when METIS_VERBOSE=1.

    Preferred over bare `print(...)` calls in hot paths.  Silent by default,
    so existing UX doesn't change; opt-in visibility via env var.
    """
    audit({"event": event, **fields})
    if os.getenv("METIS_VERBOSE"):
        print(f"[{event}] " + " ".join(f"{k}={v!r}" for k, v in fields.items()))


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
        @wraps(fn)
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
        return inner
    return wrap
