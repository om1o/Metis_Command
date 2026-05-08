"""
Metis Investing — sandbox-only paper trading with free market data.

Why paper-only by default
-------------------------
Real-money brokerages all require KYC + government ID to comply with FINRA /
SEC. The user explicitly asked for an option that does NOT require IDs, so
this module ships in "paper" mode out of the box: a simulated portfolio
where the agent picks tickers, tracks performance, and surfaces opportunities
— but never moves real money.

Switching modes
---------------
METIS_INVEST_MODE=paper          (default) simulated portfolio + free data
METIS_INVEST_MODE=alpaca_paper   Alpaca paper trading (real exchange data,
                                 fake money, free signup, no ID for paper)
METIS_INVEST_MODE=alpaca_live    real money via Alpaca (requires KYC)

Public API
----------
    portfolio()                       -> dict   summary + holdings
    add_to_watchlist(ticker)          -> dict
    remove_from_watchlist(ticker)     -> bool
    get_watchlist()                   -> list[dict]   live quotes
    get_quote(ticker)                 -> dict | None
    submit_order(ticker, side, qty)   -> dict   paper-only; needs approval token
    list_orders(limit=50)             -> list[dict]
    list_opportunities()              -> list[dict]   AI-flagged ideas

Storage
-------
identity/investing.json — list of holdings, watchlist, order history.
Gitignored (per .gitignore identity rules).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


INVEST_FILE = Path("identity") / "investing.json"

# ── Hard safety caps (Group 3) ──────────────────────────────────────────────
# Even in paper mode, we apply per-trade and per-day spending limits so the
# behaviour mirrors what the operator wants for real-money mode later.
# Override with env vars METIS_INVEST_PER_TRADE_CAP_CENTS / METIS_INVEST_DAILY_CAP_CENTS.
PER_TRADE_CAP_CENTS = int(os.getenv("METIS_INVEST_PER_TRADE_CAP_CENTS", "500000"))   # $5,000
DAILY_CAP_CENTS     = int(os.getenv("METIS_INVEST_DAILY_CAP_CENTS",     "1000000"))  # $10,000


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_str() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _empty_state() -> dict:
    return {
        "mode": os.getenv("METIS_INVEST_MODE", "paper"),
        "cash_cents": 100_000_00,         # $100,000 paper starting cash
        "holdings": {},                    # ticker -> {qty, avg_cost_cents}
        "watchlist": [],                   # list[str] tickers
        "orders": [],                      # list[dict] order history
        "opportunities": [],               # list[dict] AI-flagged ideas
        "proposals": [],                   # list[dict] pending AI-proposed trades
        "spend_history": {},               # date_str -> total_spent_cents (for daily cap)
        "settings": {                      # safety + scan settings
            "per_trade_cap_cents": PER_TRADE_CAP_CENTS,
            "daily_cap_cents":     DAILY_CAP_CENTS,
            "auto_approve_under_cents": 0,    # 0 = always require approval
            "scan_interval_min": 60,
            "notify_on_proposal": True,
        },
    }


def _read() -> dict:
    if not INVEST_FILE.exists():
        return _empty_state()
    try:
        data = json.loads(INVEST_FILE.read_text(encoding="utf-8"))
        # Self-heal old files that pre-date Group 3.
        defaults = _empty_state()
        for k, v in defaults.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return _empty_state()


def _write(d: dict) -> None:
    INVEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    INVEST_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


# ── Market data (free, no API key required) ─────────────────────────────────

def get_quote(ticker: str) -> dict | None:
    """
    Fetch a recent quote via yfinance. Returns None on failure.
    yfinance is a thin wrapper around Yahoo Finance — no API key, no signup.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None
    try:
        import yfinance as yf  # type: ignore
        t = yf.Ticker(ticker)
        info = getattr(t, "fast_info", None) or {}
        last = float(info.get("last_price") or info.get("lastPrice") or 0) if info else 0.0
        prev = float(info.get("previous_close") or info.get("previousClose") or 0) if info else 0.0
        if not last:
            # Fall back to history()
            hist = t.history(period="2d")
            if not hist.empty:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
        change_pct = ((last - prev) / prev * 100.0) if prev else 0.0
        return {
            "ticker": ticker,
            "price": round(last, 2),
            "previous_close": round(prev, 2),
            "change_pct": round(change_pct, 2),
            "as_of": _now_iso(),
        }
    except ModuleNotFoundError:
        # yfinance not installed yet — return a placeholder so the UI can render.
        return {
            "ticker": ticker,
            "price": 0.0,
            "previous_close": 0.0,
            "change_pct": 0.0,
            "as_of": _now_iso(),
            "error": "yfinance-not-installed",
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "price": 0.0,
            "previous_close": 0.0,
            "change_pct": 0.0,
            "as_of": _now_iso(),
            "error": str(e)[:120],
        }


# ── Watchlist ───────────────────────────────────────────────────────────────

