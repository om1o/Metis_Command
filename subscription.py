"""
Subscription tiers — Free / Pro / Enterprise.

Stripe is optional; when keys are absent we run in "dev" mode where
require_tier() always passes and get_current_tier() reads a local override.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Callable

from dotenv import load_dotenv
load_dotenv()

try:
    import stripe  # type: ignore
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY") or ""
except Exception:
    stripe = None  # type: ignore


class Tier(str, Enum):
    FREE = "Free"
    PRO = "Pro"
    ENTERPRISE = "Enterprise"


TIER_RANK = {Tier.FREE: 0, Tier.PRO: 1, Tier.ENTERPRISE: 2}

PRICES = {
    Tier.PRO:        os.getenv("STRIPE_PRICE_PRO") or "",
    Tier.ENTERPRISE: os.getenv("STRIPE_PRICE_ENTERPRISE") or "",
}


# ── Current tier lookup ──────────────────────────────────────────────────────

def get_current_tier(user_id: str | None = None) -> Tier:
    """
    Return the caller's active subscription tier.
    Resolution order:
        1. METIS_TIER_OVERRIDE env (dev / demo)
        2. Supabase users_subscription table
        3. Default Free
    """
    override = os.getenv("METIS_TIER_OVERRIDE") or ""
    if override:
        try:
            return Tier(override.capitalize())
        except Exception:
            pass

    if user_id:
        try:
            from supabase_client import get_client
            response = (
                get_client()
                .table("users_subscription")
                .select("tier")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if response.data:
                return Tier(response.data[0]["tier"])
        except Exception:
            pass

    return Tier.FREE


def require_tier(min_tier: str | Tier, *, user_id: str | None = None) -> bool:
    target = Tier(min_tier) if isinstance(min_tier, str) else min_tier
    have = get_current_tier(user_id=user_id)
    return TIER_RANK[have] >= TIER_RANK[target]


def tier_gate(min_tier: str | Tier):
    """Decorator that raises PermissionError when the caller's tier is too low."""
    target = Tier(min_tier) if isinstance(min_tier, str) else min_tier

    def wrap(fn: Callable):
        def inner(*args, **kwargs):
            if not require_tier(target):
                raise PermissionError(
                    f"This feature requires {target.value} tier."
                )
            return fn(*args, **kwargs)
        return inner
    return wrap


# ── Stripe checkout ──────────────────────────────────────────────────────────

def start_subscription_checkout(tier: Tier, *, success_url: str, cancel_url: str) -> str:
    """Create a Stripe Checkout Session and return its URL."""
    if stripe is None or not stripe.api_key:
        raise RuntimeError("Stripe not configured. Set STRIPE_SECRET_KEY in .env.")
    price_id = PRICES.get(tier)
    if not price_id:
        raise RuntimeError(f"No Stripe price configured for {tier.value}.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url or ""


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Stripe webhook dispatcher — called from a FastAPI route or Flask app."""
    if stripe is None:
        return {"handled": False, "reason": "stripe-missing"}
    secret = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
    if not secret:
        return {"handled": False, "reason": "no-webhook-secret"}
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception as e:
        return {"handled": False, "reason": str(e)}

    event_type = event.get("type", "")
    if event_type.startswith("customer.subscription."):
        sub = event["data"]["object"]
        # Caller is expected to map sub.customer -> user_id and upsert users_subscription.
        return {"handled": True, "type": event_type, "subscription_id": sub.get("id")}
    return {"handled": False, "type": event_type}
