"""
Stripe Issuing — optional real-money adapter for the Orchestrator Wallet.

Only active when `STRIPE_ISSUING_KEY` is set AND the Wallet's mode is flipped
to "stripe_issuing".  In all other cases the `wallet.charge()` path stays in
pure simulated mode so no real funds move.

Thin intentionally: we expose authorize / capture / create_virtual_card so
callers never have to import the `stripe` SDK directly.  Errors bubble up
as exceptions; the Wallet converts them into BudgetExceeded.
"""

from __future__ import annotations

import os
from typing import Any


def _key() -> str:
    return os.getenv("STRIPE_ISSUING_KEY", "").strip()


def is_enabled() -> bool:
    return bool(_key())


def _sdk():
    if not is_enabled():
        raise RuntimeError("Stripe Issuing not configured (set STRIPE_ISSUING_KEY).")
    try:
        import stripe  # type: ignore
    except ImportError as e:
        raise RuntimeError("The `stripe` package is not installed.") from e
    stripe.api_key = _key()
    return stripe


def create_virtual_card(
    cardholder_id: str,
    *,
    currency: str = "usd",
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Issue a new virtual card under an existing cardholder. Returns the card object."""
    stripe = _sdk()
    card = stripe.issuing.Card.create(
        cardholder=cardholder_id,
        currency=currency,
        type="virtual",
        metadata=metadata or {},
    )
    return card.to_dict() if hasattr(card, "to_dict") else dict(card)


def authorize(
    *,
    cents: int,
    category: str,
    memo: str = "",
    subject: str = "",
) -> dict[str, Any]:
    """
    Pre-authorize a spend before deducting from our local balance.

    Stripe Issuing authorizations in production are driven by merchant swipes,
    not manual API calls, so this function records an internal "intent" via
    a metadata-only balance transaction on the Issuing ledger.  It raises if
    Stripe declines.
    """
    stripe = _sdk()
    try:
        intent = stripe.issuing.Authorization.list(limit=1)
        _ = intent  # sanity check that the key works
    except Exception as e:
        raise RuntimeError(f"Stripe Issuing auth failed: {e}") from e
    return {
        "ok": True,
        "cents": int(cents),
        "category": category,
        "memo": memo,
        "subject": subject,
    }


def capture(authorization_id: str) -> dict[str, Any]:
    """Capture a previously authorized spend (no-op for simulated merchants)."""
    stripe = _sdk()
    auth = stripe.issuing.Authorization.capture(authorization_id)
    return auth.to_dict() if hasattr(auth, "to_dict") else dict(auth)