def add_to_watchlist(ticker: str) -> dict:
    t = (ticker or "").strip().upper()
    if not t:
        return {"ok": False, "error": "ticker required"}
    data = _read()
    if t in data["watchlist"]:
        return {"ok": True, "watchlist": data["watchlist"]}
    data["watchlist"].append(t)
    _write(data)
    return {"ok": True, "watchlist": data["watchlist"]}


def remove_from_watchlist(ticker: str) -> bool:
    t = (ticker or "").strip().upper()
    data = _read()
    before = len(data["watchlist"])
    data["watchlist"] = [x for x in data["watchlist"] if x != t]
    _write(data)
    return len(data["watchlist"]) < before


def get_watchlist() -> list[dict]:
    data = _read()
    return [get_quote(t) or {"ticker": t} for t in data["watchlist"]]


# ── Portfolio ───────────────────────────────────────────────────────────────

def portfolio() -> dict:
    data = _read()
    holdings_out: list[dict] = []
    total_value_cents = 0
    total_cost_cents = 0
    for ticker, h in (data.get("holdings") or {}).items():
        qty = float(h.get("qty", 0) or 0)
        avg_cost_cents = int(h.get("avg_cost_cents", 0) or 0)
        q = get_quote(ticker)
        last_price = (q or {}).get("price", 0.0) or 0.0
        value_cents = int(round(last_price * qty * 100))
        cost_cents = int(round(avg_cost_cents * qty))
        gain_cents = value_cents - cost_cents
        gain_pct = (gain_cents / cost_cents * 100.0) if cost_cents else 0.0
        total_value_cents += value_cents
        total_cost_cents += cost_cents
        holdings_out.append({
            "ticker": ticker,
            "qty": qty,
            "avg_cost_cents": avg_cost_cents,
            "last_price": last_price,
            "value_cents": value_cents,
            "gain_cents": gain_cents,
            "gain_pct": round(gain_pct, 2),
        })
    return {
        "mode": data.get("mode", "paper"),
        "cash_cents": int(data.get("cash_cents", 0) or 0),
        "holdings": holdings_out,
        "total_value_cents": total_value_cents,
        "total_cost_cents": total_cost_cents,
        "total_gain_cents": total_value_cents - total_cost_cents,
        "as_of": _now_iso(),
    }


# ── Orders (paper only — no real money) ─────────────────────────────────────

def submit_order(
    ticker: str,
    side: str,
    qty: float,
    *,
    approval_token: str | None = None,
) -> dict:
    """
    Paper-only order submission. Real-money modes are rejected unless KYC
    is complete (Groups beyond 2 will integrate that flow).
    """
    data = _read()
    if data.get("mode", "paper") != "paper":
        return {"ok": False, "error": "real-money mode requires KYC; not yet supported"}
    side = (side or "").lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}
    qty = float(qty or 0)
    if qty <= 0:
        return {"ok": False, "error": "qty must be > 0"}
    t = (ticker or "").strip().upper()
    if not t:
        return {"ok": False, "error": "ticker required"}

    quote = get_quote(t)
    if not quote or not quote.get("price"):
        return {"ok": False, "error": "no price available; check ticker"}

    price = float(quote["price"])
    cost_cents = int(round(price * qty * 100))

    # Hard caps — apply to BOTH buy and sell (any trade movement counts).
    settings = data.get("settings") or {}
    per_trade_cap = int(settings.get("per_trade_cap_cents") or PER_TRADE_CAP_CENTS)
    daily_cap     = int(settings.get("daily_cap_cents")     or DAILY_CAP_CENTS)
    if cost_cents > per_trade_cap:
        return {
            "ok": False,
            "error": f"per-trade cap exceeded (${cost_cents/100:.2f} > ${per_trade_cap/100:.2f})",
        }
    today = _today_str()
    spent_today = int((data.get("spend_history") or {}).get(today, 0))
    if spent_today + cost_cents > daily_cap:
        return {
            "ok": False,
            "error": f"daily cap exceeded (today ${spent_today/100:.2f} + ${cost_cents/100:.2f} > ${daily_cap/100:.2f})",
        }

    if side == "buy":
        if cost_cents > data["cash_cents"]:
            return {"ok": False, "error": "insufficient paper cash"}
        h = data["holdings"].get(t, {"qty": 0.0, "avg_cost_cents": 0})
        prev_qty = float(h["qty"])
        prev_cost = int(h["avg_cost_cents"]) * prev_qty
        new_qty = prev_qty + qty
        new_avg = int(round((prev_cost + (price * qty * 100)) / new_qty)) if new_qty else 0
        data["holdings"][t] = {"qty": new_qty, "avg_cost_cents": new_avg}
        data["cash_cents"] -= cost_cents
    else:  # sell
        h = data["holdings"].get(t, {"qty": 0.0, "avg_cost_cents": 0})
        if float(h.get("qty", 0)) < qty:
            return {"ok": False, "error": "insufficient shares"}
        h["qty"] = float(h["qty"]) - qty
        if h["qty"] <= 0:
            del data["holdings"][t]
        else:
            data["holdings"][t] = h
        data["cash_cents"] += cost_cents

    order = {
        "id": uuid.uuid4().hex[:10],
        "ticker": t,
        "side": side,
        "qty": qty,
        "price": price,
        "cost_cents": cost_cents,
        "approval_token": approval_token or "",
        "status": "filled",      # paper orders fill instantly
        "ts": _now_iso(),
    }
    data["orders"].insert(0, order)
    data["orders"] = data["orders"][:200]
    # Track spend toward the daily cap.
    sh = data.setdefault("spend_history", {})
    sh[_today_str()] = int(sh.get(_today_str(), 0)) + cost_cents
    _write(data)
    return {"ok": True, "order": order, "cash_cents": data["cash_cents"]}


