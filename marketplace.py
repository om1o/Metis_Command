"""
Marketplace — Metis plugin store UI and Stripe checkout flow.

Plugins live as rows in Supabase `plugins_store` with fields:
    slug, name, description, price_cents, tier_required, icon, download_url

Free plugins download immediately into plugins/<slug>.py.  Paid plugins
kick off a Stripe Checkout session; on success the webhook flips the
`purchases` row and the UI auto-installs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from subscription import Tier, get_current_tier, start_subscription_checkout

PLUGINS_DIR = Path("plugins")


# ── Data access ──────────────────────────────────────────────────────────────

def list_plugins() -> list[dict]:
    try:
        from supabase_client import get_client
        response = (
            get_client()
            .table("plugins_store")
            .select("*")
            .eq("enabled", True)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []
    except Exception:
        return _builtin_catalog()


def _builtin_catalog() -> list[dict]:
    """Fallback catalog — the 5 launch plugins already seeded in plugins/."""
    return [
        {
            "slug": "stock_terminal",
            "name": "Stock Terminal",
            "description": "Live market quotes via Yahoo Finance API.",
            "price_cents": 0,
            "tier_required": "Free",
            "icon": "📈",
        },
        {
            "slug": "stealth_scraper",
            "name": "Stealth Web Scraper",
            "description": "Playwright-based headless browser scraping.",
            "price_cents": 0,
            "tier_required": "Pro",
            "icon": "🕵️",
        },
        {
            "slug": "discord_automator",
            "name": "Discord Automator",
            "description": "Post, edit, and schedule Discord messages.",
            "price_cents": 999,
            "tier_required": "Free",
            "icon": "💬",
        },
        {
            "slug": "crypto_analyst",
            "name": "Crypto Analyst",
            "description": "CoinGecko prices + simple sentiment take.",
            "price_cents": 0,
            "tier_required": "Free",
            "icon": "🪙",
        },
        {
            "slug": "spotify_controller",
            "name": "Spotify Controller",
            "description": "Play, pause, queue, and search Spotify.",
            "price_cents": 499,
            "tier_required": "Free",
            "icon": "🎵",
        },
    ]


# ── Install helpers ──────────────────────────────────────────────────────────

def install_plugin(plugin: dict) -> bool:
    """Download and register a plugin locally."""
    slug = plugin.get("slug") or ""
    if not slug:
        return False
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    dest = PLUGINS_DIR / f"{slug}.py"
    url = plugin.get("download_url") or ""
    try:
        if url:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            dest.write_text(r.text, encoding="utf-8")
        # If no URL, we assume the plugin was already seeded locally.
        try:
            from skill_forge import save_skill_to_db
            if dest.exists():
                save_skill_to_db(slug, plugin.get("description", ""), dest.read_text("utf-8"))
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[Marketplace] install({slug}) failed: {e}")
        return False


def _purchase(plugin: dict) -> None:
    tier_needed = Tier(plugin.get("tier_required", "Free"))
    current = get_current_tier()
    if current == Tier.FREE and tier_needed != Tier.FREE:
        st.warning(f"{plugin['name']} requires {tier_needed.value} tier.")
        return

    price_cents = int(plugin.get("price_cents") or 0)
    if price_cents <= 0:
        ok = install_plugin(plugin)
        st.toast("Installed." if ok else "Install failed.",
                 icon="✅" if ok else "⚠️")
        return

    # Ask the Orchestrator Wallet first. If it can cover the cost (or policy
    # demands approval), we short-circuit Stripe Checkout.
    try:
        from wallet import try_charge, can_spend
        allowed, reason = can_spend("plugin", price_cents)
        if allowed:
            entry = try_charge(
                "plugin",
                price_cents,
                memo=f"plugin:{plugin.get('slug','')}",
                subject=plugin.get("slug", ""),
            )
            if entry is not None:
                ok = install_plugin(plugin)
                st.toast("Paid from wallet & installed." if ok else "Wallet OK, install failed.",
                         icon="✅" if ok else "⚠️")
                return
        elif reason:
            st.caption(f"Wallet can't cover this ({reason}); falling back to Stripe.")
    except Exception:
        pass

    try:
        url = start_subscription_checkout(
            tier_needed,
            success_url=(
                f"http://localhost:{os.getenv('METIS_API_PORT', '7331')}/app?checkout=success"
            ),
            cancel_url=(
                f"http://localhost:{os.getenv('METIS_API_PORT', '7331')}/app?checkout=cancel"
            ),
        )
        st.link_button("Open Stripe Checkout", url)
    except Exception as e:
        st.error(f"Checkout unavailable: {e}")


# ── UI ───────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _cached_storefront_plugins() -> list[dict]:
    """Cache the plugin catalog locally so the storefront doesn't hit
    Supabase on every Streamlit rerun. Cleared explicitly on install."""
    return list_plugins() or []


def render_storefront() -> None:
    st.markdown("### Metis Marketplace")
    st.caption(
        f"Current tier: **{get_current_tier().value}** · "
        "Install skills the swarm can invoke on demand."
    )

    cols_top = st.columns([3, 1])
    with cols_top[1]:
        if st.button("Refresh", key="mkt_refresh", use_container_width=True,
                     icon=":material/refresh:"):
            _cached_storefront_plugins.clear()
            st.rerun()

    plugins = _cached_storefront_plugins()
    if not plugins:
        st.caption("No plugins available right now.")
        return

    cols = st.columns(2)
    for i, p in enumerate(plugins):
        col = cols[i % 2]
        with col.container(border=True):
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;'>"
                f"<div style='font-size:22px;'>{p.get('icon','🧩')}</div>"
                f"<div><b>{p['name']}</b><br>"
                f"<span style='font-size:12px;color:var(--metis-muted);'>"
                f"{p.get('tier_required','Free')} tier</span></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.caption(p.get("description", ""))
            price_cents = int(p.get("price_cents") or 0)
            free = price_cents == 0
            label = "Install" if free else f"Buy · ${price_cents/100:.2f}"
            icon = ":material/download:" if free else ":material/shopping_cart:"
            if st.button(label, key=f"mkt_{p['slug']}", use_container_width=True, icon=icon):
                _purchase(p)
                _cached_storefront_plugins.clear()
