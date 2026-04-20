"""Wallet charge + policy + rollover tests."""

from __future__ import annotations

import pytest


def test_top_up_increases_balance(wallet_module):
    wallet_module.top_up(500, source="pytest")
    assert wallet_module.balance_cents() == 500


def test_charge_deducts(wallet_module):
    wallet_module.top_up(1000, source="pytest")
    entry = wallet_module.charge("other", 250, memo="coffee")
    assert entry.kind == "charge"
    assert entry.balance_after_cents == 750
    assert wallet_module.balance_cents() == 750


def test_charge_raises_when_insufficient(wallet_module):
    wallet_module.top_up(100)
    with pytest.raises(wallet_module.BudgetExceeded):
        wallet_module.charge("other", 500, memo="too much")
    # Denied charge is logged; balance intact.
    assert wallet_module.balance_cents() == 100


def test_try_charge_returns_none_on_deny(wallet_module):
    assert wallet_module.try_charge("other", 500) is None


def test_refund_returns_funds(wallet_module):
    wallet_module.top_up(500)
    wallet_module.charge("plugin", 300, memo="x")
    wallet_module.refund("plugin", 300, memo="reversal")
    assert wallet_module.balance_cents() == 500


def test_policy_per_day_cap(wallet_module):
    wallet_module.top_up(10_000)
    p = wallet_module.Policy(category="cloud_api", max_per_day_cents=100)
    wallet_module.add_policy(p)
    wallet_module.charge("cloud_api", 90, memo="ok")
    with pytest.raises(wallet_module.BudgetExceeded):
        wallet_module.charge("cloud_api", 50, memo="over")


def test_policy_requires_approval(wallet_module):
    wallet_module.top_up(10_000)
    p = wallet_module.Policy(category="plugin", require_approval_above_cents=100)
    wallet_module.add_policy(p)
    with pytest.raises(wallet_module.ConfirmRequired):
        wallet_module.charge("plugin", 500, memo="big plugin")
    # With approval it goes through.
    entry = wallet_module.charge("plugin", 500, memo="big plugin",
                                 approved_by="director")
    assert entry.kind == "charge"


def test_monthly_cap_enforced(wallet_module):
    wallet_module.set_cap(200)
    wallet_module.top_up(1000)
    wallet_module.charge("other", 150, memo="fine")
    with pytest.raises(wallet_module.BudgetExceeded):
        wallet_module.charge("other", 100, memo="over cap")


def test_summary_includes_policies(wallet_module):
    wallet_module.add_policy(wallet_module.Policy(category="subagent",
                                                  max_per_day_cents=200))
    s = wallet_module.summary()
    assert "policies" in s
    assert any(p["category"] == "subagent" for p in s["policies"])