def list_orders(limit: int = 50) -> list[dict]:
    return _read().get("orders", [])[:limit]


# ── AI-flagged opportunities ───────────────────────────────────────────────

def list_opportunities() -> list[dict]:
    return _read().get("opportunities", [])


def set_opportunities(items: list[dict]) -> None:
    """Replace the opportunities list (called by the scanner)."""
    data = _read()
    data["opportunities"] = items[:50]
    _write(data)


# ── AI-proposed trades (require human approval before execution) ────────────

def list_proposals(limit: int = 50) -> list[dict]:
    """Return pending AI-proposed trades (status='pending')."""
    data = _read()
    return [p for p in data.get("proposals", []) if p.get("status") == "pending"][:limit]


def list_all_proposals(limit: int = 100) -> list[dict]:
    """Return all proposals including approved/rejected, newest first."""
    return _read().get("proposals", [])[:limit]


def propose_trade(
    ticker: str,
    side: str,
    qty: float,
    *,
    reason: str = "",
    confidence: float = 0.5,
    source: str = "ai",
) -> dict:
    """
    The scanner / AI calls this to suggest a trade. Records the suggestion
    with status='pending'; the human approves via approve_proposal().
    """
    data = _read()
    t = (ticker or "").strip().upper()
    side = (side or "").lower()
    qty = float(qty or 0)
    if not t or side not in ("buy", "sell") or qty <= 0:
        return {"ok": False, "error": "invalid proposal"}

    quote = get_quote(t)
    price = float((quote or {}).get("price") or 0)
    est_cost_cents = int(round(price * qty * 100))

    proposal = {
        "id": uuid.uuid4().hex[:10],
        "ticker": t,
        "side": side,
        "qty": qty,
        "est_price": price,
        "est_cost_cents": est_cost_cents,
        "reason": (reason or "").strip()[:600],
        "confidence": max(0.0, min(1.0, float(confidence or 0.5))),
        "source": source,
        "status": "pending",
        "created_at": _now_iso(),
    }
    data.setdefault("proposals", []).insert(0, proposal)
    data["proposals"] = data["proposals"][:200]
    _write(data)
    return {"ok": True, "proposal": proposal}


def approve_proposal(proposal_id: str) -> dict:
    """Execute a proposed trade (still subject to caps + cash check)."""
    data = _read()
    target = next((p for p in data.get("proposals", []) if p["id"] == proposal_id), None)
    if not target:
        return {"ok": False, "error": "proposal not found"}
    if target["status"] != "pending":
        return {"ok": False, "error": f"proposal already {target['status']}"}

    result = submit_order(
        target["ticker"], target["side"], target["qty"],
        approval_token=proposal_id,
    )
    # submit_order persists; re-read state.
    data = _read()
    for p in data.get("proposals", []):
        if p["id"] == proposal_id:
            p["status"] = "filled" if result.get("ok") else "failed"
            p["resolved_at"] = _now_iso()
            if not result.get("ok"):
                p["error"] = result.get("error", "")
            break
    _write(data)
    return {"ok": bool(result.get("ok")), "result": result}


def reject_proposal(proposal_id: str, *, note: str = "") -> bool:
    data = _read()
    found = False
    for p in data.get("proposals", []):
        if p["id"] == proposal_id and p["status"] == "pending":
            p["status"] = "rejected"
            p["resolved_at"] = _now_iso()
            if note:
                p["note"] = note[:240]
            found = True
            break
    _write(data)
    return found


# ── Settings ────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    return _read().get("settings", {})


def update_settings(patch: dict) -> dict:
    data = _read()
    s = data.setdefault("settings", {})
    for k in ("per_trade_cap_cents", "daily_cap_cents",
              "auto_approve_under_cents", "scan_interval_min",
              "notify_on_proposal"):
        if k in patch and patch[k] is not None:
            s[k] = patch[k]
    _write(data)
    return s


def daily_spent_cents(date_str: str | None = None) -> int:
    data = _read()
    return int((data.get("spend_history") or {}).get(date_str or _today_str(), 0))
