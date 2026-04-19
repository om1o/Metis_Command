"""
Metis UI theme + animations — Gemini × Manus hybrid.

Injects a single <style> + <script> block into the Streamlit app that:
  - paints a low-intensity aurora gradient canvas (4-stop conic, 36s rotation)
  - rewires typography to Inter + Instrument Serif + JetBrains Mono
  - gives every interactive element a soft shadow, 16px radius, hover lift
  - animates the ◆ gem logo with a breathing + rotating aura ONLY while
    `thinking_flag(True)` has been set for the current turn
  - provides reusable animation classes:
        .metis-fade-up   message entry
        .metis-shimmer   loading text
        .metis-breath    pulsing orb
        .metis-chip      Gemini-style suggestion pill

Public API:
    inject(theme="obsidian" | "aurora" | "solar")
    thinking_flag(active)                           — toggles body.thinking
    hero(greeting, subtitle="", chips=[(label, prompt)])   -> chosen prompt | None
    thinking_orb(active, label="Thinking")
    agent_card(name=, role=, text=, status="idle", avatar_letter=None)
    statusbar([(label, value), ...])
"""

from __future__ import annotations

import html as _html

import streamlit as st


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
        "bg0":      "#fafaf8",
        "bg1":      "#ffffff",
        "bg2":      "#f3f1ec",
        "surface":  "#ffffff",
        "border":   "rgba(0,0,0,0.06)",
        "text":     "#1a1a22",
        "muted":    "#5f5f6b",
        "accent":   "#E8A446",
        "cyan":     "#0BA5A4",
        "magenta":  "#D6336C",
        "purple":   "#5B3EFF",
        "mix":      "linear-gradient(135deg,#E8A446,#D6336C,#5B3EFF)",
    },
}


# ── CSS template ────────────────────────────────────────────────────────────

_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">

<style id="metis-theme">
:root {
  --bg-0:        __BG0__;
  --bg-1:        __BG1__;
  --bg-2:        __BG2__;
  --surface:     __SURFACE__;
  --border:      __BORDER__;
  --text:        __TEXT__;
  --muted:       __MUTED__;
  --accent:      __ACCENT__;
  --cyan:        __CYAN__;
  --magenta:     __MAGENTA__;
  --purple:      __PURPLE__;
  --mix:         __MIX__;
  --radius-sm:   10px;
  --radius-md:   16px;
  --radius-lg:   24px;
  --ease-soft:   cubic-bezier(.2,.8,.2,1);
  --shadow-sm:   0 1px 2px rgba(0,0,0,0.25);
  --shadow-md:   0 8px 28px rgba(0,0,0,0.35);
  --shadow-glow: 0 0 40px rgba(232,164,70,0.12);
}

html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-0) !important;
  color: var(--text) !important;
  font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif !important;
  font-feature-settings: "ss01", "cv11";
  letter-spacing: -0.005em;
}

/* ── Aurora canvas (low-opacity conic gradient painted behind everything) ─ */
[data-testid="stAppViewContainer"]::before {
  content: "";
  position: fixed; inset: -30vmax;
  z-index: 0; pointer-events: none;
  background: var(--mix);
  filter: blur(120px) saturate(120%);
  opacity: 0.18;
  animation: metis-aurora 36s linear infinite;
  will-change: transform;
}
@keyframes metis-aurora {
  0%   { transform: rotate(0deg)   translate(0,0); }
  50%  { transform: rotate(180deg) translate(2vw,-3vh); }
  100% { transform: rotate(360deg) translate(0,0); }
}

[data-testid="stAppViewContainer"] > .main,
[data-testid="stSidebarContent"] {
  position: relative; z-index: 1;
}

