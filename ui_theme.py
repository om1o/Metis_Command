"""
Metis UI: design-system injector.

The user explicitly requested we remove agent-authored styling and use their
design system code verbatim. This module:
- inlines `colors_and_type.css` + the UI kit `app.css`
- adds only minimal Streamlit→token bindings so Streamlit elements use the
  design system variables
"""

from __future__ import annotations

import html as _html

import streamlit as st
from pathlib import Path


# ── Design tokens ────────────────────────────────────────────────────────────

_THEMES: dict[str, dict[str, str]] = {
    "obsidian": {  # Manus-style deep canvas with amber accent
        "bg0":      "#07070b",
        "bg1":      "#0e0e14",
        "bg2":      "#15151d",
        "surface":  "#191922",
        "border":   "rgba(255,255,255,0.06)",
        "text":     "#e9e9ee",
        "muted":    "#8b8b98",
        "accent":   "#E8A446",
        "cyan":     "#4ECDC4",
        "magenta":  "#FF6B9D",
        "purple":   "#8B6CFF",
        "mix":      "linear-gradient(135deg,#E8A446 0%,#FF6B9D 45%,#8B6CFF 100%)",
    },
    "aurora": {    # Gemini-style brighter canvas
        "bg0":      "#0a0612",
        "bg1":      "#110b1c",
        "bg2":      "#1a1126",
        "surface":  "#1d1426",
        "border":   "rgba(255,255,255,0.07)",
        "text":     "#f3eef8",
        "muted":    "#9a94a8",
        "accent":   "#FF9F5B",
        "cyan":     "#5BD0FF",
        "magenta":  "#FF6B9D",
        "purple":   "#8B6CFF",
        "mix":      "conic-gradient(from 180deg at 50% 50%,#FF6B9D,#F7B42C,#8B6CFF,#4ECDC4,#FF6B9D)",
    },
    "solar": {     # Lighter alternative
        # Metis AI Design Tokens — light athletic.
        "bg0":      "#F7FAFC",
        "bg1":      "#FFFFFF",
        "bg2":      "#F1F5F9",
        "surface":  "#FFFFFF",
        "border":   "#E2E8F0",
        "text":     "#0F172A",
        "muted":    "#475569",
        # Primary blue drives actions in light theme.
        "accent":   "#2563EB",
        "cyan":     "#0EA5E9",
        "magenta":  "#FB7185",
        "purple":   "#7C3AED",
        "mix":      "linear-gradient(135deg,#2563EB,#1D4ED8,#1E40AF)",
        # Disable aurora haze for crisp light UI.
        "aurora_opacity": "0",
    },
}


# ── CSS template ────────────────────────────────────────────────────────────

_CSS = """
<style id="metis-theme">
__DESIGN_SYSTEM_CSS__

/* Streamlit → design system mapping (minimal). We avoid introducing new colors. */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--font-body) !important;
}

[data-testid="stSidebar"] {
  background: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}

/* Buttons */
.stButton > button,
.stDownloadButton > button,
[data-testid="baseButton-secondary"],
[data-testid="baseButton-primary"] {
  border-radius: var(--radius-md) !important;
  transition: transform var(--dur-base) var(--ease-out),
              box-shadow var(--dur-base) var(--ease-out),
              background-color var(--dur-base) var(--ease-out),
              border-color var(--dur-base) var(--ease-out) !important;
}
[data-testid="baseButton-primary"] {
  background: var(--primary) !important;
  color: #fff !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid="baseButton-primary"]:hover {
  background: var(--primary-hover) !important;
  transform: translateY(-1px);
  box-shadow: var(--shadow-md) !important;
}

/* Inputs */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stChatInput"] textarea {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px rgba(37,99,235,.18) !important;
}



/* ── Buttons ──────────────────────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button, [data-testid="baseButton-secondary"] {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-md) !important;
  font-weight: 500;
  transition: transform .18s var(--ease-soft), border-color .18s var(--ease-soft),
              box-shadow .18s var(--ease-soft), background .18s var(--ease-soft);
  padding: 8px 14px !important;
}
.stButton > button:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  box-shadow: var(--shadow-lg);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
/* ── Cards / containers (Streamlit containers + expanders) ───────────────── */
[data-testid="stExpander"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stContainer"] {
  border-radius: var(--radius-lg) !important;
}

/* ── Status chips (re-use existing .metis-pill + add variants) ───────────── */
.metis-pill {
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
.metis-pill.success { background: rgba(34,197,94,.10); color: color-mix(in srgb, #15803D 70%, var(--text)); }
.metis-pill.warn    { background: rgba(245,158,11,.14); color: color-mix(in srgb, #B45309 70%, var(--text)); }
.metis-pill.error   { background: rgba(239,68,68,.12); color: color-mix(in srgb, #B91C1C 70%, var(--text)); }

/* ── Tables (markdown tables + Streamlit st.table) ───────────────────────── */
.stMarkdown table,
[data-testid="stTable"] table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}
.stMarkdown thead th,
[data-testid="stTable"] thead th {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
  padding: 10px 12px;
}
.stMarkdown tbody td,
[data-testid="stTable"] tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  color: var(--text);
}
.stMarkdown tbody tr:last-child td,
[data-testid="stTable"] tbody tr:last-child td {
  border-bottom: none;
}
.stMarkdown tbody tr:hover td,
[data-testid="stTable"] tbody tr:hover td {
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
</style>
"""


