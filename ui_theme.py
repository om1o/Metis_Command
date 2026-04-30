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


# ── CSS template ────────────────────────────────────────────────────────────

_CSS = """
<style id="metis-theme">
__DESIGN_SYSTEM_CSS__

/* Legacy variable aliases (keep existing UI markup working while we migrate). */
:root{
  --metis-text: var(--text);
  --metis-muted: var(--text-muted);
  --metis-subtle: var(--text-subtle);
  --metis-surface: var(--surface);
  --metis-border: var(--border);
  --metis-accent: var(--primary);
  --metis-cyan: var(--info);
  --bg-2: var(--surface-alt);
  --ease-soft: var(--ease-out);
  --accent: var(--primary);
}

/* ═════════════════════════════════════════════════════════════════════
   Streamlit → Design System mapping
   Maps Streamlit's auto-generated elements to the design-kit tokens.
   ═════════════════════════════════════════════════════════════════════ */

/* ── Global background + type ──────────────────────────────────── */
html, body, [data-testid=”stAppViewContainer”] {
  background:
    radial-gradient(circle at 15% -10%, rgba(124, 58, 237, 0.07), transparent 50%),
    radial-gradient(circle at 90% 10%, rgba(251, 113, 133, 0.06), transparent 55%),
    var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--font-body) !important;
  -webkit-font-smoothing: antialiased;
}

/* ── Page width / breathing room ───────────────────────────────── */
[data-testid=”stAppViewContainer”] > .main .block-container {
  max-width: 1380px !important;
  padding-top: 2.2rem !important;
  padding-bottom: 2.2rem !important;
  padding-left: 2.25rem !important;
  padding-right: 2.25rem !important;
}

/* ── Sidebar ───────────────────────────────────────────────────── */
[data-testid=”stSidebar”] {
  background: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid=”stSidebar”] [data-testid=”stMarkdown”] p {
  font-size: 14px;
  line-height: 1.55;
}

/* ── Chat header “aura” ────────────────────────────────────────── */
.metis-aura {
  width: 88px;
  height: 88px;
  margin: 0 auto;
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.14), rgba(251, 113, 133, 0.1));
  animation: metis-aura-pulse 3.2s var(--ease-in-out) infinite;
}
.metis-thinking .metis-aura {
  animation: metis-aura-pulse 1.35s var(--ease-in-out) infinite;
}
.metis-core {
  font-size: 36px;
  line-height: 1;
  background: var(--heritage-grad);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 10px 24px rgba(124, 58, 237, 0.22));
  animation: metis-bob 6s ease-in-out infinite;
}
@keyframes metis-aura-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.08); transform: scale(1); }
  50% { box-shadow: 0 0 42px 10px rgba(124, 58, 237, 0.2); transform: scale(1.03); }
}
@keyframes metis-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

/* ── Buttons (Streamlit native) ────────────────────────────────── */
.stButton > button,
.stDownloadButton > button,
[data-testid=”baseButton-secondary”] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-body) !important;
  font-weight: 650 !important;
  font-size: 14px !important;
  letter-spacing: -0.005em;
  padding: 10px 16px !important;
  transition: transform var(--dur-base) var(--ease-out),
              box-shadow var(--dur-base) var(--ease-out),
              background-color var(--dur-base) var(--ease-out),
              border-color var(--dur-base) var(--ease-out) !important;
}
.stButton > button:hover,
.stDownloadButton > button:hover,
[data-testid=”baseButton-secondary”]:hover {
  transform: translateY(-1px);
  border-color: var(--border-strong) !important;
  background: var(--surface-alt) !important;
  box-shadow: var(--shadow-md) !important;
}
[data-testid=”baseButton-primary”] {
  background: var(--primary) !important;
  color: #fff !important;
  border-color: var(--primary) !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid=”baseButton-primary”]:hover {
  background: var(--primary-hover) !important;
  transform: translateY(-1px);
  box-shadow: var(--shadow-md) !important;
}
[data-testid=”baseButton-primary”]:active {
  background: var(--primary-press) !important;
  transform: translateY(0);
}

/* ── Inputs (Streamlit native) ─────────────────────────────────── */
[data-testid=”stTextInput”] input,
[data-testid=”stTextArea”] textarea,
[data-testid=”stNumberInput”] input,
[data-testid=”stChatInput”] textarea {
  font-family: var(--font-body) !important;
  font-size: 14px !important;
  padding: 10px 12px !important;
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
  transition: border-color var(--dur-base), box-shadow var(--dur-base) !important;
}
[data-testid=”stTextInput”] input::placeholder,
[data-testid=”stTextArea”] textarea::placeholder,
[data-testid=”stChatInput”] textarea::placeholder {
  color: var(--text-subtle) !important;
}
[data-testid=”stTextInput”] input:focus,
[data-testid=”stTextArea”] textarea:focus,
[data-testid=”stChatInput”] textarea:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px rgba(37,99,235,.18) !important;
  outline: none !important;
}

/* ── Chat input composer feel ──────────────────────────────────── */
[data-testid=”stChatInput”] {
  border-radius: 16px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  box-shadow: var(--shadow-md) !important;
  padding: 4px !important;
}

/* ── Chat messages (design-kit bubble style) ───────────────────── */
[data-testid=”stChatMessage”] {
  border-radius: 16px !important;
  padding: 12px 16px !important;
  font-size: 14.5px !important;
  line-height: 1.55 !important;
  margin-bottom: 8px !important;
  max-width: 88%;
  border: none !important;
  box-shadow: none !important;
}
[data-testid=”stChatMessage”][data-testid*=”user”],
[data-testid=”stChatMessage”]:has([data-testid=”chatAvatarIcon-user”]) {
  background: var(--primary) !important;
  color: #fff !important;
  border-bottom-right-radius: 4px !important;
  align-self: flex-end;
  margin-left: auto;
}
[data-testid=”stChatMessage”]:has([data-testid=”chatAvatarIcon-user”]) p,
[data-testid=”stChatMessage”]:has([data-testid=”chatAvatarIcon-user”]) span {
  color: #fff !important;
}
[data-testid=”stChatMessage”]:has([data-testid=”chatAvatarIcon-assistant”]) {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  color: var(--text) !important;
  border-bottom-left-radius: 4px !important;
  box-shadow: var(--shadow-xs) !important;
}
[data-testid=”stChatMessage”]:has([data-testid=”chatAvatarIcon-assistant”]) code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  background: var(--surface-alt);
  padding: 1px 6px;
  border-radius: 5px;
}

/* ── Cards / containers / expanders ────────────────────────────── */
[data-testid=”stExpander”] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid=”stExpander”] summary {
  font-weight: 600 !important;
  font-size: 14px !important;
}
[data-testid=”stVerticalBlockBorderWrapper”] {
  border-radius: var(--radius-lg) !important;
}

/* ── Selectbox / dropdown ──────────────────────────────────────── */
[data-testid=”stSelectbox”] [data-baseweb=”select”] {
  border-radius: var(--radius-md) !important;
}

/* ── Toggle switches ──────────────────────────────────────────── */
[data-testid=”stToggle”] label {
  font-size: 14px !important;
  font-weight: 500 !important;
}

/* ── Tabs (design-kit style) ──────────────────────────────────── */
[data-testid=”stTabs”] [role=”tablist”] {
  gap: 4px !important;
  border-bottom: 1px solid var(--border) !important;
}
[data-testid=”stTabs”] [role=”tab”] {
  font-weight: 600 !important;
  font-size: 14px !important;
  color: var(--text-muted) !important;
  padding: 10px 14px !important;
  border-bottom: 2px solid transparent !important;
}
[data-testid=”stTabs”] [role=”tab”]:hover {
  color: var(--text) !important;
}
[data-testid=”stTabs”] [role=”tab”][aria-selected=”true”] {
  color: var(--primary) !important;
  border-bottom-color: var(--primary) !important;
}

/* ── File uploader ─────────────────────────────────────────────── */
[data-testid=”stFileUploader”] {
  border-radius: var(--radius-lg) !important;
}
[data-testid=”stFileUploader”] section {
  border: 1px dashed var(--border) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--surface) !important;
}

/* ── Progress bar ──────────────────────────────────────────────── */
[data-testid=”stProgress”] > div {
  border-radius: 999px !important;
  height: 6px !important;
}

/* ── Toast / notification ──────────────────────────────────────── */
.stToast {
  background: var(--text) !important;
  color: #fff !important;
  border-radius: 12px !important;
  box-shadow: var(--shadow-lg) !important;
  font-size: 13.5px !important;
}

/* ── Tables ────────────────────────────────────────────────────── */
.stMarkdown table,
[data-testid=”stTable”] table {
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
[data-testid=”stTable”] thead th {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  background: var(--surface-alt);
  border-bottom: 1px solid var(--border);
  padding: 10px 12px;
}
.stMarkdown tbody td,
[data-testid=”stTable”] tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  color: var(--text);
}
.stMarkdown tbody tr:last-child td,
[data-testid=”stTable”] tbody tr:last-child td {
  border-bottom: none;
}
.stMarkdown tbody tr:hover td,
[data-testid=”stTable”] tbody tr:hover td {
  background: color-mix(in srgb, var(--primary) 6%, var(--surface));
}

/* ── Code blocks ───────────────────────────────────────────────── */
[data-testid=”stCode”],
.stMarkdown pre {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border) !important;
  font-family: var(--font-mono) !important;
  font-size: 13px !important;
}

/* ── Metric cards ──────────────────────────────────────────────── */
[data-testid=”stMetric”] {
  font-family: var(--font-display) !important;
}
[data-testid=”stMetricValue”] {
  font-family: var(--font-display) !important;
  font-weight: 750 !important;
}
[data-testid=”stMetricLabel”] {
  font-family: var(--font-mono) !important;
  font-size: 10.5px !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  color: var(--text-subtle) !important;
}

/* ── Auth page spacing ─────────────────────────────────────────── */
[data-testid=”stVerticalBlock”] [data-testid=”stContainer”] {
  margin-top: 0.4rem;
}
[data-testid=”stTextInput”],
[data-testid=”stButton”],
[data-testid=”stLinkButton”] {
  margin-bottom: 0.3rem;
}
</style>
"""


