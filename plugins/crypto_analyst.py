"""
Crypto Analyst — prices and simple sentiment via CoinGecko.
"""

from __future__ import annotations

import json
from typing import Any

import requests

CG = "https://api.coingecko.com/api/v3"


def price(coin_id: str, vs: str = "usd") -> dict[str, Any]:
    coin_id = (coin_id or "").strip().lower()
    try:
        r = requests.get(
            f"{CG}/simple/price",
            params={"ids": coin_id, "vs_currencies": vs, "include_24hr_change": "true"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get(coin_id) or {}
        if not data:
            return {"error": "coin not found", "coin": coin_id}
        change = data.get(f"{vs}_24h_change", 0.0)
        verdict = "bullish" if change > 3 else "bearish" if change < -3 else "flat"
        return {
            "coin": coin_id,
            "price": data.get(vs),
            "change_24h_pct": round(change, 2),
            "verdict": verdict,
        }
    except Exception as e:
        return {"error": str(e), "coin": coin_id}


def top(n: int = 10) -> list[dict[str, Any]]:
    try:
        r = requests.get(
            f"{CG}/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": n, "page": 1},
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json() or []
        return [
            {
                "coin":            row.get("id"),
                "symbol":          row.get("symbol"),
                "price":           row.get("current_price"),
                "change_24h_pct":  round(row.get("price_change_percentage_24h") or 0, 2),
                "market_cap":      row.get("market_cap"),
            }
            for row in rows
        ]
    except Exception as e:
        return [{"error": str(e)}]


if __name__ == "__main__":
    print(json.dumps(price("bitcoin"), indent=2))