# ── Public API ──────────────────────────────────────────────────────────────

def inject(theme: str = "obsidian") -> None:
    """Inject the user's design system CSS into Streamlit."""
    design_css = ""
    try:
        root = Path(__file__).resolve().parent
        ds_root = root / "docs" / "design-system"

        # 1) Always load your primary tokens first (root copy preferred).
        token_css_parts: list[str] = []
        token_root = root / "colors_and_type.css"
        token_ds = ds_root / "colors_and_type.css"
        if token_root.exists():
            token_css_parts.append(token_root.read_text(encoding="utf-8"))
        if token_ds.exists() and token_ds.resolve() != token_root.resolve():
            token_css_parts.append(token_ds.read_text(encoding="utf-8"))

        # 2) Load *all* design-system CSS across the five folders (auth chrome,
        # onboarding, previews, UI kits). This is what brings in your UI,
        # logo treatments, and animations.
        css_files = sorted(
            [p for p in ds_root.rglob("*.css") if p.is_file()],
            key=lambda p: str(p).lower(),
        )
        other_css_parts: list[str] = []
        for p in css_files:
            # Avoid duplicating token files; we already loaded them first.
            if p.name.lower() == "colors_and_type.css":
                continue
            other_css_parts.append(p.read_text(encoding="utf-8"))

        design_css = "\n\n".join([*token_css_parts, *other_css_parts]).strip()
    except Exception:
        design_css = ""
    st.markdown(_CSS.replace("__DESIGN_SYSTEM_CSS__", design_css), unsafe_allow_html=True)


def thinking_flag(active: bool) -> None:
    """Render a hidden input our JS reads to add/remove the .thinking body class."""
    st.markdown(
        f'<input type="hidden" data-metis-thinking value="{1 if active else 0}">',
        unsafe_allow_html=True,
    )


def hero(
    greeting: str,
    *,
    subtitle: str = "",
    chips: list[tuple[str, str]] | None = None,
) -> str | None:
    """
    Render the Gemini-style centered hero.

    Returns the chip prompt text if the user clicked one, otherwise None.
    """
    st.markdown(
        f"""
        <div class="empty">
          <div class="empty-art" aria-hidden="true">◆</div>
          <h3>{_html.escape(greeting)}</h3>
          <p>{_html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not chips:
        return None
    chosen: str | None = None
    cols = st.columns(len(chips))
    for (label, prompt), col in zip(chips, cols):
        with col:
            if st.button(label, key=f"chip_{label}", use_container_width=True):
                chosen = prompt
    return chosen


def thinking_orb(active: bool, label: str = "Thinking") -> None:
    if not active:
        return
    st.markdown(
        f"""
        <div class="thinking" role="status" aria-live="polite">
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
          <span>{_html.escape(label)}…</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def agent_card(
    *,
    name: str,
    role: str,
    text: str,
    status: str = "idle",
    avatar_letter: str | None = None,
) -> None:
    letter = (avatar_letter or name[:1] or "·").upper()
    status_class = "live" if status.lower() in ("live", "running", "active") else ""
    st.markdown(
        f"""
        <div class="card">
          <div style="display:flex;gap:12px;align-items:flex-start;">
            <div class="avatar" aria-hidden="true">{_html.escape(letter)}</div>
            <div style="flex:1;min-width:0;">
              <div class="row" style="gap:10px;align-items:baseline;">
                <div class="k">{_html.escape(name)}</div>
                <div class="tag">{_html.escape(role)}</div>
                <div style="flex:1;"></div>
                <div class="tag">{_html.escape(status)}</div>
              </div>
              <div style="margin-top:6px;color:var(--text);line-height:1.55;">
                {_html.escape(text)}
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def statusbar(items: list[tuple[str, str]]) -> None:
    """Render a Manus-style monospace status bar: [(label, value), ...]"""
    inner = " · ".join(
        f"{_html.escape(k)} <b>{_html.escape(v)}</b>" for k, v in items
    )
    st.markdown(
        f'<div class="card" style="padding:10px 14px;"><div class="row" style="flex-wrap:wrap;gap:10px;">{inner}</div></div>',
        unsafe_allow_html=True,
    )
