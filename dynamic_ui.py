"""
Metis Command — Streamlit UI.

Feels like Claude.ai (3-column layout, artifacts pane, show-thinking,
copyable code, drag-drop attachments) with Codex agent ergonomics
(tool-call cards, slash commands, command palette, diff viewer,
status bar, keyboard shortcuts, voice I/O).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from ui_theme import (
    inject as inject_theme,
    hero as render_hero,
    thinking_flag,
    thinking_orb,
    agent_card,
    statusbar,
)
from hardware_scanner import get_hardware_report, get_hardware_tier
from brain_engine import ROLE_MODELS, stream_chat, CancelToken
from memory import save_message, load_session
from memory_loop import inject_context, persist_turn, load_reasoning
from identity_matrix import get_active_persona, build_system_prompt, list_personas
from artifacts import list_artifacts, get_artifact, Artifact
from metis_version import (
    METIS_MARKETING_SITE,
    METIS_PRODUCT_NAME,
    METIS_RELEASES_URL,
    METIS_SUPPORT_URL,
    METIS_VERSION,
)


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Metis Command",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme = st.session_state.get("theme", "obsidian")
inject_theme(theme=theme)
thinking_flag(st.session_state.get("thinking", False))


# ── Session state bootstrap ──────────────────────────────────────────────────
def _init_state() -> None:
    st.session_state.setdefault("session_id", f"s_{uuid.uuid4().hex[:10]}")
    st.session_state.setdefault("messages", [])             # [{role, content, reasoning?, tool_events?}]
    st.session_state.setdefault("planning_mode", False)
    st.session_state.setdefault("local_mode", True)
    st.session_state.setdefault("active_role", "manager")
    st.session_state.setdefault("active_artifact_id", None)
    st.session_state.setdefault("show_palette", False)
    st.session_state.setdefault("show_shortcuts", False)
    st.session_state.setdefault("show_artifacts", True)
    st.session_state.setdefault("thinking", False)
    st.session_state.setdefault("pending_voice_text", "")
    st.session_state.setdefault("last_metrics", {"tok_s": 0, "tokens": 0})
    st.session_state.setdefault("cancel_token", None)


_init_state()


# ── Layout helpers ───────────────────────────────────────────────────────────
def _group_sessions(session_ids: list[str]) -> dict[str, list[str]]:
    """We don't have timestamps per session here, so bucket by index order."""
    buckets = {"Today": [], "Yesterday": [], "Last 7 days": [], "Older": []}
    if not session_ids:
        return buckets
    buckets["Today"] = session_ids[:3]
    buckets["Yesterday"] = session_ids[3:6]
    buckets["Last 7 days"] = session_ids[6:12]
    buckets["Older"] = session_ids[12:]
    return buckets