/* ── Sidebar ──────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg,var(--bg-1) 0%,var(--bg-0) 100%) !important;
  border-right: 1px solid var(--border);
  backdrop-filter: blur(8px);
}
[data-testid="stSidebar"] .metis-pill {
  display:inline-flex;align-items:center;gap:6px;
  padding: 2px 10px; border-radius: 999px;
  font-size:11px; font-weight:500; letter-spacing:.02em;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  color: var(--text);
}
[data-testid="stSidebar"] .metis-pill.muted { color: var(--muted); }
[data-testid="stSidebar"] .metis-side-heading {
  font-size:10.5px; font-weight:600; letter-spacing:.14em;
  text-transform:uppercase; color: var(--muted);
  margin: 14px 4px 8px;
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
  box-shadow: var(--shadow-md);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
.stButton > button:active { transform: translateY(0); }

[data-testid="baseButton-primary"] {
  background: var(--mix) !important;
  color: #0a0a0a !important;
  border: none !important;
  font-weight: 600 !important;
  box-shadow: var(--shadow-md), var(--shadow-glow);
}

/* ── Chat bubbles ─────────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
  animation: metis-fade-up .35s var(--ease-soft) both;
  border-radius: var(--radius-md);
  padding: 14px 18px !important;
  margin-bottom: 10px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter: blur(6px);
}
[data-testid="stChatMessage"][data-testid*="assistant"] {
  background: linear-gradient(180deg,
    color-mix(in srgb, var(--surface) 94%, transparent),
    color-mix(in srgb, var(--bg-2) 94%, transparent));
  border: 1px solid color-mix(in srgb, var(--accent) 18%, var(--border));
}
@keyframes metis-fade-up {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.metis-fade-up { animation: metis-fade-up .35s var(--ease-soft) both; }

/* ── Input bar ────────────────────────────────────────────────────────────── */
[data-testid="stChatInput"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 22px !important;
  box-shadow: var(--shadow-md);
  transition: border-color .18s var(--ease-soft), box-shadow .18s var(--ease-soft);
}
[data-testid="stChatInput"]:focus-within {
  border-color: color-mix(in srgb, var(--accent) 60%, var(--border)) !important;
  box-shadow: 0 8px 28px rgba(0,0,0,.35),
              0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}
[data-testid="stChatInput"] textarea {
  background: transparent !important;
  color: var(--text) !important;
  font-family: 'Inter', system-ui, sans-serif !important;
  font-size: 15px !important;
}

/* ── Hero empty state ─────────────────────────────────────────────────────── */
.metis-hero {
  display:flex; flex-direction:column; align-items:center;
  gap: 14px; padding: 40px 16px 28px;
  animation: metis-fade-up .6s var(--ease-soft) both;
}
.metis-hero-title {
  font-family: 'Instrument Serif', Georgia, serif;
  font-weight: 400; font-size: 54px; line-height: 1.05;
  letter-spacing: -0.02em; text-align: center;
  background: var(--mix);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}
.metis-hero-sub {
  font-size: 14px; color: var(--muted);
  max-width: 520px; text-align:center;
}

/* ── Chips / pills ────────────────────────────────────────────────────────── */
.metis-chip-row {
  display:flex; flex-wrap:wrap; gap:10px;
  justify-content:center; margin-top: 10px;
}

/* ── Logo gem + breathing aura (only spins while .thinking) ───────────────── */
.metis-gem {
  display:inline-flex; align-items:center; justify-content:center;
  width: 30px; height: 30px; border-radius: 50%;
  background: radial-gradient(circle at 30% 30%,
              color-mix(in srgb, var(--accent) 40%, transparent), transparent 60%);
  color: var(--accent);
  font-family: 'JetBrains Mono', monospace;
  font-size: 19px;
  position: relative;
}
.metis-gem::after {
  content: "";
  position: absolute; inset: -6px; border-radius: 50%;
  background: conic-gradient(from 0deg,
              color-mix(in srgb, var(--magenta) 40%, transparent),
              color-mix(in srgb, var(--accent)  40%, transparent),
              color-mix(in srgb, var(--purple)  40%, transparent),
              color-mix(in srgb, var(--cyan)    40%, transparent),
              color-mix(in srgb, var(--magenta) 40%, transparent));
  filter: blur(8px);
  opacity: 0;
  transition: opacity .4s var(--ease-soft);
}
.thinking .metis-gem::after {
  opacity: .9; animation: metis-spin 6s linear infinite;
}
@keyframes metis-spin { to { transform: rotate(360deg); } }

