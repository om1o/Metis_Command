"""
Investing Scanner — periodic AI-driven analysis of the watchlist.

For each ticker the Director is watching, fetch a quote + recent news, then
ask Groq (free tier) for a 2-sentence take and a directional signal. When
the signal is strong, surface it as an `opportunity` and (optionally) emit
a `proposal` that the human must approve before execution.

Public API
----------
    scan_watchlist(*, max_tickers=10, propose=False) -> dict
        Walk every ticker on the watchlist (capped to keep Groq under the
        free-tier rate limit), generate analysis, write opportunities, and
        if `propose=True` push high-confidence picks into the proposals
        queue for the human to approve.

    analyze_ticker(ticker) -> dict | None
        One-shot analysis returning {ticker, take, signal, confidence, ...}.

Safety
------
- Even with `propose=True`, every proposal still requires the human to
  approve before any (paper) order fills. We never auto-execute.
- Free Groq tier is rate-limited; we cap to 10 tickers per call by default.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any


_SYSTEM_PROMPT = (
    "You are a sober equity research analyst. Given a ticker, current price, "
    "day change, and a few recent news headlines, return STRICT JSON ONLY in "
    "this exact shape:\n"
    "{\n"
    '  "take": "<2 sentences max — what is going on with this stock right now>",\n'
    '  "signal": "buy" | "sell" | "hold",\n'
    '  "confidence": 0.0-1.0,\n'
    '  "risk": "low" | "medium" | "high",\n'
    '  "key_factors": ["...", "..."]\n'
    "}\n"
    "Be conservative. If the data is thin, return signal=hold with confidence<=0.4. "
    "Never recommend buying based on hype alone. Never invent news that wasn't in "
    "the input. No prose outside the JSON."
)


def _fetch_news(ticker: str, max_items: int = 4) -> list[str]:
    """Pull the latest few news headlines for a ticker via yfinance."""
    try:
        import yfinance as yf  # type: ignore
        items = []
        for n in (yf.Ticker(ticker).news or [])[:max_items]:
            title = n.get("title") if isinstance(n, dict) else None
            if title:
                items.append(str(title)[:240])
        return items
    except Exception:
        return []


def _extract_json(text: str) -> dict | None:
    """Pull the first {...} block from a possibly-fenced reply."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        # Strip ```json ... ```
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Best-effort: find first { ... last }
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            return None
    return None


def analyze_ticker(ticker: str) -> dict | None:
    """Use Groq to write a short take on a single ticker."""
    import investing as _inv
    quote = _inv.get_quote(ticker)
    if not quote or not quote.get("price"):
        return None
    headlines = _fetch_news(ticker)
    user_block = (
        f"Ticker: {ticker}\n"
        f"Last price: ${quote.get('price')}\n"
        f"Previous close: ${quote.get('previous_close')}\n"
        f"Day change: {quote.get('change_pct')}%\n"
        f"Recent headlines:\n"
        + "\n".join(f"- {h}" for h in headlines)
    )
    try:
        from providers import groq as _groq
        if not _groq.is_configured():
            return {
                "ticker": ticker,
                "take": "Groq API key not set — set GROQ_API_KEY in .env to enable AI analysis.",
                "signal": "hold",
                "confidence": 0.0,
                "risk": "medium",
                "key_factors": [],
                "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
            }
        # Use the recommended fast tools-capable model from the new registry.
        recommended = getattr(_groq, "GROQ_RECOMMENDED", {}).get("reasoning") or _groq.default_model()
        raw = _groq.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_block},
            ],
            model=recommended,
            temperature=0.2,
            timeout=45.0,
        )
        parsed = _extract_json(raw) or {}
    except Exception as e:
        parsed = {"take": f"Analysis failed: {e}", "signal": "hold", "confidence": 0.0, "risk": "medium", "key_factors": []}

    return {
        "ticker": ticker,
        "take": str(parsed.get("take") or "")[:600],
        "signal": (parsed.get("signal") or "hold").lower(),
        "confidence": max(0.0, min(1.0, float(parsed.get("confidence") or 0.0))),
        "risk": (parsed.get("risk") or "medium").lower(),
        "key_factors": list(parsed.get("key_factors") or [])[:6],
        "headlines": headlines,
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "price": quote.get("price"),
        "change_pct": quote.get("change_pct"),
    }


