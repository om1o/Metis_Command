"""
Usage Tracker — Cline-style token + cost accounting.

Local Ollama calls are free but tracked anyway so the UI status bar can
report tok/s, total tokens per session, and "equivalent cloud cost" (what
the same volume would have cost via OpenAI / Anthropic).

Cloud calls through OpenAI/Anthropic are tracked against real prices.
State lives in `logs/usage.jsonl` and is tail-read by the UI.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from safety import audit


USAGE_LOG = Path("logs") / "usage.jsonl"


# Input / output per-1K-token pricing in USD. Local Ollama = 0.
# Kept as a plain dict so users can swap values without touching logic.
PRICES_USD_PER_1K: dict[str, dict[str, float]] = {
    "ollama":         {"in": 0.0000, "out": 0.0000},
    "gpt-4o":         {"in": 0.0025, "out": 0.0100},
    "gpt-4o-mini":    {"in": 0.00015, "out": 0.00060},
    "claude-sonnet":  {"in": 0.003,  "out": 0.015},
    "claude-opus":    {"in": 0.015,  "out": 0.075},
    "claude-haiku":   {"in": 0.00025, "out": 0.00125},
}


@dataclass
class UsageEvent:
    ts: float = field(default_factory=time.time)
    role: str = "default"
    model: str = ""
    provider: str = "ollama"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    session_id: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_usd(self) -> float:
        price = PRICES_USD_PER_1K.get(self.provider, PRICES_USD_PER_1K["ollama"])
        return round(
            (self.prompt_tokens / 1000) * price["in"]
            + (self.completion_tokens / 1000) * price["out"],
            6,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        d["cost_usd"] = self.cost_usd()
        return d


_lock = threading.Lock()
_in_memory: list[UsageEvent] = []


# ── Public API ───────────────────────────────────────────────────────────────

def record(
    *,
    role: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    session_id: str = "",
    provider: str | None = None,
) -> UsageEvent:
    """Record one LLM call. `provider` auto-detected from the model name if omitted."""
    if provider is None:
        provider = _guess_provider(model)
    event = UsageEvent(
        role=role,
        model=model,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
        session_id=session_id,
    )
    with _lock:
        _in_memory.append(event)
    _persist(event)
    # Bill the Orchestrator wallet for any non-local inference, with graceful
    # fallback when the wallet module is unavailable or denies the charge.
    if event.provider != "ollama":
        cost_cents = int(round(event.cost_usd() * 100))
        if cost_cents > 0:
            try:
                from wallet import try_charge
                try_charge(
                    "cloud_api",
                    cost_cents,
                    memo=f"{event.role}:{event.provider}",
                    subject=event.model,
                )
            except Exception:
                pass
    return event


def summary(session_id: str | None = None) -> dict[str, Any]:
    """Aggregate totals, optionally scoped to a single session."""
    events = load()
    if session_id:
        events = [e for e in events if e.get("session_id") == session_id]
    total_in  = sum(e.get("prompt_tokens", 0)     for e in events)
    total_out = sum(e.get("completion_tokens", 0) for e in events)
    total_cost = sum(e.get("cost_usd", 0.0)       for e in events)
    by_model: dict[str, dict[str, Any]] = {}
    for e in events:
        model = e.get("model", "?")
        agg = by_model.setdefault(model, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0})
        agg["calls"] += 1
        agg["tokens_in"] += e.get("prompt_tokens", 0)
        agg["tokens_out"] += e.get("completion_tokens", 0)
        agg["cost"] += e.get("cost_usd", 0.0)
    return {
        "calls":       len(events),
        "tokens_in":   total_in,
        "tokens_out":  total_out,
        "total_tokens": total_in + total_out,
        "cost_usd":    round(total_cost, 6),
        "by_model":    by_model,
    }


def load(limit: int | None = None) -> list[dict[str, Any]]:
    if not USAGE_LOG.exists():
        return []
    text = USAGE_LOG.read_text(encoding="utf-8")
    lines = text.splitlines()
    if limit:
        lines = lines[-limit:]
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def clear() -> None:
    if USAGE_LOG.exists():
        USAGE_LOG.unlink()
    with _lock:
        _in_memory.clear()
    audit({"event": "usage_cleared"})


# ── Helpers ──────────────────────────────────────────────────────────────────

def _guess_provider(model: str) -> str:
    m = (model or "").lower()
    if "gpt" in m or "o1" in m or "o3" in m:
        return "gpt-4o" if "4o" in m else "gpt-4o-mini" if "mini" in m else "gpt-4o"
    if "claude" in m:
        if "opus"   in m: return "claude-opus"
        if "haiku"  in m: return "claude-haiku"
        return "claude-sonnet"
    return "ollama"


def _persist(event: UsageEvent) -> None:
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Token estimation fallback ────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough 4-char-per-token heuristic (good enough for local UX)."""
    return max(1, len(text or "") // 4)
