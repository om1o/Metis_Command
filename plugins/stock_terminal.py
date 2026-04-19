"""
Stock Terminal — quick-lookup market data.

Uses Yahoo Finance's public quote endpoint. No API key required.
"""

from __future__ import annotations

import json
from typing import Any

import requests

YF_URL = "https://query1.finance.yahoo.com/v7/finance/quote"


def quote(symbol: str) -> dict[str, Any]:
    """Return a dict with price, change, and volume for `symbol`."""
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"error": "symbol required"}
    try:
        r = requests.get(
            YF_URL,
            params={"symbols": symbol},
            headers={"User-Agent": "Mozilla/5.0 Metis"},
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json().get("quoteResponse", {}).get("result") or []
        if not rows:
            return {"error": "symbol not found", "symbol": symbol}
        q = rows[0]
        return {
            "symbol":          q.get("symbol"),
            "name":            q.get("longName") or q.get("shortName"),
            "price":           q.get("regularMarketPrice"),
            "change_percent":  q.get("regularMarketChangePercent"),
            "volume":          q.get("regularMarketVolume"),
            "currency":        q.get("currency"),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def portfolio(symbols: list[str]) -> list[dict[str, Any]]:
    return [quote(s) for s in symbols]


if __name__ == "__main__":
    print(json.dumps(quote("AAPL"), indent=2))