def scan_watchlist(*, max_tickers: int = 10, propose: bool = False) -> dict:
    """
    Run AI analysis across the watchlist + every current holding.

    `propose=True` means high-confidence buy/sell signals get pushed into
    the `proposals` queue (status='pending') for the human to approve.
    """
    import investing as _inv
    data = _inv._read()
    universe: list[str] = []
    for t in data.get("watchlist", []) or []:
        if t and t not in universe:
            universe.append(t)
    for t in (data.get("holdings") or {}).keys():
        if t and t not in universe:
            universe.append(t)
    if not universe:
        return {"ok": True, "scanned": 0, "opportunities": 0, "proposals": 0}

    universe = universe[:max_tickers]
    opps: list[dict] = []
    proposals_made = 0

    for ticker in universe:
        result = analyze_ticker(ticker)
        if not result:
            continue
        opps.append(result)
        # Auto-propose only when signal is decisive AND confidence is high.
        if propose and result["signal"] in ("buy", "sell") and result["confidence"] >= 0.7:
            # Suggest a small notional position to keep within caps.
            settings = _inv.get_settings()
            per_trade = int(settings.get("per_trade_cap_cents") or _inv.PER_TRADE_CAP_CENTS)
            target_notional_cents = max(10000, per_trade // 5)  # ~20% of per-trade cap
            qty = target_notional_cents / max(1, int((result.get("price") or 1) * 100))
            qty = round(qty, 2)
            if qty <= 0:
                continue
            r = _inv.propose_trade(
                ticker, result["signal"], qty,
                reason=result.get("take") or "",
                confidence=result["confidence"],
                source="scanner",
            )
            if r.get("ok"):
                proposals_made += 1
                # Best-effort: notify the Director per their preferences (Group 8 hooks in here).
                try:
                    _maybe_notify_proposal(r["proposal"])
                except Exception:
                    pass

    _inv.set_opportunities(opps)
    return {
        "ok": True,
        "scanned": len(universe),
        "opportunities": len(opps),
        "proposals": proposals_made,
    }


def _maybe_notify_proposal(proposal: dict) -> None:
    """
    Send a notification when the AI proposes a trade. Honors the Director's
    notification prefs (email > sms > voice from .env METIS_NOTIFY_PREFER).
    """
    try:
        import manager_config as _mc
        cfg = _mc.get_config("default")
    except Exception:
        cfg = None
    if not cfg or not cfg.notify_on_complete:
        return

    body = (
        f"AI proposed a trade:\n"
        f"  {proposal['side'].upper()} {proposal['qty']} {proposal['ticker']} "
        f"@ ~${proposal['est_price']:.2f}  (≈ ${proposal['est_cost_cents']/100:.2f})\n\n"
        f"Why: {proposal['reason'][:400]}\n\n"
        f"Open the Money tab → Investing to approve or reject."
    )
    subject = f"Metis: AI proposed {proposal['side'].upper()} {proposal['ticker']}"

    pref = (os.getenv("METIS_NOTIFY_PREFER") or "email,sms,voice").lower()
    channels = [c.strip() for c in pref.split(",") if c.strip()]
    try:
        from comms_link import CommsLink
        link = CommsLink()
        for ch in channels:
            if ch == "email" and cfg.notification_email:
                if link.send_human_email(cfg.notification_email, subject, body, user_id="default"):
                    return
            elif ch == "sms" and cfg.notification_phone:
                if link.send_text_message(cfg.notification_phone, subject + "\n\n" + body[:300]):
                    return
    except Exception:
        return
