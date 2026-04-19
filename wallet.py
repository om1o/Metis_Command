"""
Orchestrator Wallet — budget, policies, and ledger for autonomous spend.

Gives the Orchestrator a real "card" the swarm can use to spend on cloud API
calls, plugin purchases, and subagent summons.  By default it is a SIMULATED
budget (no real money moves anywhere) with policy-gated charges and a
monthly cap.  Flipping `WALLET_MODE=stripe_issuing` + setting
`STRIPE_ISSUING_KEY` routes charges through the (thin) Stripe Issuing adapter
in `providers/stripe_issuing.py`.

Data model:
    Wallet    — single persistent document (identity/wallet.json)
    Policy    — per-category allow/deny rule
    Ledger    — append-only JSONL at logs/wallet.jsonl

Public API (stable):
    get_wallet() -> Wallet
    balance_cents() -> int
    top_up(cents, source="manual") -> int
    charge(category, cents, memo="", *, subject=None) -> LedgerEntry
    try_charge(...) -> LedgerEntry | None            (never raises)
    can_spend(category, cents) -> (bool, reason)
    set_cap(monthly_cap_cents) -> None
    set_mode(mode) -> None
    add_policy(policy) / remove_policy(policy_id) / list_policies()
    ledger(limit=50, category=None) -> list[dict]
    monthly_spent(category=None) -> int
    summary() -> dict
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WALLET_FILE = Path("identity") / "wallet.json"
LEDGER_LOG = Path("logs") / "wallet.jsonl"

# Categories the Orchestrator is allowed to charge against.
CATEGORIES = ("cloud_api", "plugin", "subagent", "compute", "data", "other")

_DEFAULT_CAP_CENTS = int(os.getenv("METIS_WALLET_CAP_CENTS", "10000") or "10000")
_DEFAULT_MODE = os.getenv("METIS_WALLET_MODE", "simulated").strip() or "simulated"


# ── Errors ───────────────────────────────────────────────────────────────────

class BudgetExceeded(Exception):
    """Raised by `charge()` when a policy denies the spend."""


class ConfirmRequired(Exception):
    """Raised when a category requires human approval above a threshold."""


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Policy:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    category: str = "other"                   # one of CATEGORIES or "*"
    max_per_day_cents: int | None = None
    max_per_charge_cents: int | None = None
    require_approval_above_cents: int | None = None
    deny: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Wallet:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = "Orchestrator Wallet"
    balance_cents: int = 0
    monthly_cap_cents: int = _DEFAULT_CAP_CENTS
    monthly_spent_cents: int = 0
    month_key: str = ""                      # YYYY-MM of the current period
    mode: str = _DEFAULT_MODE                # "simulated" | "stripe_issuing"
    policies: list[Policy] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["policies"] = [p if isinstance(p, dict) else p.to_dict() for p in self.policies]
        return d


@dataclass
class LedgerEntry:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    ts: float = field(default_factory=time.time)
    kind: str = "charge"                     # "charge" | "topup" | "refund" | "deny"
    category: str = "other"
    cents: int = 0                           # positive for debits, negative for credits
    memo: str = ""
    subject: str = ""                        # model, plugin slug, subagent type…
    balance_after_cents: int = 0
    approved_by: str | None = None
    policy_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Persistence ─────────────────────────────────────────────────────────────

_lock = threading.Lock()


def _load() -> Wallet:
    if not WALLET_FILE.exists():
        w = Wallet()
        _save(w)
        return w
    try:
        raw = json.loads(WALLET_FILE.read_text(encoding="utf-8"))
        policies = [Policy(**p) for p in raw.pop("policies", []) if isinstance(p, dict)]
        w = Wallet(**raw)
        w.policies = policies
        return w
    except Exception:
        w = Wallet()
        _save(w)
        return w


def _save(w: Wallet) -> None:
    WALLET_FILE.parent.mkdir(parents=True, exist_ok=True)
    w.updated_at = time.time()
    WALLET_FILE.write_text(json.dumps(w.to_dict(), indent=2), encoding="utf-8")


def _persist_ledger(entry: LedgerEntry) -> None:
    try:
        LEDGER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass


def _current_month_key() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m")


def _roll_period(w: Wallet) -> None:
    """If the calendar month changed, reset monthly_spent."""
    mk = _current_month_key()
    if w.month_key != mk:
        w.month_key = mk
        w.monthly_spent_cents = 0


# ── Public API ──────────────────────────────────────────────────────────────

def get_wallet() -> Wallet:
    with _lock:
        w = _load()
        _roll_period(w)
        return w


def balance_cents() -> int:
    return get_wallet().balance_cents


def set_cap(monthly_cap_cents: int) -> Wallet:
    with _lock:
        w = _load()
        w.monthly_cap_cents = max(0, int(monthly_cap_cents))
        _save(w)
    _audit("wallet_cap_set", {"cap": w.monthly_cap_cents})
    return w


def set_mode(mode: str) -> Wallet:
    if mode not in ("simulated", "stripe_issuing"):
        raise ValueError(f"Unknown wallet mode: {mode}")
    with _lock:
        w = _load()
        w.mode = mode
        _save(w)
    _audit("wallet_mode_set", {"mode": mode})
    return w


def top_up(cents: int, source: str = "manual") -> int:
    cents = int(cents)
    if cents <= 0:
        return get_wallet().balance_cents
    with _lock:
        w = _load()
        _roll_period(w)
        w.balance_cents += cents
        _save(w)
        entry = LedgerEntry(
            kind="topup",
            category="other",
            cents=-cents,
            memo=f"top_up:{source}",
            balance_after_cents=w.balance_cents,
        )
        _persist_ledger(entry)
    _audit("wallet_topup", {"cents": cents, "source": source, "balance": w.balance_cents})
    return w.balance_cents


# ── Policy management ───────────────────────────────────────────────────────

def add_policy(policy: Policy) -> Policy:
    if policy.category not in CATEGORIES and policy.category != "*":
        raise ValueError(f"Unknown category: {policy.category}")
    with _lock:
        w = _load()
        w.policies.append(policy)
        _save(w)
    _audit("wallet_policy_add", policy.to_dict())
    return policy


def remove_policy(policy_id: str) -> bool:
    with _lock:
        w = _load()
        before = len(w.policies)
        w.policies = [p for p in w.policies if p.id != policy_id]
        _save(w)
    return len(w.policies) < before


def list_policies() -> list[Policy]:
    return list(get_wallet().policies)


# ── Charging ────────────────────────────────────────────────────────────────

def can_spend(category: str, cents: int) -> tuple[bool, str]:
    """Pre-flight check used by the UI before kicking off a pay-per-use action."""
    if category not in CATEGORIES:
        return False, f"unknown category {category}"
    cents = int(cents)
    if cents <= 0:
        return True, ""
    w = get_wallet()
    if w.balance_cents < cents:
        return False, "insufficient balance"
    if (w.monthly_spent_cents + cents) > w.monthly_cap_cents:
        return False, "monthly cap"
    for p in w.policies:
        if p.category not in (category, "*"):
            continue
        if p.deny:
            return False, f"policy:{p.id} deny"
        if p.max_per_charge_cents is not None and cents > p.max_per_charge_cents:
            return False, f"policy:{p.id} max_per_charge"
        if p.max_per_day_cents is not None:
            today = _spent_today(category)
            if (today + cents) > p.max_per_day_cents:
                return False, f"policy:{p.id} max_per_day"
    return True, ""


def charge(
    category: str,
    cents: int,
    memo: str = "",
    *,
    subject: str = "",
    approved_by: str | None = None,
) -> LedgerEntry:
    """
    Deduct `cents` from the wallet. Raises BudgetExceeded on deny and
    ConfirmRequired when a policy demands approval above threshold.
    Zero-cent charges are allowed (useful as accounting pings).
    """
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    cents = int(cents)
    ok, reason = can_spend(category, cents) if cents > 0 else (True, "")
    if not ok:
        entry = LedgerEntry(
            kind="deny",
            category=category,
            cents=cents,
            memo=f"{memo} ({reason})".strip(),
            subject=subject,
            balance_after_cents=get_wallet().balance_cents,
        )
        _persist_ledger(entry)
        _audit("wallet_deny", {"category": category, "cents": cents, "reason": reason})
        raise BudgetExceeded(f"{category} charge denied: {reason}")

    # Approval-required policies
    if cents > 0 and approved_by is None:
        for p in get_wallet().policies:
            if p.category not in (category, "*"):
                continue
            threshold = p.require_approval_above_cents
            if threshold is not None and cents > threshold:
                _audit("wallet_approval_required", {
                    "category": category, "cents": cents, "policy": p.id,
                })
                raise ConfirmRequired(
                    f"{category} charge of {cents}c exceeds policy {p.id} "
                    f"approval threshold ({threshold}c)."
                )

    # Optional Stripe Issuing path.
    with _lock:
        w = _load()
        _roll_period(w)
        if cents > 0 and w.mode == "stripe_issuing":
            try:
                from providers import stripe_issuing as _si
                _si.authorize(cents=cents, category=category, memo=memo, subject=subject)
            except Exception as e:
                entry = LedgerEntry(
                    kind="deny", category=category, cents=cents,
                    memo=f"{memo} (stripe: {e})",
                    subject=subject,
                    balance_after_cents=w.balance_cents,
                )
                _persist_ledger(entry)
                raise BudgetExceeded(f"Stripe Issuing declined: {e}") from e
        w.balance_cents -= cents
        w.monthly_spent_cents += max(0, cents)
        _save(w)
        entry = LedgerEntry(
            kind="charge",
            category=category,
            cents=cents,
            memo=memo,
            subject=subject,
            balance_after_cents=w.balance_cents,
            approved_by=approved_by,
        )
        _persist_ledger(entry)
    _audit("wallet_charge", {
        "category": category, "cents": cents, "memo": memo,
        "subject": subject, "balance": w.balance_cents,
    })
    return entry


def try_charge(
    category: str,
    cents: int,
    memo: str = "",
    *,
    subject: str = "",
    approved_by: str | None = None,
) -> LedgerEntry | None:
    """Like `charge()` but returns None instead of raising on deny/approval."""
    try:
        return charge(category, cents, memo, subject=subject, approved_by=approved_by)
    except (BudgetExceeded, ConfirmRequired):
        return None
    except Exception as e:
        _audit("wallet_charge_error", {"category": category, "error": str(e)})
        return None


def refund(category: str, cents: int, memo: str = "") -> LedgerEntry:
    cents = int(cents)
    if cents <= 0:
        return LedgerEntry(kind="refund", cents=0, category=category, memo=memo)
    with _lock:
        w = _load()
        _roll_period(w)
        w.balance_cents += cents
        w.monthly_spent_cents = max(0, w.monthly_spent_cents - cents)
        _save(w)
        entry = LedgerEntry(
            kind="refund", category=category, cents=-cents, memo=memo,
            balance_after_cents=w.balance_cents,
        )
        _persist_ledger(entry)
    _audit("wallet_refund", {"category": category, "cents": cents, "memo": memo})
    return entry


# ── Queries ─────────────────────────────────────────────────────────────────

def ledger(limit: int = 50, category: str | None = None) -> list[dict]:
    if not LEDGER_LOG.exists():
        return []
    lines = LEDGER_LOG.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for ln in lines[-5000:]:
        try:
            row = json.loads(ln)
        except Exception:
            continue
        if category and row.get("category") != category:
            continue
        out.append(row)
    return out[-limit:]


def monthly_spent(category: str | None = None) -> int:
    w = get_wallet()
    if category is None:
        return w.monthly_spent_cents
    key = _current_month_key()
    total = 0
    for row in ledger(limit=10_000, category=category):
        if row.get("kind") == "charge" and row.get("ts") and \
           datetime.fromtimestamp(row["ts"], tz=timezone.utc).strftime("%Y-%m") == key:
            total += int(row.get("cents", 0))
    return total


def _spent_today(category: str) -> int:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    total = 0
    for row in ledger(limit=10_000, category=category):
        if row.get("kind") != "charge":
            continue
        ts = row.get("ts")
        if not ts:
            continue
        if datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") == today:
            total += int(row.get("cents", 0))
    return total


def summary() -> dict:
    w = get_wallet()
    return {
        "id":                 w.id,
        "name":               w.name,
        "balance_cents":      w.balance_cents,
        "monthly_cap_cents":  w.monthly_cap_cents,
        "monthly_spent_cents": w.monthly_spent_cents,
        "mode":               w.mode,
        "policies":           [p.to_dict() for p in w.policies],
        "month_key":          w.month_key or _current_month_key(),
    }


# ── helpers ─────────────────────────────────────────────────────────────────

def _audit(event: str, payload: dict) -> None:
    try:
        from safety import audit as _audit_fn
        _audit_fn({"event": event, **payload})
    except Exception:
        pass


# ── Convenience: install a sane default policy set on first boot ────────────

def install_default_policies() -> None:
    w = get_wallet()
    if w.policies:
        return
    add_policy(Policy(category="cloud_api",  max_per_day_cents=500,  note="$5/day cloud cap"))
    add_policy(Policy(category="plugin",     require_approval_above_cents=2000,
                      note="Ask before spending > $20 on a single plugin"))
    add_policy(Policy(category="subagent",   max_per_day_cents=200,  note="$2/day on subagents"))