# ── Public API ──────────────────────────────────────────────────────────────

# Module-level CSS payload cache — built once per process, never re-reads disk.
_CSS_PAYLOAD_CACHE: dict[str, str] = {}


def _build_css_payload(theme: str) -> str:  # noqa: ARG001  (theme reserved for future per-theme tokens)
    """Read all design-system CSS files and return the full <style> payload."""
    design_css = ""
    try:
        root = Path(__file__).resolve().parent
        ds_root = root / "assets" / "design-system"

        token_css_parts: list[str] = []
        token_root = root / "colors_and_type.css"
        token_ds = ds_root / "colors_and_type.css"
        if token_root.exists():
            token_css_parts.append(token_root.read_text(encoding="utf-8"))
        if token_ds.exists() and token_ds.resolve() != token_root.resolve():
            token_css_parts.append(token_ds.read_text(encoding="utf-8"))

        css_files = sorted(
            [p for p in ds_root.rglob("*.css") if p.is_file()],
            key=lambda p: str(p).lower(),
        )
        other_css_parts: list[str] = []
        for p in css_files:
            if p.name.lower() == "colors_and_type.css":
                continue
            css = p.read_text(encoding="utf-8")
            css = "\n".join(
                ln for ln in css.splitlines()
                if not ln.lstrip().lower().startswith("@import ")
            )
            other_css_parts.append(css)

        design_css = "\n\n".join([*token_css_parts, *other_css_parts]).strip()
    except Exception:
        design_css = ""
    return _CSS.replace("__DESIGN_SYSTEM_CSS__", design_css)


