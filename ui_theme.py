"""
Metis UI theme — the Claude.ai + Codex CSS layer.

One function: inject(). Call it once per Streamlit rerun before anything else.
Keeps dynamic_ui.py focused on layout instead of CSS.
"""

from __future__ import annotations

import streamlit as st


CYAN = "#66FCF1"
PURPLE = "#9D7CFF"
OBSIDIAN = "#0B0C10"
SURFACE = "#121319"
SURFACE_2 = "#1A1B23"
BORDER = "rgba(255,255,255,0.08)"
TEXT = "#E8EAF0"
MUTED = "#8A8E9C"


CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Fira+Code:wght@400;500&display=swap');

:root {{
  --metis-cyan: {CYAN};
  --metis-purple: {PURPLE};
  --metis-bg: {OBSIDIAN};
  --metis-surface: {SURFACE};
  --metis-surface-2: {SURFACE_2};
  --metis-border: {BORDER};
  --metis-text: {TEXT};
  --metis-muted: {MUTED};
}}

html, body, .stApp {{
  background: radial-gradient(ellipse at top, #14151e 0%, {OBSIDIAN} 60%) !important;
  color: var(--metis-text) !important;
  font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif !important;
  font-size: 15.5px;
  line-height: 1.55;
}}

/* Tighten default Streamlit padding so the 3-column layout breathes */
section.main > div.block-container {{
  padding-top: 1.2rem !important;
  padding-bottom: 6rem !important;
  max-width: 100% !important;
}}

/* Hide Streamlit's default footer + hamburger, we have our own shell */
footer, #MainMenu, header[data-testid="stHeader"] {{
  visibility: hidden;
  height: 0;
}}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
  background: {SURFACE} !important;
  border-right: 1px solid var(--metis-border);
}}
section[data-testid="stSidebar"] .stButton > button {{
  background: transparent;
  border: 1px solid var(--metis-border);
  color: var(--metis-text);
  border-radius: 10px;
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  transition: all 0.15s ease;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
  border-color: var(--metis-cyan);
  background: rgba(102, 252, 241, 0.06);
}}

.metis-side-heading {{
  color: var(--metis-muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin: 14px 0 6px 4px;
}}
.metis-pill {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(102, 252, 241, 0.1);
  border: 1px solid rgba(102, 252, 241, 0.25);
  color: var(--metis-cyan);
  font-size: 11px;
  font-weight: 500;
}}
.metis-pill.purple {{
  background: rgba(157, 124, 255, 0.1);
  border-color: rgba(157, 124, 255, 0.3);
  color: var(--metis-purple);
}}
.metis-pill.muted {{
  background: rgba(255,255,255,0.04);
  border-color: var(--metis-border);
  color: var(--metis-muted);
}}

/* ── Chat messages ──────────────────────────────────────────────────────── */
div[data-testid="stChatMessage"] {{
  background: transparent !important;
  border: none !important;
  padding: 14px 4px !important;
}}
div[data-testid="stChatMessage"] p,
div[data-testid="stChatMessage"] li {{
  font-size: 15.5px;
  line-height: 1.6;
}}

/* User messages get a subtle glass card; assistant stays flush */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {{
  background: rgba(255,255,255,0.02) !important;
  border: 1px solid var(--metis-border) !important;
  border-radius: 14px !important;
  padding: 14px 18px !important;
  margin: 6px 0 !important;
}}

/* Code blocks — Fira Code + copy button hint */
pre, code, .stCode {{
  font-family: 'Fira Code', ui-monospace, monospace !important;
}}
div.stCodeBlock, pre {{
  background: #0f1016 !important;
  border: 1px solid var(--metis-border) !important;
  border-radius: 10px !important;
}}

/* ── Input area ─────────────────────────────────────────────────────────── */
div[data-testid="stChatInput"] {{
  background: {SURFACE} !important;
  border: 1px solid var(--metis-border) !important;
  border-radius: 14px !important;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}}
div[data-testid="stChatInput"]:focus-within {{
  border-color: var(--metis-cyan) !important;
  box-shadow: 0 0 0 3px rgba(102,252,241,0.12);
}}