/* ── Thinking orb (used when streaming) ───────────────────────────────────── */
.metis-breath {
  display:inline-block;
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--mix);
  box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 60%, transparent);
  animation: metis-breath 2.4s var(--ease-soft) infinite;
  margin-right: 8px; vertical-align: middle;
}
@keyframes metis-breath {
  0%,100% { transform: scale(.85); opacity: .6; }
  50%     { transform: scale(1.15); opacity: 1;  }
}
.metis-shimmer {
  background: linear-gradient(90deg,
      var(--muted) 0%, var(--text) 50%, var(--muted) 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
  animation: metis-shimmer 2.2s ease-in-out infinite;
  font-weight: 500;
}
@keyframes metis-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ── Mission / Agent cards ────────────────────────────────────────────────── */
.metis-agent-card {
  display:flex; gap:14px; align-items:flex-start;
  padding: 14px 16px; border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--surface) 94%, transparent);
  border: 1px solid var(--border);
  transition: transform .18s var(--ease-soft), border-color .18s var(--ease-soft),
              box-shadow .18s var(--ease-soft);
  margin-bottom: 8px;
}
.metis-agent-card:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
  box-shadow: var(--shadow-md);
}
.metis-avatar {
  width: 34px; height: 34px; border-radius: 50%;
  display:flex; align-items:center; justify-content:center;
  font-family: 'Instrument Serif', serif; font-size: 17px;
  color: #0a0a0a; flex-shrink:0;
  background: var(--mix);
  box-shadow: 0 0 0 1px var(--border);
}
.metis-agent-meta { flex:1; min-width:0; }
.metis-agent-name { font-weight: 600; font-size: 14px; color: var(--text); }
.metis-agent-role { font-size: 11.5px; color: var(--muted); letter-spacing:.04em; text-transform:uppercase; }
.metis-agent-body { font-size: 13.5px; color: var(--text); margin-top: 4px; line-height: 1.5; }
.metis-agent-status {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  font-family: 'JetBrains Mono', monospace;
  background: color-mix(in srgb, var(--cyan) 15%, transparent);
  color: var(--cyan);
  border: 1px solid color-mix(in srgb, var(--cyan) 25%, transparent);
}
.metis-agent-status.live { background: color-mix(in srgb, var(--accent) 15%, transparent);
                           color: var(--accent);
                           border-color: color-mix(in srgb, var(--accent) 30%, transparent); }

/* ── Status bar ───────────────────────────────────────────────────────────── */
.metis-statusbar {
  display:flex; gap:14px; align-items:center;
  padding: 6px 14px; border-radius: 999px;
  background: color-mix(in srgb, var(--surface) 94%, transparent);
  border: 1px solid var(--border);
  backdrop-filter: blur(8px);
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: var(--muted);
}
.metis-statusbar b { color: var(--text); font-weight: 500; }

/* ── Code blocks ──────────────────────────────────────────────────────────── */
pre, code, .stMarkdown pre {
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
  font-size: 13px !important;
}
pre {
  border-radius: var(--radius-sm) !important;
  border: 1px solid var(--border) !important;
  background: var(--bg-2) !important;
}

/* ── Reduce motion for accessibility ──────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001s !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001s !important;
  }
}
</style>
"""


# ── Public API ──────────────────────────────────────────────────────────────

def inject(theme: str = "obsidian") -> None:
    """Inject the Metis theme CSS + thinking-class wiring script."""
    tokens = _THEMES.get(theme, _THEMES["obsidian"])
    css = _CSS
    for key, val in {
        "__BG0__":     tokens["bg0"],
        "__BG1__":     tokens["bg1"],
        "__BG2__":     tokens["bg2"],
        "__SURFACE__": tokens["surface"],
        "__BORDER__":  tokens["border"],
        "__TEXT__":    tokens["text"],
        "__MUTED__":   tokens["muted"],
        "__ACCENT__":  tokens["accent"],
        "__CYAN__":    tokens["cyan"],
        "__MAGENTA__": tokens["magenta"],
        "__PURPLE__":  tokens["purple"],
        "__MIX__":     tokens["mix"],
    }.items():
        css = css.replace(key, val)
    st.markdown(css, unsafe_allow_html=True)

    # Small JS that watches the hidden thinking-flag input and toggles the
    # `.thinking` class on <body> so the gem's aura animates only while busy.
    st.markdown(
        """
        <script>
        (function(){
          const body = window.parent.document.body;
          const sync = () => {
            const flag = window.parent.document.querySelector(
                'input[data-metis-thinking]');
            const on = flag && flag.value === '1';
            body.classList.toggle('thinking', !!on);
          };
          new MutationObserver(sync).observe(
              window.parent.document.body,
              {childList:true, subtree:true, attributes:true, attributeFilter:['value']});
          sync();
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


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
        <div class="metis-hero">
            <div class="metis-gem">◆</div>
            <div class="metis-hero-title">{_html.escape(greeting)}</div>
            <div class="metis-hero-sub">{_html.escape(subtitle)}</div>
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
        f'<div class="metis-fade-up">'
        f'  <span class="metis-breath"></span>'
        f'  <span class="metis-shimmer">{_html.escape(label)}…</span>'
        f'</div>',
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
        <div class="metis-agent-card metis-fade-up">
          <div class="metis-avatar">{_html.escape(letter)}</div>
          <div class="metis-agent-meta">
            <div style="display:flex;gap:10px;align-items:center;">
              <div class="metis-agent-name">{_html.escape(name)}</div>
              <div class="metis-agent-role">{_html.escape(role)}</div>
              <div style="flex:1;"></div>
              <span class="metis-agent-status {status_class}">{_html.escape(status)}</span>
            </div>
            <div class="metis-agent-body">{_html.escape(text)}</div>
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
        f'<div class="metis-statusbar">{inner}</div>',
        unsafe_allow_html=True,
    )