def inject(theme: str = "obsidian") -> None:
    """Inject the user's design system CSS into Streamlit.

    The CSS payload is built once per server process and cached in
    ``_CSS_PAYLOAD_CACHE`` so that Streamlit reruns don't re-read
    every design-system file from disk each time.
    """
    if theme not in _CSS_PAYLOAD_CACHE:
        _CSS_PAYLOAD_CACHE[theme] = _build_css_payload(theme)
    payload = _CSS_PAYLOAD_CACHE[theme]
    if hasattr(st, "html"):
        st.html(payload)
    else:
        st.markdown(payload, unsafe_allow_html=True)


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
    root = Path(__file__).resolve().parent
    logo_png = root / "assets" / "design-system" / "assets" / "metis-logomark.png"
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        if logo_png.exists():
            st.image(str(logo_png), width=96)
        st.markdown(
            f"""
            <div class="empty" style="padding-top:8px;">
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
    # Map status → chip variant
    chip_class = {
        "live": "chip-running", "running": "chip-running",
        "idle": "chip-ready", "error": "chip-failed",
    }.get(status, "chip-ready")
    chip_label = _html.escape(status.capitalize())
    st.markdown(
        f"""
        <div class="card" style="padding:16px;margin-bottom:8px;">
          <div style="display:flex;gap:12px;align-items:flex-start;">
            <div class="avatar" aria-hidden="true">{_html.escape(letter)}</div>
            <div style="flex:1;min-width:0;">
              <div class="row" style="gap:10px;align-items:center;">
                <span style="font-family:var(--font-display);font-size:15px;font-weight:700;color:var(--text);">{_html.escape(name)}</span>
                <span class="chip chip-ready" style="font-size:11px;">{_html.escape(role)}</span>
                <div style="flex:1;"></div>
                <span class="chip {chip_class}"><span class="chip-dot"></span>{chip_label}</span>
              </div>
              <div style="margin-top:6px;color:var(--text-muted);font-size:13.5px;line-height:1.55;">
                {_html.escape(text)}
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def statusbar(items: list[tuple[str, str]]) -> None:
    """Render a design-kit monospace status bar: [(label, value), ...]"""
    inner = " · ".join(
        f"<span style='font-family:var(--font-mono);font-size:11px;letter-spacing:0.04em;"
        f"text-transform:uppercase;color:var(--text-subtle);'>{_html.escape(k)}</span>"
        f" <b style='font-family:var(--font-mono);font-size:12px;"
        f"font-feature-settings:\"tnum\" 1,\"lnum\" 1;color:var(--text);'>{_html.escape(v)}</b>"
        for k, v in items
    )
    st.markdown(
        f'<div class="card" style="padding:10px 14px;margin-top:12px;">'
        f'<div class="row" style="flex-wrap:wrap;gap:10px;justify-content:center;">{inner}</div></div>',
        unsafe_allow_html=True,
    )