/* ── Aura animation (only active when .metis-thinking is on the root) ──── */
.metis-aura {{
  position: relative;
  width: 120px;
  height: 120px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.metis-aura::before {{
  content: "";
  position: absolute;
  inset: -24px;
  border-radius: 50%;
  background: conic-gradient(from 0deg,
    var(--metis-cyan), var(--metis-purple),
    var(--metis-cyan), var(--metis-purple), var(--metis-cyan));
  filter: blur(28px);
  opacity: 0.0;
  transition: opacity 0.6s ease;
  animation: metisSpin 8s linear infinite;
  animation-play-state: paused;
  z-index: 0;
}}
.metis-aura .metis-core {{
  position: relative;
  z-index: 1;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, #1e2030, #0b0c10 80%);
  border: 1px solid var(--metis-border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--metis-cyan);
  font-family: 'Fira Code', monospace;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.04em;
}}
body.metis-thinking .metis-aura::before,
.metis-thinking .metis-aura::before {{
  opacity: 0.85;
  animation-play-state: running;
}}
@keyframes metisSpin {{
  to {{ transform: rotate(360deg); }}
}}
@media (prefers-reduced-motion: reduce) {{
  .metis-aura::before {{ animation: none !important; }}
}}

/* ── Tool-call cards ────────────────────────────────────────────────────── */
.metis-tool-card {{
  background: {SURFACE_2};
  border: 1px solid var(--metis-border);
  border-radius: 10px;
  padding: 10px 14px;
  margin: 6px 0;
  font-size: 13.5px;
  color: var(--metis-muted);
  display: flex;
  align-items: center;
  gap: 10px;
}}
.metis-tool-card.success {{ border-left: 3px solid var(--metis-cyan); }}
.metis-tool-card.error   {{ border-left: 3px solid #ff6b6b; }}

/* ── Status bar ─────────────────────────────────────────────────────────── */
.metis-statusbar {{
  position: fixed;
  bottom: 0; left: 0; right: 0;
  background: rgba(11,12,16,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid var(--metis-border);
  padding: 6px 18px;
  font-size: 12px;
  color: var(--metis-muted);
  display: flex;
  align-items: center;
  gap: 14px;
  z-index: 50;
}}
.metis-statusbar .dot {{
  width: 7px; height: 7px; border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 8px #4ade80;
}}
.metis-statusbar .dot.thinking {{
  background: var(--metis-cyan);
  box-shadow: 0 0 8px var(--metis-cyan);
  animation: metisPulse 1.1s ease-in-out infinite;
}}
@keyframes metisPulse {{
  0%,100% {{ opacity: 0.4; }}
  50%     {{ opacity: 1;   }}
}}

/* ── Mic button ─────────────────────────────────────────────────────────── */
.metis-mic {{
  width: 38px; height: 38px; border-radius: 50%;
  background: {SURFACE_2};
  border: 1px solid var(--metis-border);
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--metis-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}}
.metis-mic:hover {{
  color: var(--metis-cyan);
  border-color: var(--metis-cyan);
}}
.metis-mic.listening {{
  color: #ff6b6b;
  border-color: #ff6b6b;
  animation: metisPulse 0.9s ease-in-out infinite;
}}

/* ── Light theme override (applied when body has .metis-light) ──────────── */
body.metis-light, body.metis-light .stApp {{
  background: #f7f8fc !important;
  color: #1a1b23 !important;
}}
body.metis-light section[data-testid="stSidebar"] {{ background: #ffffff !important; }}
body.metis-light pre, body.metis-light div.stCodeBlock {{
  background: #ffffff !important;
  border-color: #dfe1e7 !important;
}}

/* ── Accessibility helpers ──────────────────────────────────────────────── */
.metis-sr-only {{
  position: absolute !important;
  width: 1px; height: 1px; padding: 0;
  overflow: hidden; clip: rect(0,0,0,0);
  white-space: nowrap; border: 0;
}}
button:focus-visible, a:focus-visible, [tabindex]:focus-visible {{
  outline: 2px solid var(--metis-cyan) !important;
  outline-offset: 2px;
  border-radius: 6px;
}}
"""


def inject(theme: str = "obsidian") -> None:
    body_class = "metis-light" if theme == "light" else ""
    st.markdown(
        f"<style>{CSS}</style>"
        f"<script>document.body.classList.remove('metis-light');"
        f"{'document.body.classList.add(\"metis-light\");' if body_class else ''}</script>",
        unsafe_allow_html=True,
    )