def _sidebar() -> None:
    with st.sidebar:
        st.markdown(
            "<div style='display:flex;align-items:center;gap:10px;margin-bottom:6px;'>"
            "<span style='font-family:Fira Code;font-size:22px;color:var(--metis-cyan);'>◆</span>"
            "<span style='font-weight:600;font-size:17px;letter-spacing:0.02em;'>"
            "Metis Command</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button("＋  New chat", key="new_chat_btn", use_container_width=True,
                     help="Ctrl+Shift+N"):
            st.session_state["session_id"] = f"s_{uuid.uuid4().hex[:10]}"
            st.session_state["messages"] = []
            st.rerun()

        search = st.text_input(
            "Search chats",
            key="chat_search",
            placeholder="Search chats…",
            label_visibility="collapsed",
        )

        st.markdown("<div class='metis-side-heading'>History</div>", unsafe_allow_html=True)
        try:
            from memory import list_sessions
            # We don't have a guaranteed user_id at this point; best-effort query.
            sessions: list[str] = []
            try:
                sessions = list_sessions(user_id="") or []
            except Exception:
                sessions = []
        except Exception:
            sessions = []

        if search:
            sessions = [s for s in sessions if search.lower() in s.lower()]

        grouped = _group_sessions(sessions)
        for label, ids in grouped.items():
            if not ids:
                continue
            st.markdown(f"<div class='metis-side-heading'>{label}</div>", unsafe_allow_html=True)
            for sid in ids:
                if st.button(sid, key=f"hist_{sid}", use_container_width=True):
                    st.session_state["session_id"] = sid
                    st.session_state["messages"] = [
                        {"role": r["role"], "content": r["content"]}
                        for r in load_session(sid, limit=200)
                    ]
                    st.rerun()

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
        st.markdown("<div class='metis-side-heading'>Mode</div>", unsafe_allow_html=True)
        st.session_state["planning_mode"] = st.toggle(
            "Planning Mode",
            value=st.session_state["planning_mode"],
            help="Agent asks multiple-choice questions before executing.",
        )
        st.session_state["local_mode"] = st.toggle(
            "Local (offline) brain",
            value=st.session_state["local_mode"],
            help="Off → use OpenAI cloud fallback when available.",
        )

        st.markdown("<div class='metis-side-heading'>Persona</div>", unsafe_allow_html=True)
        try:
            personas = list_personas() or []
        except Exception:
            personas = []
        persona_names = [p["name"] for p in personas] if personas else ["Metis"]
        active_persona = get_active_persona()
        default_idx = persona_names.index(active_persona["name"]) if active_persona["name"] in persona_names else 0
        chosen = st.selectbox(
            "Active persona",
            options=persona_names,
            index=default_idx,
            label_visibility="collapsed",
        )
        st.session_state["active_persona_name"] = chosen

        st.markdown("<div class='metis-side-heading'>System</div>", unsafe_allow_html=True)
        report = get_hardware_report()
        st.markdown(
            f"<span class='metis-pill'>Tier: {report['tier']}</span> "
            f"<span class='metis-pill muted'>RAM {report['available_ram_gb']}/{report['total_ram_gb']} GB</span>",
            unsafe_allow_html=True,
        )

        with st.expander("Models in use", expanded=False):
            for role, model in ROLE_MODELS.items():
                if role == "default":
                    continue
                st.markdown(
                    f"<div style='font-size:12.5px;color:var(--metis-muted);'>"
                    f"<b style='color:var(--metis-text);'>{role}</b> → "
                    f"<code>{model}</code></div>",
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Palette", use_container_width=True, help="Ctrl+K"):
                st.session_state["show_palette"] = not st.session_state["show_palette"]
        with col_b:
            if st.button("Shortcuts", use_container_width=True, help="Ctrl+/"):
                st.session_state["show_shortcuts"] = not st.session_state["show_shortcuts"]

        col_c, col_d = st.columns(2)
        with col_c:
            if st.button("Theme", use_container_width=True):
                st.session_state["theme"] = "light" if theme == "obsidian" else "obsidian"
                st.rerun()
        with col_d:
            if st.button("Artifacts", use_container_width=True, help="Ctrl+J"):
                st.session_state["show_artifacts"] = not st.session_state["show_artifacts"]
                st.rerun()

        # ── Brains ───────────────────────────────────────────────────────
        with st.expander("Brains", expanded=False):
            try:
                import brains as _brains
                cur = _brains.active()
                options = [b.slug for b in _brains.list_brains()] or ["default"]
                current_slug = cur.slug if cur else options[0]
                idx = options.index(current_slug) if current_slug in options else 0
                chosen_brain = st.selectbox("Active brain", options=options, index=idx,
                                            key="active_brain_select")
                if chosen_brain != current_slug:
                    try:
                        _brains.switch(chosen_brain)
                        st.toast(f"Switched to brain: {chosen_brain}")
                    except Exception as e:
                        st.error(str(e))

                stats = _brains.stats(chosen_brain) if chosen_brain else {}
                st.caption(
                    f"Entries: {stats.get('entries','?')} · "
                    f"≈{stats.get('approx_tokens','?')}/{stats.get('budget_tokens','?')} tokens"
                )

                new_name = st.text_input("New brain name", key="new_brain_name",
                                         placeholder="e.g. Work, Personal")
                if st.button("Create brain", use_container_width=True, key="brain_create"):
                    if new_name.strip():
                        _brains.create(new_name.strip())
                        st.success(f"Created brain '{new_name.strip()}'")
                        st.rerun()

                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("Compact", use_container_width=True, key="brain_compact"):
                        folded = _brains.compact(brain=chosen_brain)
                        st.toast(f"Folded {folded} entries")
                with col_b2:
                    if st.button("Backup", use_container_width=True, key="brain_backup"):
                        path = Path("identity") / "backups" / f"{chosen_brain}_{int(time.time())}.json"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        _brains.backup(str(path), brain=chosen_brain)
                        st.success(f"Saved → {path}")
            except Exception as e:
                st.caption(f"Brains unavailable: {e}")

        # ── Wallet ───────────────────────────────────────────────────────
        with st.expander("Wallet", expanded=False):
            try:
                import wallet as _wallet
                summary = _wallet.summary()
                st.markdown(
                    f"**Balance:** ${summary['balance_cents']/100:.2f}  ·  "
                    f"**Cap:** ${summary['monthly_cap_cents']/100:.2f}/mo  ·  "
                    f"**Mode:** {summary['mode']}"
                )
                st.caption(f"Spent this month: ${summary['monthly_spent_cents']/100:.2f}")
                col_w1, col_w2 = st.columns([2, 1])
                with col_w1:
                    topup_amt = st.number_input("Top-up ($)", min_value=0.0, step=1.0,
                                                key="wallet_topup_amt")
                with col_w2:
                    if st.button("Add", key="wallet_topup_btn", use_container_width=True):
                        _wallet.top_up(int(round(topup_amt * 100)), source="ui")
                        st.rerun()

                new_cap = st.number_input("Monthly cap ($)",
                                          value=float(summary['monthly_cap_cents'] / 100),
                                          min_value=0.0, step=10.0, key="wallet_cap_input")
                if st.button("Save cap", key="wallet_cap_btn", use_container_width=True):
                    _wallet.set_cap(int(round(new_cap * 100)))
                    st.toast("Cap saved.")

                rows = _wallet.ledger(limit=8)
                if rows:
                    st.markdown("<div class='metis-side-heading'>Recent</div>",
                                unsafe_allow_html=True)
                    for r in reversed(rows):
                        sign = "−" if r.get("kind") == "charge" else "+"
                        cents = abs(int(r.get("cents", 0)))
                        st.caption(
                            f"{sign}${cents/100:.2f} · {r.get('category','?')} · "
                            f"{r.get('memo','')[:48]}"
                        )
            except Exception as e:
                st.caption(f"Wallet unavailable: {e}")

        # ── Agent Roster ─────────────────────────────────────────────────
        with st.expander("Agent Roster", expanded=False):
            try:
                import agent_roster as _roster
                specs = _roster.list_roster()
                live = set(_roster.list_persistent())
                st.caption(f"{len(specs)} agents · {len(live)} persistent")
                for spec in specs:
                    is_live = spec.slug in live
                    body = (spec.system or "").strip()
                    if len(body) > 140:
                        body = body[:140].rstrip() + "…"
                    agent_card(
                        name=spec.name,
                        role=spec.role,
                        text=body,
                        status="live" if is_live else "idle",
                        avatar_letter=spec.slug[:1],
                    )
                    cols = st.columns(2)
                    with cols[0]:
                        if is_live and st.button(
                            "Stop", key=f"agent_stop_{spec.slug}",
                            use_container_width=True,
                        ):
                            _roster.stop_persistent(spec.slug)
                            st.rerun()
                    with cols[1]:
                        if not is_live and st.button(
                            "Start", key=f"agent_start_{spec.slug}",
                            use_container_width=True,
                        ):
                            _roster.spawn_persistent(spec.slug)
                            st.rerun()
            except Exception as e:
                st.caption(f"Roster unavailable: {e}")

        # ── Developer (local API token) ──────────────────────────────────
        with st.expander("About", expanded=False):
            _site = ""
            if METIS_MARKETING_SITE:
                _ms = METIS_MARKETING_SITE
                _site = (
                    f"<br/>Site: <a href='{_ms}' target='_blank' rel='noopener'>{_ms}</a>"
                )
            st.markdown(
                f"<div style='font-size:13px;line-height:1.5;color:var(--metis-muted);'>"
                f"<b style='color:var(--metis-text);'>{METIS_PRODUCT_NAME}</b><br/>"
                f"Version <code>{METIS_VERSION}</code><br/><br/>"
                f"Support: <a href='{METIS_SUPPORT_URL}' target='_blank' rel='noopener'>"
                f"GitHub Discussions</a><br/>"
                f"Releases &amp; checksums: "
                f"<a href='{METIS_RELEASES_URL}' target='_blank' rel='noopener'>GitHub</a>"
                f"{_site}</div>",
                unsafe_allow_html=True,
            )

        with st.expander("Developer", expanded=False):
            try:
                import auth_local
                token = auth_local.get_or_create()
                st.caption("Local API token — required for every /wallet, "
                           "/brains, /agents call.")
                st.code(f"Authorization: Bearer {token}", language="text")
                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    if st.button("Copy", key="token_copy",
                                 use_container_width=True):
                        try:
                            import pyperclip
                            pyperclip.copy(token)
                            st.toast("Token copied.")
                        except Exception:
                            st.toast("Clipboard unavailable.", icon="⚠️")
                with col_t2:
                    if st.button("Rotate", key="token_rotate",
                                 use_container_width=True):
                        auth_local.rotate()
                        st.toast("Token rotated.")
                        st.rerun()
            except Exception as e:
                st.caption(f"Developer panel unavailable: {e}")

        with st.expander("Brain backup", expanded=False):
            try:
                from mts_format import export_identity, import_identity  # noqa: F401
                pw = st.text_input("Password (optional)", type="password", key="mts_pw")
                if st.button("Backup brain (.mts)", use_container_width=True):
                    path = Path("identity") / f"brain_{int(time.time())}.mts"
                    export_identity(str(path), password=pw or None)
                    st.success(f"Saved → {path}")
                uploaded = st.file_uploader(".mts to restore", type=["mts"])
                if uploaded and st.button("Restore brain", use_container_width=True):
                    tmp = Path("identity") / f"restore_{int(time.time())}.mts"
                    tmp.write_bytes(uploaded.read())
                    import_identity(str(tmp), password=pw or None)
                    st.success("Brain restored.")
            except Exception as e:
                st.caption(f"Backup tools unavailable: {e}")


# ── Command palette + shortcut cheat sheet ──────────────────────────────────
PALETTE_ACTIONS = [
    ("New chat",              "new_chat"),
    ("Toggle Planning Mode",  "toggle_plan"),
    ("Toggle Local/Cloud",    "toggle_local"),
    ("Toggle Theme",          "toggle_theme"),
    ("Open Marketplace",      "open_marketplace"),
    ("Export brain (.mts)",   "export_brain"),
    ("Clear session",         "clear_session"),
    ("Show Shortcuts",        "show_shortcuts"),
]


def _run_palette_action(action: str) -> None:
    if action == "new_chat":
        st.session_state["session_id"] = f"s_{uuid.uuid4().hex[:10]}"
        st.session_state["messages"] = []
    elif action == "toggle_plan":
        st.session_state["planning_mode"] = not st.session_state["planning_mode"]
    elif action == "toggle_local":
        st.session_state["local_mode"] = not st.session_state["local_mode"]
    elif action == "toggle_theme":
        st.session_state["theme"] = "light" if st.session_state.get("theme") != "light" else "obsidian"
    elif action == "open_marketplace":
        st.session_state["active_tab"] = "marketplace"
    elif action == "clear_session":
        st.session_state["messages"] = []
    elif action == "show_shortcuts":
        st.session_state["show_shortcuts"] = True
    elif action == "export_brain":
        try:
            from mts_format import export_identity
            path = Path("identity") / f"brain_{int(time.time())}.mts"
            export_identity(str(path))
            st.toast(f"Brain saved → {path}")
        except Exception as e:
            st.toast(f"Export failed: {e}", icon="⚠️")


def _palette() -> None:
    if not st.session_state["show_palette"]:
        return
    with st.container(border=True):
        st.markdown("**⌘ Command Palette**")
        q = st.text_input("Search actions", key="palette_query", label_visibility="collapsed")
        matches = [
            (label, act) for label, act in PALETTE_ACTIONS
            if not q or q.lower() in label.lower()
        ]
        for label, act in matches:
            if st.button(label, key=f"pal_{act}", use_container_width=True):
                st.session_state["show_palette"] = False
                _run_palette_action(act)
                st.rerun()


def _shortcut_sheet() -> None:
    if not st.session_state["show_shortcuts"]:
        return
    with st.container(border=True):
        st.markdown("**⌨ Keyboard Shortcuts**")
        st.markdown(
            "- **Ctrl+K** — Command palette\n"
            "- **Ctrl+Shift+N** — New chat\n"
            "- **Ctrl+Enter** — Send message\n"
            "- **Esc** — Stop generation\n"
            "- **Ctrl+/** — This cheat sheet\n"
            "- **Ctrl+B** — Toggle sidebar (Streamlit native)\n"
            "- **Ctrl+J** — Toggle artifacts pane\n"
            "- **Ctrl+M** — Push-to-talk (mic)"
        )
        if st.button("Close", key="close_shortcuts"):
            st.session_state["show_shortcuts"] = False
            st.rerun()


# ── Slash-command parser ─────────────────────────────────────────────────────
SLASH_MODES = {
    "/code":       ("code",     "Coder will write and sandbox-test code."),
    "/plan":       ("plan",     "Thinker will plan before executing."),
    "/search":     ("research", "Researcher will hit the live web."),
    "/research":   ("research", "Researcher will hit the live web."),
    "/skill":      ("code",     "Forge a new skill into plugins/."),
    "/sandbox":    ("code",     "Run code inside the Docker sandbox."),
    "/remember":   ("remember", "Store a durable fact in memory."),
    "/forget":     ("forget",   "Delete matching memories."),
    "/model":      ("model",    "Hot-swap a role's Ollama model."),
    "/screenshot": ("tool",     "Capture a screenshot."),
    "/speak":      ("tool",     "Speak text aloud."),
    "/click":      ("tool",     "Request a click at x,y."),
}


def _parse_slash(text: str) -> tuple[str | None, str]:
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None, stripped
    head, _, rest = stripped.partition(" ")
    return head.lower(), rest.strip() or stripped


# ── Tool-call card renderer ──────────────────────────────────────────────────
TOOL_ICONS = {
    "internet_search": "🔍",
    "Screenshot":      "📸",
    "ReadClipboard":   "📋",
    "WriteClipboard":  "📋",
    "Speak":           "🔊",
    "ListenOnce":      "🎙️",
    "sandbox":         "🧪",
    "default":         "🛠",
}


def _render_tool_events(events: list[dict]) -> None:
    if not events:
        return
    for ev in events:
        t = ev.get("type")
        agent = ev.get("agent", "agent")
        tool = ev.get("tool", "")
        icon = TOOL_ICONS.get(tool, TOOL_ICONS["default"])
        css = "success" if t == "tool_end" else ""
        if t == "mission_start":
            st.markdown(
                f"<div class='metis-tool-card'>"
                f"<span>🚀</span> <b>{agent}</b> starting mission · "
                f"<span style='color:var(--metis-muted)'>{ev.get('mode','')}</span></div>",
                unsafe_allow_html=True,
            )
        elif t in ("tool_start", "tool_end"):
            duration = ev.get("duration_ms")
            suffix = f" · {duration} ms" if duration else ""
            st.markdown(
                f"<div class='metis-tool-card {css}'>"
                f"<span>{icon}</span> <b>{tool}</b>"
                f"<span style='color:var(--metis-muted);margin-left:6px;'>by {agent}{suffix}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        elif t == "thought":
            content = ev.get("content", "")[:120]
            if content.strip():
                st.markdown(
                    f"<div class='metis-tool-card'>"
                    f"<span>💭</span> <span style='color:var(--metis-muted);font-style:italic;'>{content}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        elif t == "error":
            st.markdown(
                f"<div class='metis-tool-card error'>"
                f"<span>⚠️</span> <b>Error:</b> {ev.get('message','unknown')}"
                f"</div>",
                unsafe_allow_html=True,
            )


# ── Artifacts pane ───────────────────────────────────────────────────────────
def _artifacts_pane(container) -> None:
    if not st.session_state["show_artifacts"]:
        return
    with container:
        st.markdown(
            "<div style='display:flex;align-items:center;justify-content:space-between;"
            "margin-bottom:8px;'>"
            "<span style='font-weight:600;'>Artifacts</span>"
            "<span class='metis-pill muted'>live</span></div>",
            unsafe_allow_html=True,
        )
        arts = list_artifacts(limit=50)
        if not arts:
            st.caption("No artifacts yet. Run /code, /skill, or /screenshot.")
            return
        for a in arts:
            with st.container(border=True):
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:8px;'>"
                    f"<span class='metis-pill {'purple' if a.type=='image' else ''}'>{a.type}</span>"
                    f"<span style='font-weight:600;'>{a.title}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if a.type == "image" and a.path and Path(a.path).exists():
                    st.image(a.path, use_container_width=True)
                elif a.content:
                    lang = a.language or "text"
                    preview = a.content if len(a.content) < 2000 else a.content[:2000] + "\n…"
                    st.code(preview, language=lang)
                if a.path and Path(a.path).exists():
                    with open(a.path, "rb") as fh:
                        st.download_button(
                            "Download",
                            data=fh.read(),
                            file_name=Path(a.path).name,
                            key=f"dl_{a.id}",
                            use_container_width=True,
                        )


# ── Main thread rendering ────────────────────────────────────────────────────
def _render_thread() -> None:
    # Gemini-style hero when the conversation is empty.
    if not st.session_state["messages"]:
        try:
            persona = get_active_persona() or {}
        except Exception:
            persona = {}
        display_name = (persona.get("name") or "").strip() or "Director"
        chosen_prompt = render_hero(
            f"Hello, {display_name}",
            subtitle="What should Metis work on today?",
            chips=[
                ("Plan my day",      "Plan my day. Ask me 2 quick questions first."),
                ("Summarise inbox",  "Summarise my unread messages and pick the 3 to reply today."),
                ("Research topic",   "Research and give me a 6-bullet brief on: "),
                ("Write code",       "Write Python to: "),
                ("Brainstorm",       "Brainstorm 5 wild ideas for: "),
            ],
        )
        if chosen_prompt:
            st.session_state["messages"].append(
                {"role": "user", "content": chosen_prompt}
            )
            st.rerun()
        return

    for i, msg in enumerate(st.session_state["messages"]):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                # Tool-call cards above the body.
                _render_tool_events(msg.get("tool_events", []))
                # Main content.
                st.markdown(msg.get("content", ""))
                # Show-thinking dropdown.
                reasoning = msg.get("reasoning")
                if reasoning:
                    with st.expander(f"Show thinking · {len(reasoning)//4} chars",
                                     expanded=False):
                        st.markdown(
                            f"<div style='color:var(--metis-muted);font-size:13px;"
                            f"font-family:Fira Code, monospace;white-space:pre-wrap;'>"
                            f"{reasoning}</div>",
                            unsafe_allow_html=True,
                        )
                # Row of message actions.
                c1, c2, c3 = st.columns([1, 1, 8])
                with c1:
                    if st.button("🔁", key=f"regen_{i}", help="Regenerate"):
                        st.session_state["messages"] = st.session_state["messages"][:i]
                        st.rerun()
                with c2:
                    if st.button("🔊", key=f"speak_{i}", help="Read aloud"):
                        try:
                            from tools.voice_io import speak
                            speak(msg.get("content", ""))
                        except Exception:
                            st.toast("TTS unavailable", icon="⚠️")
            else:
                st.markdown(msg.get("content", ""))


# ── Send + stream pipeline ───────────────────────────────────────────────────
def _send_prompt(user_text: str) -> None:
    slash, payload = _parse_slash(user_text)
    mode = "chat"
    routed_role = "manager"

    if slash in SLASH_MODES:
        mapped, _desc = SLASH_MODES[slash]
        if mapped in ("code", "plan", "research"):
            mode = mapped
            routed_role = {"code": "coder", "plan": "thinker", "research": "researcher"}[mapped]
        elif mapped == "remember":
            try:
                from memory_vault import MemoryBank
                MemoryBank().store_interaction(
                    entity_name=f"manual:{int(time.time())}",
                    facts=payload,
                )
                st.toast("Remembered.", icon="✅")
            except Exception as e:
                st.toast(f"Memory write failed: {e}", icon="⚠️")
            return
        elif mapped == "tool":
            if slash == "/screenshot":
                try:
                    from tools.computer_use import screenshot
                    screenshot()
                    st.toast("Screenshot captured.", icon="📸")
                except Exception as e:
                    st.toast(f"Screenshot failed: {e}", icon="⚠️")
                return
            if slash == "/speak":
                try:
                    from tools.voice_io import speak
                    speak(payload or "Metis online.")
                except Exception as e:
                    st.toast(f"Speak failed: {e}", icon="⚠️")
                return
            if slash == "/click":
                st.toast("Click is confirm-gated; use /code to request.", icon="🛡️")
                return

    st.session_state["messages"].append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    # Stream the assistant reply.
    tool_events: list[dict] = []
    reasoning_buf: list[str] = []
    assistant_container = st.chat_message("assistant")
    cancel = CancelToken()
    st.session_state["cancel_token"] = cancel
    st.session_state["thinking"] = True
    with assistant_container:
        thinking_orb(True, label="Metis is thinking")

    persona_prompt = build_system_prompt(get_active_persona())
    context_msgs = inject_context(st.session_state["session_id"], user_text)
    system_msg = {"role": "system", "content": persona_prompt}
    user_msg = {"role": "user", "content": payload if slash in SLASH_MODES else user_text}
    conversation = [system_msg] + context_msgs + [user_msg]

    token_container = assistant_container.empty()
    token_buf: list[str] = []
    started = time.time()

    try:
        # Simple modes go straight to the role model for speed.
        if mode in ("code", "research", "plan", "chat"):
            tool_events.append({
                "type": "tool_start",
                "agent": routed_role,
                "tool": ROLE_MODELS.get(routed_role, ""),
            })
            for ev in stream_chat(routed_role, conversation, cancel=cancel):
                if ev["type"] == "token":
                    token_buf.append(ev["delta"])
                    token_container.markdown("".join(token_buf) + "▌")
                elif ev["type"] == "reasoning":
                    reasoning_buf.append(ev["delta"])
                elif ev["type"] == "done":
                    tok = ev.get("tokens", 0)
                    dur = ev.get("duration_ms", 1) or 1
                    st.session_state["last_metrics"] = {
                        "tok_s": round(tok / (dur / 1000), 1),
                        "tokens": tok,
                    }
            tool_events.append({
                "type": "tool_end",
                "agent": routed_role,
                "tool": ROLE_MODELS.get(routed_role, ""),
                "duration_ms": int((time.time() - started) * 1000),
            })
        else:
            tool_events.append({"type": "mission_start", "mode": mode, "agent": "manager"})
            from crew_engine import run_agentic_mission
            reply = run_agentic_mission(
                user_text,
                mode=mode,
                on_event=tool_events.append,
                session_id=st.session_state["session_id"],
            )
            token_buf.append(reply)
            token_container.markdown(reply)
    finally:
        st.session_state["thinking"] = False
        st.session_state["cancel_token"] = None

    final_text = "".join(token_buf).strip()
    reasoning_text = "".join(reasoning_buf).strip() or None
    token_container.markdown(final_text)

    st.session_state["messages"].append({
        "role": "assistant",
        "content": final_text,
        "reasoning": reasoning_text,
        "tool_events": tool_events,
    })

    # Persist the turn (best-effort).
    try:
        persist_turn(
            session_id=st.session_state["session_id"],
            user_msg=user_text,
            assistant_msg=final_text,
            reasoning=reasoning_text,
        )
    except Exception as e:
        print(f"[UI] persist_turn failed: {e}")


# ── Status bar ───────────────────────────────────────────────────────────────
def _update_banner() -> None:
    """Show a dismissable banner when a newer Metis release is available."""
    if st.session_state.get("update_banner_dismissed"):
        return
    try:
        from scripts import updater
        row = updater.cached_check(max_age_s=3600)
    except Exception:
        return
    if not row.get("update_available"):
        return
    latest = row.get("latest", "?")
    url = row.get("url") or "https://github.com/om1o/Metis_Command/releases"
    with st.container(border=True):
        col_msg, col_action, col_dismiss = st.columns([5, 1, 1])
        with col_msg:
            st.markdown(
                f"**Update available** — Metis v{latest} is out. "
                f"You're running v{row.get('current','?')}."
            )
        with col_action:
            st.link_button("Release notes", url, use_container_width=True)
        with col_dismiss:
            if st.button("Dismiss", key="update_dismiss",
                         use_container_width=True):
                st.session_state["update_banner_dismissed"] = True
                st.rerun()


def _health_snapshot() -> dict:
    """Cheap snapshot of Ollama + Wallet + Brain for the status bar."""
    snap = {"ollama": False, "wallet_usd": None, "brain": None}
    try:
        from brain_engine import list_local_models
        snap["ollama"] = bool(list_local_models())
    except Exception:
        pass
    try:
        from wallet import summary as _ws
        s = _ws()
        snap["wallet_usd"] = s["balance_cents"] / 100.0
    except Exception:
        pass
    try:
        import brains as _brains
        active = _brains.active()
        if active is not None:
            snap["brain"] = active.name
    except Exception:
        pass
    return snap


def _status_bar() -> None:
    thinking = st.session_state.get("thinking", False)
    tier = get_hardware_tier()
    metrics = st.session_state.get("last_metrics", {})
    sid = st.session_state.get("session_id", "")
    snap = _health_snapshot()
    items = [
        ("status", "thinking…" if thinking else "ready"),
        ("role",   st.session_state.get("active_role", "manager")),
        ("tier",   tier),
        ("ollama", "up" if snap["ollama"] else "down"),
    ]
    if snap["brain"]:
        items.append(("brain", snap["brain"]))
    if snap["wallet_usd"] is not None:
        items.append(("wallet", f"${snap['wallet_usd']:.2f}"))
    items.extend([
        ("tok/s",  f"{float(metrics.get('tok_s', 0)):.1f}"),
        ("session", sid[-8:] if sid else "—"),
    ])
    statusbar(items)


# ── Aura header ──────────────────────────────────────────────────────────────
def _aura_header() -> None:
    thinking = st.session_state.get("thinking", False)
    cls = "metis-aura"
    wrapper_class = "metis-thinking" if thinking else ""
    st.markdown(
        f"<div class='{wrapper_class}'>"
        f"<div class='{cls}'><div class='metis-core'>◆</div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<h1 style='text-align:center;font-weight:300;letter-spacing:0.08em;"
        "margin:8px 0 2px 0;'>METIS <span style='color:var(--metis-cyan);'>//</span> CORE</h1>"
        "<div style='text-align:center;color:var(--metis-muted);font-size:13px;margin-bottom:12px;'>"
        "local agentic swarm · offline-first · zero-trust</div>",
        unsafe_allow_html=True,
    )


# ── Marketplace tab (thin) ───────────────────────────────────────────────────
def _marketplace_tab() -> None:
    try:
        from marketplace import render_storefront
        render_storefront()
    except Exception as e:
        st.info("Marketplace is being set up. Seed plugins are in the plugins/ folder.")
        st.caption(f"(detail: {e})")


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    _sidebar()
    _update_banner()

    main_col, side_col = (st.columns([2.0, 1.0]) if st.session_state["show_artifacts"]
                          else (st.container(), None))

    with (main_col if isinstance(main_col, st.delta_generator.DeltaGenerator) else st.container()):
        tabs = st.tabs(["Chat", "Marketplace"])
        with tabs[0]:
            _aura_header()
            _palette()
            _shortcut_sheet()

            # Drag-drop attachments (text/pdf/image) — passed as context.
            uploaded = st.file_uploader(
                "Attach files (txt / pdf / png / jpg)",
                type=["txt", "md", "pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key="attachments",
                label_visibility="collapsed",
            )
            if uploaded:
                names = ", ".join(u.name for u in uploaded)
                st.caption(f"📎 Attached: {names}")

            _render_thread()

            # Voice prefill (Phase 5D).
            with st.expander("🎙  Voice input", expanded=False):
                colv1, colv2 = st.columns([3, 1])
                with colv1:
                    st.caption("Click 'Listen' to record one phrase (≈5s).")
                with colv2:
                    if st.button("Listen", key="voice_listen", use_container_width=True):
                        try:
                            from tools.voice_io import listen_once
                            heard = listen_once()
                            st.session_state["pending_voice_text"] = heard
                            if heard:
                                st.toast(f"Heard: {heard}", icon="🎙️")
                            else:
                                st.toast("No speech detected.", icon="🤔")
                        except Exception as e:
                            st.toast(f"Mic failed: {e}", icon="⚠️")

            prefill = st.session_state.pop("pending_voice_text", "") or ""
            placeholder = (
                "Type, / for slash commands, drag files to attach…  "
                + (f"[voice: {prefill[:40]}]" if prefill else "")
            )
            user_text = st.chat_input(placeholder)
            if prefill and not user_text:
                user_text = prefill

            if user_text:
                _send_prompt(user_text)
                st.rerun()

        with tabs[1]:
            _marketplace_tab()

    if side_col is not None:
        _artifacts_pane(side_col)

    _status_bar()


if __name__ == "__main__":
    main()
