"""
Metis Command — Streamlit UI.

Feels like Claude.ai (3-column layout, artifacts pane, show-thinking,
copyable code, drag-drop attachments) with Codex agent ergonomics
(tool-call cards, slash commands, command palette, diff viewer,
status bar, keyboard shortcuts, voice I/O).
"""

from __future__ import annotations

import base64
import json
import os
import re
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
from artifacts import list_artifacts, get_artifact, save_artifact, Artifact
from supabase_client import get_client
from metis_version import (
    METIS_MARKETING_SITE,
    METIS_PRODUCT_NAME,
    METIS_RELEASES_URL,
    METIS_SUPPORT_URL,
    METIS_VERSION,
)

_REPO_ROOT = Path(__file__).resolve().parent
_LOGOMARK_PNG = _REPO_ROOT / "assets" / "design-system" / "assets" / "metis-logomark.png"


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Metis Command",
    page_icon=str(_LOGOMARK_PNG) if _LOGOMARK_PNG.exists() else "◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme = st.session_state.get("theme", "solar")
inject_theme(theme=theme)
thinking_flag(st.session_state.get("thinking", False))

# ── Cached helpers (built once per process; avoids repeated disk/network I/O) ─
_LOGO_B64_CACHE: dict[str, str] = {}  # path → base64 string


def _read_b64(path: Path) -> str:
    """Read a file as base64, cached in a module-level dict."""
    key = str(path)
    if key not in _LOGO_B64_CACHE:
        try:
            _LOGO_B64_CACHE[key] = base64.b64encode(path.read_bytes()).decode("ascii") if path.exists() else ""
        except Exception:
            _LOGO_B64_CACHE[key] = ""
    return _LOGO_B64_CACHE[key]


@st.cache_data(ttl=120, show_spinner=False)
def _cached_hardware_report() -> dict:
    """Hardware report — cached 2 min, runs system calls once."""
    return get_hardware_report()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_hardware_tier() -> str:
    return get_hardware_tier()


@st.cache_data(ttl=20, show_spinner=False)
def _cached_health_snapshot() -> dict:
    """Ping Ollama + wallet + active brain — cached 20 s."""
    snap: dict = {"ollama": False, "wallet_usd": None, "brain": None}
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


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_sessions(user_id: str = "") -> list:
    try:
        from memory import list_sessions
        return list_sessions(user_id=user_id) or []
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _cached_list_personas() -> list:
    try:
        from identity_matrix import list_personas
        return list_personas() or []
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _cached_comms_status() -> tuple[bool, bool]:
    """Returns (smtp_configured, twilio_configured)."""
    try:
        from comms_policy import smtp_configured, twilio_configured
        return smtp_configured(), twilio_configured()
    except Exception:
        return False, False


@st.cache_data(ttl=15, show_spinner=False)
def _cached_list_artifacts(limit: int = 50) -> list:
    try:
        from artifacts import list_artifacts
        return list_artifacts(limit=limit)
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_brains() -> list:
    try:
        import brains as _brains
        return [{"slug": b.slug, "name": b.name} for b in (_brains.list_brains() or [])]
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_roster() -> list:
    try:
        import agent_roster as _r
        return [s.to_dict() for s in (_r.list_roster() or [])]
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def _cached_marketplace_plugins() -> list:
    try:
        from marketplace import list_plugins
        return list_plugins() or []
    except Exception:
        return []


@st.cache_data(ttl=8, show_spinner=False)
def _cached_agent_health() -> list:
    try:
        from agent_roster import get_agent_health
        return get_agent_health() or []
    except Exception:
        return []


def _bust_caches() -> None:
    """Clear data caches after state-changing operations (sessions, brains, etc.)."""
    for fn in (
        _cached_list_sessions, _cached_list_artifacts, _cached_list_brains,
        _cached_list_roster, _cached_marketplace_plugins, _cached_agent_health,
        _cached_health_snapshot,
    ):
        try:
            fn.clear()
        except Exception:
            pass


# Auth result cache — avoids a Supabase network round-trip on every rerun.
_AUTH_CACHE_TTL_S = 90  # seconds


def _auth_cached_ok() -> bool:
    """Return True if auth was verified within the last N seconds."""
    last = st.session_state.get("_auth_last_check_ts", 0.0)
    return (time.time() - last) < _AUTH_CACHE_TTL_S and st.session_state.get("_auth_ok", False)


def _auth_mark_ok() -> None:
    st.session_state["_auth_ok"] = True
    st.session_state["_auth_last_check_ts"] = time.time()


def _auth_mark_fail() -> None:
    st.session_state["_auth_ok"] = False
    st.session_state["_auth_last_check_ts"] = 0.0


# ── Session state bootstrap ──────────────────────────────────────────────────
def _init_state() -> None:
    st.session_state.setdefault("session_id", f"s_{uuid.uuid4().hex[:10]}")
    st.session_state.setdefault("messages", [])             # [{role, content, reasoning?, tool_events?}]
    st.session_state.setdefault("planning_mode", False)
    st.session_state.setdefault("local_mode", True)
    st.session_state.setdefault("auto_write_files", True)
    st.session_state.setdefault("auto_write_debug", [])     # list[dict]
    st.session_state.setdefault("pending_filename", "")    # filename requested by the Director
    st.session_state.setdefault("active_role", "manager")
    st.session_state.setdefault("active_artifact_id", None)
    st.session_state.setdefault("show_palette", False)
    st.session_state.setdefault("show_shortcuts", False)
    st.session_state.setdefault("show_artifacts", True)
    st.session_state.setdefault("thinking", False)
    st.session_state.setdefault("auto_show_thinking", True)
    st.session_state.setdefault("pending_voice_text", "")
    st.session_state.setdefault("last_metrics", {"tok_s": 0, "tokens": 0})
    st.session_state.setdefault("cancel_token", None)
    # Director-chosen outbound tools (enforced in comms_policy + CommsLink; see sidebar).
    st.session_state.setdefault("tool_sms", False)
    st.session_state.setdefault("tool_phone_calls", False)
    st.session_state.setdefault("tool_email", False)
    st.session_state.setdefault("tool_calendar", False)


_init_state()

_PROFILE_PATH = Path("identity") / "profile.json"


def _load_profile() -> dict:
    try:
        if _PROFILE_PATH.exists():
            return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_profile(profile: dict) -> None:
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    save_artifact(
        Artifact(
            type="config",
            title="profile.json",
            language="json",
            path=str(_PROFILE_PATH),
            content=json.dumps(profile, indent=2),
            metadata={"source": "setup_wizard"},
        )
    )


def _setup_wizard() -> None:
    """First-run setup gate. Writes identity/profile.json + artifact."""
    st.session_state.setdefault("setup_step", 1)
    st.session_state.setdefault("setup_name", "")
    st.session_state.setdefault("setup_use_case", "")
    st.session_state.setdefault("setup_model_pref", "")
    st.session_state.setdefault("setup_theme", st.session_state.get("theme", "solar"))

    total = 4
    step = int(st.session_state.get("setup_step", 1) or 1)
    step = max(1, min(total, step))
    st.session_state["setup_step"] = step

    st.markdown("<div class='metis-eyebrow'>SETUP</div>", unsafe_allow_html=True)
    st.markdown("<h2 style='margin:6px 0 0 0;'>Set up Metis</h2>", unsafe_allow_html=True)
    st.caption("One-time setup — you can change everything later in Settings.")
    st.progress(step / total)

    with st.container(border=True):
        if step == 1:
            st.markdown("**What should we call you?**")
            st.session_state["setup_name"] = st.text_input(
                "Display name",
                value=st.session_state.get("setup_name", ""),
                placeholder="e.g. Alex Chen",
                label_visibility="collapsed",
            )
            if st.session_state["setup_name"].strip():
                st.caption(f"Nice to meet you, **{st.session_state['setup_name'].strip()}**.")

        elif step == 2:
            st.markdown("**What brings you here?**")
            st.session_state["setup_use_case"] = st.radio(
                "Use case",
                options=["Work", "Personal", "Build / Dev", "Research", "Sales / Outreach", "Ops / Automation"],
                index=0,
                horizontal=True,
                label_visibility="collapsed",
            )
            st.caption("This tailors defaults and starter templates.")

        elif step == 3:
            st.markdown("**Default brain preference**")
            st.session_state["setup_model_pref"] = st.radio(
                "Model preference",
                options=["Smart (recommended)", "Fast", "Local-first"],
                index=0,
                horizontal=True,
                label_visibility="collapsed",
            )
            st.caption("You can override per chat and per agent.")

        elif step == 4:
            st.markdown("**Theme**")
            _theme_options = ["solar", "obsidian", "aurora"]
            _current_theme = st.session_state.get("theme", "solar")
            _theme_idx = _theme_options.index(_current_theme) if _current_theme in _theme_options else 0
            st.session_state["setup_theme"] = st.radio(
                "Theme",
                options=_theme_options,
                index=_theme_idx,
                horizontal=True,
                label_visibility="collapsed",
            )
            st.caption("Solar is the new light athletic theme · Obsidian is dark · Aurora is brighter dark.")

        col_l, col_r = st.columns([1, 1])
        with col_l:
            if st.button("Back", use_container_width=True, disabled=(step == 1)):
                st.session_state["setup_step"] = step - 1
                st.rerun()
        with col_r:
            if step < total:
                if st.button("Continue", type="primary", use_container_width=True):
                    st.session_state["setup_step"] = step + 1
                    st.rerun()
            else:
                if st.button("Finish setup", type="primary", use_container_width=True):
                    profile = {
                        "display_name": (st.session_state.get("setup_name") or "").strip(),
                        "use_case": st.session_state.get("setup_use_case") or "",
                        "model_preference": st.session_state.get("setup_model_pref") or "",
                        "theme": st.session_state.get("setup_theme") or "solar",
                        "completed_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    _save_profile(profile)
                    st.session_state["theme"] = profile["theme"]
                    st.success("Setup saved.")
                    st.rerun()

    st.stop()


def _auth_gate() -> bool:
    """Return True if the user is authenticated, else render login/setup UI."""
    st.session_state.setdefault("auth_mode", "login")  # login | signup

    # ── Fast path: skip the Supabase network call if recently validated ────
    # get_user() is a round-trip to Supabase — do it at most every 90 s so
    # every button click isn't blocked by a network request.
    if _auth_cached_ok():
        profile = _load_profile()
        if not profile.get("completed_at"):
            _setup_wizard()
        return True

    client = get_client()

    # Streamlit reruns wipe in-memory auth state. Persist Supabase session tokens
    # in session_state and restore them on each run.
    sb_sess = st.session_state.get("supabase_session") or {}
    access_token = sb_sess.get("access_token")
    refresh_token = sb_sess.get("refresh_token")
    if access_token and refresh_token:
        try:
            client.auth.set_session(access_token, refresh_token)
        except Exception:
            try:
                client.auth.set_session(
                    {"access_token": access_token, "refresh_token": refresh_token}
                )
            except Exception:
                pass

    authed = False
    try:
        u = client.auth.get_user()
        authed = bool(getattr(u, "user", None))
    except Exception:
        authed = False

    # Token may be expired but the refresh_token still valid — try to refresh once.
    if not authed and refresh_token:
        try:
            from auth_engine import refresh_session
            new_sess = refresh_session()
            if new_sess and getattr(new_sess, "access_token", None):
                st.session_state["supabase_session"] = {
                    "access_token": new_sess.access_token,
                    "refresh_token": getattr(new_sess, "refresh_token", refresh_token) or refresh_token,
                }
                u = client.auth.get_user()
                authed = bool(getattr(u, "user", None))
        except Exception:
            authed = False

    if authed:
        _auth_mark_ok()
        profile = _load_profile()
        if not profile.get("completed_at"):
            _setup_wizard()
        return True
    else:
        _auth_mark_fail()

    # ── Build logo data URI once (module-level cache, no repeated disk reads) ─
    _starburst_svg = _REPO_ROOT / "assets" / "design-system" / "assets" / "metis-mark-starburst.svg"
    logo_b64 = _read_b64(_LOGOMARK_PNG)
    starburst_b64 = _read_b64(_starburst_svg)

    is_signup = st.session_state["auth_mode"] == "signup"
    title_label = "metis · sign up" if is_signup else "Metis — Sign in"

    # ── Inject auth-page CSS + titlebar + watermark ─────────────────────
    starburst_img = ""
    if starburst_b64:
        starburst_img = f'<img src="data:image/svg+xml;base64,{starburst_b64}" alt="">'

    _GOOGLE_SVG = '<svg viewBox="0 0 24 24" width="18" height="18"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>'
    _GITHUB_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="#0F172A"><path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.203 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.847-2.339 4.695-4.566 4.943.359.31.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0022 12.017C22 6.484 17.522 2 12 2z"/></svg>'

    auth_css = f"""
    <style id="metis-auth-page">
    /* ── Auth page overrides for Streamlit ── */
    .titlebar {{ position: fixed; top: 0; left: 0; right: 0; height: 32px;
      background: rgba(247,250,252,0.85); backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border); display: flex; align-items: center;
      padding: 0 14px; gap: 8px; z-index: 100; }}
    .titlebar .traffic {{ display: flex; gap: 7px; }}
    .traffic span {{ width: 12px; height: 12px; border-radius: 50%; }}
    .traffic .r {{ background: #FF5F57; }} .traffic .y {{ background: #FEBC2E; }} .traffic .g {{ background: #28C840; }}
    .titlebar .title {{ flex: 1; text-align: center; font-size: 12px;
      color: var(--text-muted); font-family: var(--font-mono); font-weight: 500; }}

    .auth-watermark {{ position: fixed; top: 50px; left: 40px; display: flex;
      align-items: center; gap: 10px; z-index: 5; }}
    .auth-watermark img {{ height: 26px; animation: spinSlow 22s linear infinite; }}
    .auth-watermark .wm {{ font-family: ui-serif, "Iowan Old Style", Georgia, serif;
      font-size: 19px; font-weight: 500; letter-spacing: -0.01em; color: var(--text); }}
    .auth-watermark .wm em {{ font-style: italic; }}
    @keyframes spinSlow {{ to {{ transform: rotate(360deg); }} }}

    .auth-card h1 {{ font-family: var(--font-display); font-size: 32px;
      font-weight: 750; letter-spacing: -0.02em; line-height: 1.15; margin: 0 0 10px; }}
    .auth-card h1 em {{ font-family: ui-serif, "Iowan Old Style", Georgia, serif;
      font-style: italic; font-weight: 500;
      background: var(--heritage-grad); -webkit-background-clip: text;
      background-clip: text; -webkit-text-fill-color: transparent; }}
    .auth-card .sub {{ font-size: 14.5px; color: var(--text-muted);
      margin: 0 0 28px; line-height: 1.55; }}
    .auth-card .lockup {{ display: flex; align-items: center; gap: 12px; margin-bottom: 36px; }}
    .auth-card .lockup img {{ height: 42px; animation: spinSlow 22s linear infinite; }}

    .auth-security {{ display: flex; gap: 18px; margin-top: 32px;
      font-family: var(--font-mono); font-size: 10.5px; color: var(--text-subtle);
      justify-content: center; }}
    .auth-security span {{ display: inline-flex; align-items: center; gap: 5px; }}
    .auth-security svg {{ width: 11px; height: 11px; stroke: var(--text-subtle);
      stroke-width: 2; fill: none; stroke-linecap: round; stroke-linejoin: round; }}

    .auth-toggle {{ margin-top: 22px; text-align: center; font-size: 13px; color: var(--text-muted); }}

    /* Override Streamlit padding for auth page */
    [data-testid="stAppViewContainer"] > .main .block-container {{
      padding-top: 56px !important;
    }}
    </style>

    <div class="titlebar">
      <div class="traffic"><span class="r"></span><span class="y"></span><span class="g"></span></div>
      <div class="title">{title_label}</div>
    </div>
    <div class="auth-watermark">{starburst_img}<span class="wm">Met<em>i</em>s</span></div>
    """
    st.html(auth_css)

    # ── OAuth callback handling (runs before form renders) ──────────────
    try:
        qp = dict(st.query_params)
    except Exception:
        qp = {}
    if qp.get("error") or qp.get("error_description"):
        msg = (qp.get("error_description") or qp.get("error") or "Sign-in failed.").strip()
        st.error(msg)
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.session_state.pop("oauth_url", None)
    code = qp.get("code")
    if isinstance(code, str) and code.strip():
        try:
            from auth_engine import complete_oauth

            out = complete_oauth(code=code.strip())
            sess = out.get("session") if isinstance(out, dict) else None
            if sess and getattr(sess, "access_token", None) and getattr(sess, "refresh_token", None):
                st.session_state["supabase_session"] = {
                    "access_token": sess.access_token,
                    "refresh_token": sess.refresh_token,
                }
            try:
                st.query_params.clear()
            except Exception:
                pass
            st.session_state.pop("oauth_url", None)
            st.success("Signed in.")
            st.rerun()
        except Exception as e:
            st.error(str(e))
            try:
                st.query_params.clear()
            except Exception:
                pass
            st.session_state.pop("oauth_url", None)

    # ── Auto-redirect for pending OAuth ─────────────────────────────────
    oauth_url = st.session_state.get("oauth_url")
    if isinstance(oauth_url, str) and oauth_url.startswith("http"):
        # Streamlit renders st.html inside an iframe, so we must target
        # the parent frame to redirect the whole tab, not just the iframe.
        st.html(f"""<script>
(function(){{
  var u={json.dumps(oauth_url)};
  try{{ window.parent.location.href=u; }}catch(e){{
    try{{ window.top.location.href=u; }}catch(e2){{ window.location.href=u; }}
  }}
}})();
</script>""")
        st.link_button("Continue sign-in →", oauth_url, use_container_width=True)
        st.caption("If nothing happens automatically, click the button above.")
        st.stop()
        return False

    # ── Centered auth card ──────────────────────────────────────────────
    _, auth_col, _ = st.columns([1, 1.6, 1])
    with auth_col:
        # Brand lockup + heading
        logo_img_tag = ""
        if logo_b64:
            logo_img_tag = f'<img src="data:image/png;base64,{logo_b64}" alt="Metis">'

        if is_signup:
            heading = "Create your <em>account</em>"
            subtitle = "Free to start. No credit card required. Be running missions in under a minute."
        else:
            heading = "Welcome <em>back</em>"
            subtitle = "Sign in to keep your missions, automations, and library in sync."

        st.html(
            f"""
            <div class="auth-card">
              <div class="lockup">{logo_img_tag}</div>
              <h1>{heading}</h1>
              <p class="sub">{subtitle}</p>
            </div>
            """,
        )

        # ── OAuth buttons ───────────────────────────────────────────────
        ui_port = os.getenv("METIS_UI_PORT", "8501")
        redirect_to = f"http://127.0.0.1:{ui_port}"

        if st.button("  Continue with Google", use_container_width=True, key="oauth_google", icon=":material/public:"):
            try:
                from auth_engine import start_oauth
                url = start_oauth(provider="google", redirect_to=redirect_to)
                st.session_state["oauth_url"] = url
                st.rerun()
            except Exception as e:
                st.error(str(e))
        if st.button("  Continue with GitHub", use_container_width=True, key="oauth_github", icon=":material/code:"):
            try:
                from auth_engine import start_oauth
                url = start_oauth(provider="github", redirect_to=redirect_to)
                st.session_state["oauth_url"] = url
                st.rerun()
            except Exception as e:
                st.error(str(e))

        # ── Divider ─────────────────────────────────────────────────────
        st.html('<div style="display:flex;align-items:center;gap:12px;margin:8px 0 12px;font-family:var(--font-mono);font-size:11px;color:var(--text-subtle);letter-spacing:0.08em;text-transform:uppercase;"><span style="flex:1;height:1px;background:var(--border);"></span>or with email<span style="flex:1;height:1px;background:var(--border);"></span></div>')

        # ── Email / passcode form ───────────────────────────────────────
        email = st.text_input("Email", key="auth_email", placeholder="you@work.com")
        pw = st.text_input("Passcode", type="password", key="auth_pw", placeholder="••••••••")

        if is_signup:
            if st.button("Create account", type="primary", use_container_width=True,
                         key="auth_submit", icon=":material/arrow_forward:"):
                try:
                    from auth_engine import sign_up
                    out = sign_up(email=email.strip(), password=pw)
                    sess = out.get("session") if isinstance(out, dict) else None
                    if sess and getattr(sess, "access_token", None) and getattr(sess, "refresh_token", None):
                        st.session_state["supabase_session"] = {
                            "access_token": sess.access_token,
                            "refresh_token": sess.refresh_token,
                        }
                    st.success("Account created. Check email for verification if prompted, then sign in.")
                except Exception as e:
                    st.error(str(e))

            if st.button("Already have an account? Sign in", key="auth_toggle", use_container_width=True):
                st.session_state["auth_mode"] = "login"
                st.rerun()
        else:
            if st.button("Sign in", type="primary", use_container_width=True,
                         key="auth_submit", icon=":material/arrow_forward:"):
                if not email.strip():
                    st.error("Enter your email first.")
                elif not pw:
                    st.error("Enter your passcode.")
                else:
                    try:
                        from auth_engine import sign_in
                        out = sign_in(email=email.strip(), password=pw)
                        sess = out.get("session") if isinstance(out, dict) else None
                        if sess and getattr(sess, "access_token", None) and getattr(sess, "refresh_token", None):
                            st.session_state["supabase_session"] = {
                                "access_token": sess.access_token,
                                "refresh_token": sess.refresh_token,
                            }
                            st.success("Signed in.")
                            st.rerun()
                        else:
                            st.warning("Signed in but no session returned — check your email for a verification link.")
                    except Exception as e:
                        err = str(e)
                        if "email" in err.lower() and "confirm" in err.lower():
                            st.warning("Please verify your email address first, then try again.")
                        elif "invalid" in err.lower() or "credentials" in err.lower():
                            st.error("Incorrect email or passcode.")
                        else:
                            st.error(err)

            # ── Forgot password flow (toggleable inline) ────────────────
            if st.session_state.get("show_forgot"):
                with st.container(border=True):
                    st.caption("Enter your email and we’ll send a passcode reset link.")
                    reset_email = st.text_input(
                        "Reset email",
                        value=email.strip(),
                        key="auth_reset_email",
                        placeholder="you@work.com",
                    )
                    col_send, col_cancel = st.columns([1, 1])
                    with col_send:
                        if st.button("Send reset email", type="primary", use_container_width=True, key="auth_reset_send"):
                            try:
                                from auth_engine import reset_password
                                if not reset_email.strip():
                                    st.error("Enter your email first.")
                                else:
                                    reset_password(reset_email.strip())
                                    st.success("Reset email sent. Check your inbox.")
                                    st.session_state["show_forgot"] = False
                            except Exception as e:
                                st.error(str(e))
                    with col_cancel:
                        if st.button("Cancel", use_container_width=True, key="auth_reset_cancel"):
                            st.session_state["show_forgot"] = False
                            st.rerun()
            else:
                if st.button("Forgot passcode?", key="auth_forgot", use_container_width=True):
                    st.session_state["show_forgot"] = True
                    st.rerun()

            if st.button("No account yet? Create one — it’s free", key="auth_toggle", use_container_width=True):
                st.session_state["auth_mode"] = "signup"
                st.rerun()

        # ── Security badges ─────────────────────────────────────────────
        st.html("""
        <div class="auth-security">
          <span><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>End-to-end encrypted</span>
          <span><svg viewBox="0 0 24 24"><path d="M12 2L3 7v6c0 5 4 9 9 11 5-2 9-6 9-11V7l-9-5z"/></svg>SOC 2 in progress</span>
        </div>
        """)

    st.stop()
    return False

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
        # Design-kit sidebar header (sb-head pattern).
        _mark_html = ""
        if _LOGOMARK_PNG.exists():
            _mark_b64 = _read_b64(_LOGOMARK_PNG)
            if _mark_b64:
                _mark_html = f'<img src="data:image/png;base64,{_mark_b64}" alt="Metis">'
            else:
                _mark_html = '<svg viewBox="0 0 64 64"><path d="M32 4 L36 28 L60 32 L36 36 L32 60 L28 36 L4 32 L28 28 Z" fill="#fff"/></svg>'
        else:
            _mark_html = '<svg viewBox="0 0 64 64"><path d="M32 4 L36 28 L60 32 L36 36 L32 60 L28 36 L4 32 L28 28 Z" fill="#fff"/></svg>'
        st.markdown(
            f"""<div class="sb-head">
              <div class="mark">{_mark_html}</div>
              <div class="name">Metis</div>
              <div style="margin-left:auto;">
                <span class="chip chip-synced"><span class="chip-dot"></span>Synced</span>
              </div>
            </div>""",
            unsafe_allow_html=True,
        )

        if st.button("＋  New chat", key="new_chat_btn", use_container_width=True,
                     help="Ctrl+Shift+N", icon=":material/add:"):
            st.session_state["session_id"] = f"s_{uuid.uuid4().hex[:10]}"
            st.session_state["messages"] = []
            _bust_caches()
            st.rerun()

        search = st.text_input(
            "Search chats",
            key="chat_search",
            placeholder="Search chats…",
            label_visibility="collapsed",
        )

        st.markdown("<div class='sb-section'>History</div>", unsafe_allow_html=True)
        # Cached 30s — avoids a Supabase round-trip on every Streamlit rerun.
        sessions: list[str] = list(_cached_list_sessions(user_id="") or [])

        if search:
            sessions = [s for s in sessions if search.lower() in s.lower()]

        grouped = _group_sessions(sessions)
        for label, ids in grouped.items():
            if not ids:
                continue
            st.markdown(f"<div class='sb-section'>{label}</div>", unsafe_allow_html=True)
            for sid in ids:
                is_active = sid == st.session_state.get("session_id")
                if st.button(sid, key=f"hist_{sid}", use_container_width=True,
                             type="primary" if is_active else "secondary"):
                    st.session_state["session_id"] = sid
                    st.session_state["messages"] = [
                        {"role": r["role"], "content": r["content"]}
                        for r in load_session(sid, limit=200)
                    ]
                    st.rerun()

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
        st.markdown("<div class='sb-section'>Mode</div>", unsafe_allow_html=True)
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
        st.session_state["auto_write_files"] = st.toggle(
            "Auto-write files",
            value=st.session_state["auto_write_files"],
            help="When Metis outputs code + a filename, write it into generated/ and add an artifact.",
        )
        with st.expander("Auto-write debug", expanded=False):
            rows = st.session_state.get("auto_write_debug") or []
            if not rows:
                st.caption("No auto-write attempts yet.")
            else:
                st.caption("Newest first.")
                for r in rows[:5]:
                    st.code(
                        json.dumps(r, indent=2),
                        language="json",
                    )

        st.markdown("<div class='sb-section'>Tools &amp; outreach</div>", unsafe_allow_html=True)
        st.caption(
            "Enable what you want the AI to be allowed to use. "
            "Credentials still go in `.env` (Twilio, SMTP, etc.)."
        )
        st.session_state["tool_sms"] = st.toggle(
            "Text messages (SMS)",
            value=st.session_state["tool_sms"],
            help="Allows the send_sms skill and SMS via Twilio (TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM).",
        )
        st.session_state["tool_phone_calls"] = st.toggle(
            "Phone calls (outbound)",
            value=st.session_state["tool_phone_calls"],
            help="Allows place_outbound_call. Needs Twilio + a TwiML URL (TWILIO_CALL_TWIML_URL or pass URL in skill).",
        )
        st.session_state["tool_email"] = st.toggle(
            "Email (SMTP)",
            value=st.session_state["tool_email"],
            help="Allows the send_email skill. Set EMAIL_USER, EMAIL_PASS (and optional SMTP_HOST/PORT).",
        )
        st.session_state["tool_calendar"] = st.toggle(
            "Calendar / booking (beta)",
            value=st.session_state["tool_calendar"],
            help="When integrations exist, allows booking-related skills. Off = drafts only.",
        )
        try:
            from comms_policy import smtp_configured, twilio_configured
            st.caption(
                f"SMTP: {'ready' if smtp_configured() else 'not configured'} · "
                f"Twilio: {'ready' if twilio_configured() else 'not configured'}"
            )
        except Exception:
            pass

        st.markdown("<div class='sb-section'>Persona</div>", unsafe_allow_html=True)
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

        st.markdown("<div class='sb-section'>System</div>", unsafe_allow_html=True)
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

        # ── Quick actions (design-kit sb-foot style) ────────────────────
        st.markdown("<div class='sb-foot' style='margin-top:16px;'></div>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⌘ Palette", use_container_width=True, help="Ctrl+K"):
                st.session_state["show_palette"] = not st.session_state["show_palette"]
        with col_b:
            if st.button("⌨ Shortcuts", use_container_width=True, help="Ctrl+/"):
                st.session_state["show_shortcuts"] = not st.session_state["show_shortcuts"]

        col_c, col_d = st.columns(2)
        with col_c:
            if st.button("🎨 Theme", use_container_width=True):
                st.session_state["theme"] = "light" if theme == "obsidian" else "obsidian"
                st.rerun()
        with col_d:
            if st.button("📂 Artifacts", use_container_width=True, help="Ctrl+J"):
                st.session_state["show_artifacts"] = not st.session_state["show_artifacts"]
                st.rerun()

        # ── Brains ───────────────────────────────────────────────────────
        with st.expander("Brains", expanded=False):
            try:
                import brains as _brains
                cur = _brains.active()
                # Cached list — avoids re-walking the brain index on each rerun.
                options = [b["slug"] for b in _cached_list_brains()] or ["default"]
                current_slug = cur.slug if cur else options[0]
                idx = options.index(current_slug) if current_slug in options else 0
                chosen_brain = st.selectbox("Active brain", options=options, index=idx,
                                            key="active_brain_select")
                if chosen_brain != current_slug:
                    try:
                        _brains.switch(chosen_brain)
                        _bust_caches()
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
                    st.markdown("<div class='sb-section'>Recent</div>",
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
                # Cached roster (rarely changes) + live list (free; in-memory).
                specs_data = _cached_list_roster()
                live = set(_roster.list_persistent())
                st.caption(f"{len(specs_data)} agents · {len(live)} persistent")
                for spec_dict in specs_data:
                    spec = _roster.AgentSpec(**spec_dict)
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
                            use_container_width=True, icon=":material/stop:",
                        ):
                            _roster.stop_persistent(spec.slug)
                            _bust_caches()
                            st.rerun()
                    with cols[1]:
                        if not is_live and st.button(
                            "Start", key=f"agent_start_{spec.slug}",
                            use_container_width=True, icon=":material/play_arrow:",
                        ):
                            _roster.spawn_persistent(spec.slug)
                            _bust_caches()
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

        # ── Marketplace ─────────────────────────────────────────────────
        with st.expander("🧩  Marketplace", expanded=False):
            try:
                from marketplace import render_storefront
                render_storefront()
            except Exception as e:
                st.caption(f"Marketplace unavailable: {e}")

        # ── Agent health dashboard ──────────────────────────────────────
        with st.expander("🛰  Agent health", expanded=False):
            try:
                from agent_roster import list_persistent
                health = _cached_agent_health()
                if not health:
                    st.caption("No persistent agents running. Start one with `/agent <slug>`.")
                else:
                    for h in health:
                        cols = st.columns([0.12, 0.5, 0.38])
                        cols[0].markdown(h["status_color"])
                        cols[1].markdown(f"**{h['slug']}**")
                        cols[2].caption(
                            f"{h['label']} · {h['messages_handled']} msgs"
                            + (f" · err: {h['last_error'][:40]}" if h.get("last_error") else "")
                        )
                if list_persistent():
                    if st.button("Refresh", key="agent_health_refresh",
                                 use_container_width=True, icon=":material/refresh:"):
                        _cached_agent_health.clear()
                        st.rerun()
            except Exception as e:
                st.caption(f"Health dashboard unavailable: {e}")

        # ── 2FA / MFA ───────────────────────────────────────────────────
        with st.expander("🔐  Security · 2FA", expanded=False):
            try:
                from auth_engine import enroll_totp, verify_totp, list_mfa_factors, unenroll_totp
                factors = []
                try:
                    factors = list_mfa_factors() or []
                except Exception as e:
                    st.caption(f"Could not list factors: {e}")
                verified = [f for f in factors if (f.get("status") == "verified")]
                pending = [f for f in factors if (f.get("status") != "verified")]

                if verified:
                    st.success(f"2FA enabled · {len(verified)} factor(s)")
                    for f in verified:
                        cols = st.columns([0.7, 0.3])
                        cols[0].caption(f.get("friendly_name") or f.get("id", "unknown"))
                        if cols[1].button("Remove", key=f"mfa_rm_{f.get('id')}", use_container_width=True):
                            unenroll_totp(factor_id=str(f.get("id")))
                            st.rerun()
                else:
                    st.caption("Add an authenticator app (Authy, 1Password, Google Authenticator).")
                    if st.button("Set up 2FA", use_container_width=True, key="mfa_enroll_start"):
                        try:
                            enrollment = enroll_totp()
                            st.session_state["mfa_enrollment"] = enrollment
                        except Exception as e:
                            st.error(f"Enrollment failed: {e}")
                    enrollment = st.session_state.get("mfa_enrollment") or {}
                    if enrollment.get("factor_id"):
                        if enrollment.get("qr_code"):
                            st.image(enrollment["qr_code"], caption="Scan in your authenticator")
                        if enrollment.get("secret"):
                            st.code(enrollment["secret"], language="text")
                        code = st.text_input("Enter the 6-digit code", key="mfa_verify_code", max_chars=10)
                        if st.button("Verify and enable", use_container_width=True, key="mfa_verify_btn"):
                            try:
                                verify_totp(factor_id=str(enrollment["factor_id"]), code=code or "")
                                st.success("2FA enabled.")
                                st.session_state.pop("mfa_enrollment", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Verify failed: {e}")
                if pending:
                    st.caption(f"{len(pending)} pending factor(s) — finish enrollment or remove.")
                    for f in pending:
                        if st.button(f"Cancel pending: {f.get('friendly_name','factor')}",
                                     key=f"mfa_cancel_{f.get('id')}", use_container_width=True):
                            unenroll_totp(factor_id=str(f.get("id")))
                            st.rerun()
            except ImportError:
                st.caption("auth_engine MFA not available.")
            except Exception as e:
                st.caption(f"2FA panel unavailable: {e}")

        # Keep comms / outbound policy aligned with sidebar toggles for this run.
        try:
            from comms_policy import set_from_session
            set_from_session(dict(st.session_state))
        except Exception:
            pass


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
        st.markdown(
            "<div class='row' style='margin-bottom:8px;'>"
            "<span style='font-family:var(--font-display);font-weight:700;font-size:16px;'>Command Palette</span>"
            "<span class='kbd'>⌘K</span></div>",
            unsafe_allow_html=True,
        )
        q = st.text_input("Search actions", key="palette_query", label_visibility="collapsed",
                          placeholder="Search actions…")
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
        st.markdown(
            "<div style='font-family:var(--font-display);font-weight:700;font-size:16px;"
            "margin-bottom:12px;'>Keyboard Shortcuts</div>",
            unsafe_allow_html=True,
        )
        _shortcuts = [
            ("Command palette", "Ctrl", "K"),
            ("New chat", "Ctrl", "⇧", "N"),
            ("Send message", "Ctrl", "↵"),
            ("Stop generation", "Esc", ""),
            ("This cheat sheet", "Ctrl", "/"),
            ("Toggle sidebar", "Ctrl", "B"),
            ("Toggle artifacts", "Ctrl", "J"),
            ("Push-to-talk", "Ctrl", "M"),
        ]
        for label, *keys in _shortcuts:
            keys_html = " ".join(f"<kbd>{k}</kbd>" for k in keys if k)
            st.markdown(
                f"<div style='display:flex;align-items:center;justify-content:space-between;"
                f"padding:8px 0;border-bottom:1px solid var(--border);'>"
                f"<span style='font-size:13.5px;'>{label}</span>"
                f"<span style='display:flex;gap:4px;'>{keys_html}</span></div>",
                unsafe_allow_html=True,
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


# Standalone command-palette slashes that DON'T trigger a chat turn.
# Returns True if the command was handled (caller should skip normal flow).
_COMMAND_HELP_TEXT = """**Slash commands**

| Command | What it does |
| --- | --- |
| `/help` | Show this help |
| `/clear` | Clear the current chat history |
| `/agent <slug>` | Start a persistent agent (e.g. `/agent news_digest`) |
| `/agents` | List all available agent slugs |
| `/role <name>` | Switch active role (manager/coder/thinker/scholar/researcher) |
| `/forge <goal>` | Ask the Coder to forge a new skill in the sandbox |
| `/install <slug>` | Install a marketplace plugin by slug |
| `/sessions` | List recent session ids |
| `/brain <slug>` | Switch the active brain |
| `/code <goal>` | Coder writes and sandbox-tests code |
| `/plan <goal>` | Thinker plans before executing |
| `/research <q>` | Researcher hits the live web |
| `/remember <fact>` | Store a durable fact in memory |
| `/screenshot` | Capture a screenshot |
| `/speak <text>` | Speak text aloud |"""


def _try_command_palette(text: str) -> bool:
    """
    Run command-palette slashes that don't go through the chat pipeline.
    Returns True iff the command was recognized and handled.
    """
    head, rest = _parse_slash(text)
    if head is None:
        return False
    rest = rest.strip()

    if head == "/help":
        st.session_state.setdefault("messages", []).append({
            "role": "assistant",
            "content": _COMMAND_HELP_TEXT,
        })
        return True

    if head == "/clear":
        st.session_state["messages"] = []
        st.toast("Chat cleared.", icon="🧹")
        return True

    if head == "/role":
        valid = {"manager", "coder", "thinker", "scholar", "researcher", "genius", "vision"}
        if rest in valid:
            st.session_state["active_role"] = rest
            st.toast(f"Role set to {rest}.", icon="🎭")
        else:
            st.toast(f"Unknown role. Try: {', '.join(sorted(valid))}", icon="⚠️")
        return True

    if head == "/agents":
        try:
            import agent_roster
            slugs = ", ".join(s.slug for s in agent_roster.list_roster())
            st.session_state.setdefault("messages", []).append({
                "role": "assistant",
                "content": f"**Available agents:** {slugs}",
            })
        except Exception as e:
            st.toast(f"Roster unavailable: {e}", icon="⚠️")
        return True

    if head == "/agent":
        try:
            import agent_roster
            if not rest:
                st.toast("Usage: /agent <slug>", icon="ℹ️")
                return True
            ok = agent_roster.spawn_persistent(rest)
            st.toast(f"Started {rest}." if ok else f"Unknown agent: {rest}",
                     icon="🤖" if ok else "⚠️")
        except Exception as e:
            st.toast(f"Failed: {e}", icon="⚠️")
        return True

    if head == "/forge":
        if not rest:
            st.toast("Usage: /forge <goal>", icon="ℹ️")
            return True
        try:
            from skill_forge import forge_skill
            with st.spinner("Forging skill (sandboxing)…"):
                art = forge_skill(rest)
            st.toast(f"Forged: {art.title}", icon="✨")
            st.session_state.setdefault("messages", []).append({
                "role": "assistant",
                "content": f"**New skill forged**\n\n{art.title}\n\nSaved to `{art.path}`.",
            })
        except Exception as e:
            st.toast(f"Forge failed: {e}", icon="⚠️")
        return True

    if head == "/install":
        if not rest:
            st.toast("Usage: /install <plugin-slug>", icon="ℹ️")
            return True
        try:
            from marketplace import install_plugin
            plugins = _cached_marketplace_plugins()
            target = next((p for p in plugins if p.get("slug") == rest), None)
            if not target:
                st.toast(f"Plugin '{rest}' not in catalog.", icon="⚠️")
                return True
            ok = install_plugin(target)
            _cached_marketplace_plugins.clear()
            st.toast(f"Installed {rest}." if ok else f"Install failed for {rest}.",
                     icon="📦" if ok else "⚠️")
        except Exception as e:
            st.toast(f"Install failed: {e}", icon="⚠️")
        return True

    if head == "/sessions":
        try:
            from memory import list_sessions
            sids = list(list_sessions(limit=20) or [])
            body = "\n".join(f"- `{s}`" for s in sids) or "_(none)_"
            st.session_state.setdefault("messages", []).append({
                "role": "assistant",
                "content": f"**Recent sessions**\n\n{body}",
            })
        except Exception as e:
            st.toast(f"Sessions unavailable: {e}", icon="⚠️")
        return True

    if head == "/brain":
        if not rest:
            st.toast("Usage: /brain <slug>", icon="ℹ️")
            return True
        try:
            import brains
            brains.switch(rest)
            st.toast(f"Active brain → {rest}.", icon="🧠")
        except Exception as e:
            st.toast(f"Brain switch failed: {e}", icon="⚠️")
        return True

    return False


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
        if t == "mission_start":
            st.markdown(
                f"<div class='metis-tool-card'>"
                f"<span>🚀</span> <b>{agent}</b> starting mission · "
                f"<span class='chip chip-running'><span class='chip-dot'></span>{ev.get('mode','')}</span></div>",
                unsafe_allow_html=True,
            )
        elif t in ("tool_start", "tool_end"):
            duration = ev.get("duration_ms")
            dur_badge = ""
            if duration:
                dur_badge = (
                    f" <span class='metric' style='font-size:11.5px;color:var(--text-muted);'>"
                    f"{duration} ms</span>"
                )
            chip = "chip-synced" if t == "tool_end" else "chip-running"
            css = "success" if t == "tool_end" else ""
            st.markdown(
                f"<div class='metis-tool-card {css}'>"
                f"<span>{icon}</span> <b>{tool}</b>"
                f"<span style='color:var(--text-muted);margin-left:6px;font-size:12.5px;'>by {agent}</span>"
                f"{dur_badge}"
                f"<span style='margin-left:auto;'>"
                f"<span class='chip {chip}' style='font-size:10px;'>"
                f"<span class='chip-dot'></span>{'done' if t == 'tool_end' else 'running'}</span></span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        elif t == "thought":
            content = ev.get("content", "")[:120]
            if content.strip():
                st.markdown(
                    f"<div class='metis-tool-card'>"
                    f"<span>💭</span> <span style='color:var(--text-muted);font-style:italic;font-size:13px;'>{content}</span>"
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
_ART_TYPE_ICON = {
    "code": "code", "image": "img", "config": "md",
    "text": "md", "data": "csv", "email": "eml",
}


def _artifacts_pane(container) -> None:
    if not st.session_state["show_artifacts"]:
        return
    with container:
        st.markdown(
            "<div class='page-head' style='margin-bottom:16px;'>"
            "<div><div class='h' style='font-size:22px;'>Artifacts</div>"
            "<div class='sub'>Every run's output, saved and synced.</div></div>"
            "<span class='chip chip-synced'><span class='chip-dot'></span>Live</span></div>",
            unsafe_allow_html=True,
        )
        # Cached 15s — list_artifacts walks the filesystem.
        arts = _cached_list_artifacts(limit=50)
        if not arts:
            st.markdown(
                "<div class='empty'>"
                "<div class='empty-art' style='width:64px;height:64px;border-radius:16px;'>📂</div>"
                "<h3 style='font-size:18px;'>No artifacts yet</h3>"
                "<p>Run /code, /skill, or /screenshot to generate artifacts.</p>"
                "</div>",
                unsafe_allow_html=True,
            )
            return
        for a in arts:
            icon_cls = _ART_TYPE_ICON.get(a.type, "md")
            with st.container(border=True):
                st.markdown(
                    f"<div class='art-head'>"
                    f"<div class='art-iconbox {icon_cls}' style='width:28px;height:28px;border-radius:8px;'>"
                    f"<span style='font-size:14px;'>{'🖼' if a.type == 'image' else '📄'}</span></div>"
                    f"<span class='chip chip-saved' style='font-size:10px;'>"
                    f"<span class='chip-dot'></span>Saved</span></div>"
                    f"<div class='art-name' style='font-size:14px;margin-top:6px;'>{a.title}</div>"
                    f"<div class='art-meta' style='margin-top:3px;'>{a.type}</div>",
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
                # Tool-call cards above the body (design-kit step-row style).
                _render_tool_events(msg.get("tool_events", []))
                # Main content.
                st.markdown(msg.get("content", ""))
                # Show-thinking dropdown (design-kit thinking style).
                reasoning = msg.get("reasoning")
                if reasoning:
                    with st.expander(f"Show thinking · {len(reasoning)//4} chars",
                                     expanded=False):
                        st.markdown(
                            f"<div style='color:var(--text-muted);font-size:12.5px;"
                            f"font-family:var(--font-mono);white-space:pre-wrap;"
                            f"line-height:1.6;'>"
                            f"{reasoning}</div>",
                            unsafe_allow_html=True,
                        )
                # Row of message actions (design-kit iconbtn pattern).
                c1, c2, c3, c_spacer = st.columns([0.8, 0.8, 1.2, 7.2])
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
                with c3:
                    if st.button("💾 Write", key=f"writefile_{i}", help="Write file from this message"):
                        try:
                            _auto_write_generated_file(
                                final_text=msg.get("content", ""),
                                user_text="",
                            )
                        except Exception as e:
                            st.toast(f"Write failed: {e}", icon="⚠️")
            else:
                st.markdown(msg.get("content", ""))


# ── Auto-write files from assistant output ────────────────────────────────────
_FILENAME_RE = re.compile(r"(?<![\\w/\\\\])([A-Za-z0-9_.-]+\\.(?:py|js|ts|tsx|json|md|txt|html|css))\\b")
_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]+)?\\n([\\s\\S]*?)```", re.MULTILINE)
_CODELIKE_RE = re.compile(r"^(?:\\s{0,4})(?:import\\s+|from\\s+|def\\s+|class\\s+|if\\s+__name__\\s*==|#|\\w+\\s*=)", re.MULTILINE)


def _minimal_template_for(filename: str, original_text: str = "") -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".py":
        return (
            "from __future__ import annotations\n\n"
            "def main() -> None:\n"
            "    print(\"TODO: implement\")\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        )
    if ext in (".js",):
        return "console.log(\"TODO: implement\");\n"
    if ext in (".ts",):
        return "export function main(): void {\n  console.log(\"TODO: implement\");\n}\n\nmain();\n"
    if ext in (".tsx",):
        return (
            "import React from \"react\";\n\n"
            "export default function App() {\n"
            "  return <div>TODO: implement</div>;\n"
            "}\n"
        )
    if ext == ".json":
        return "{\n  \"todo\": \"implement\"\n}\n"
    if ext == ".html":
        return (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "  <meta charset=\"utf-8\" />\n  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />\n"
            "  <title>Metis Generated</title>\n</head>\n<body>\n  <h1>TODO: implement</h1>\n</body>\n</html>\n"
        )
    if ext == ".css":
        return "/* TODO: implement */\n"
    if ext == ".md":
        return "# TODO\n\n- implement\n"
    if ext == ".txt":
        return (original_text or "TODO: implement\n").rstrip() + "\n"
    return (original_text or "TODO: implement\n").rstrip() + "\n"


def _safe_filename(name: str) -> str:
    base = Path(name).name  # drop any path components
    # allowlist characters
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
    if not base or base.startswith(".") or ".." in base:
        return ""
    return base


def _auto_write_generated_file(final_text: str, user_text: str) -> None:
    if not st.session_state.get("auto_write_files", True):
        return

    dbg = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "enabled": True,
        "filename_candidates": [],
        "filename": "",
        "extracted_chars": 0,
        "out_dir": "",
        "out_path": "",
        "status": "started",
        "error": "",
    }

    # Look for an explicit filename mention in either user prompt or assistant reply,
    # falling back to a filename explicitly requested by the Director.
    candidates = _FILENAME_RE.findall(final_text) + _FILENAME_RE.findall(user_text)
    pending = (st.session_state.get("pending_filename") or "").strip()
    if pending:
        candidates.append(pending)
    dbg["filename_candidates"] = candidates[:5]
    if not candidates:
        dbg["status"] = "skipped_no_filename"
        st.session_state["auto_write_debug"] = [dbg] + (st.session_state.get("auto_write_debug") or [])
        return

    filename = _safe_filename(candidates[0])
    if not filename:
        dbg["status"] = "skipped_unsafe_filename"
        st.session_state["auto_write_debug"] = [dbg] + (st.session_state.get("auto_write_debug") or [])
        return
    dbg["filename"] = filename

    text = final_text or ""

    # Prefer fenced code blocks.
    m = _FENCE_RE.search(text)
    code = ""
    if m:
        code = (m.group(1) or "").rstrip() + "\n"
    else:
        # Fallback: extract the longest contiguous "code-like" block.
        lines = text.splitlines()
        best: list[str] = []
        cur: list[str] = []
        for ln in lines:
            if _CODELIKE_RE.match(ln) or (cur and (ln.startswith(" ") or ln.startswith("\t"))):
                cur.append(ln.rstrip("\n"))
            else:
                if len(cur) > len(best):
                    best = cur
                cur = []
        if len(cur) > len(best):
            best = cur
        if best:
            code = "\n".join(best).rstrip() + "\n"

    if not code.strip():
        # Stricter deterministic fallback: write a minimal valid starter template
        # for the requested file type.
        code = _minimal_template_for(filename, original_text=text)
        dbg["status"] = "fallback_wrote_min_template"
    dbg["extracted_chars"] = len(code)

    try:
        base_dir = Path(__file__).resolve().parent
        out_dir = base_dir / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_text(code, encoding="utf-8")
        dbg["out_dir"] = str(out_dir)
        dbg["out_path"] = str(out_path)
        dbg["status"] = "wrote_file"
    except Exception as e:
        dbg["status"] = "error"
        dbg["error"] = str(e)
        st.session_state["auto_write_debug"] = [dbg] + (st.session_state.get("auto_write_debug") or [])
        raise

    art = Artifact(
        type="code",
        title=f"generated/{filename}",
        language=out_path.suffix.lstrip(".") or "text",
        path=str(out_path),
        metadata={"source": "auto_write", "filename": filename},
    )
    save_artifact(art)
    st.session_state["active_artifact_id"] = art.id
    st.toast(f"Wrote {out_path}", icon="✅")

    st.session_state["auto_write_debug"] = [dbg] + (st.session_state.get("auto_write_debug") or [])
    # Clear pending filename once we successfully wrote something.
    st.session_state["pending_filename"] = ""


# ── Send + stream pipeline ───────────────────────────────────────────────────
def _send_prompt(user_text: str) -> None:
    # Standalone slash commands (don't go through chat pipeline).
    if _try_command_palette(user_text):
        return

    slash, payload = _parse_slash(user_text)
    mode = "chat"
    routed_role = "manager"

    # Capture a requested filename early so auto-write can be deterministic.
    try:
        fname_hits = _FILENAME_RE.findall(user_text or "")
        if fname_hits:
            st.session_state["pending_filename"] = _safe_filename(fname_hits[0]) or ""
    except Exception:
        pass

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
        # Live thinking expander — auto-expands as <think> tokens arrive,
        # so the user can watch the reasoning unfold instead of waiting.
        thinking_expander = st.expander("Show thinking", expanded=st.session_state.get("auto_show_thinking", True))
        thinking_slot = thinking_expander.empty()

    persona_prompt = build_system_prompt(get_active_persona())
    try:
        from comms_policy import build_comms_system_block, set_from_session
        set_from_session(dict(st.session_state))
        comms_block = build_comms_system_block(st.session_state)
    except Exception:
        comms_block = ""
    context_msgs = inject_context(st.session_state["session_id"], user_text)
    system_msg = {
        "role": "system",
        "content": (persona_prompt + "\n\n" + comms_block).strip() if comms_block else persona_prompt,
    }
    user_msg = {"role": "user", "content": payload if slash in SLASH_MODES else user_text}
    conversation = [system_msg] + context_msgs + [user_msg]

    token_container = assistant_container.empty()
    token_buf: list[str] = []
    started = time.time()

    try:
        # Reliability guard: if the user requested local mode but Ollama is down,
        # return a deterministic error message (and still allow auto-write).
        if st.session_state.get("local_mode", True):
            try:
                from brain_engine import list_local_models
                if not list_local_models():
                    msg = (
                        "Local brain is selected but Ollama appears to be down.\n\n"
                        "Start it with:\n"
                        "`ollama serve`\n\n"
                        "Or toggle **Local (offline) brain** OFF to use a cloud provider if configured."
                    )
                    token_buf.append(msg)
                    token_container.markdown(msg)
                    raise StopIteration()
            except StopIteration:
                raise
            except Exception:
                # If health check fails, we still try streaming.
                pass

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
                    # Update the live thinking pane every few hundred chars.
                    _r_text = "".join(reasoning_buf)
                    if len(_r_text) % 24 < 2 or len(_r_text) < 24:
                        thinking_slot.markdown(
                            f"<div style='font-family:var(--font-mono);font-size:11.5px;"
                            f"color:var(--text-muted);white-space:pre-wrap;'>{_r_text[-2000:]}</div>",
                            unsafe_allow_html=True,
                        )
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
    except StopIteration:
        # Used for deterministic early-exit paths above.
        pass
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

    # Auto-write any generated code file (best-effort).
    try:
        _auto_write_generated_file(final_text=final_text, user_text=user_text)
    except Exception as e:
        st.toast(f"Auto-write failed: {e}", icon="⚠️")

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
    wrapper_class = "metis-thinking" if thinking else ""
    st.markdown(
        f"<div class='{wrapper_class}' style='text-align:center;padding-top:8px;'>"
        f"<div class='metis-aura'><div class='metis-core'>◆</div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    snap = _cached_health_snapshot()
    role = st.session_state.get("active_role", "manager")
    brain_chip = ""
    if snap.get("brain"):
        brain_chip = (
            f" <span class='chip chip-saved' style='font-size:11px;margin-left:6px;'>"
            f"<span class='chip-dot'></span>{snap['brain']}</span>"
        )
    status_chip = (
        "<span class='chip chip-running'><span class='chip-dot'></span>Thinking</span>"
        if thinking
        else "<span class='chip chip-synced'><span class='chip-dot'></span>Ready</span>"
    )
    st.markdown(
        f"<div style='text-align:center;margin:8px 0 4px 0;'>"
        f"<span class='page-head' style='display:inline-block;margin-bottom:0;'>"
        f"<span class='h' style='font-size:24px;'>Metis</span></span>"
        f"</div>"
        f"<div style='text-align:center;margin-bottom:12px;display:flex;align-items:center;"
        f"justify-content:center;gap:8px;flex-wrap:wrap;'>"
        f"{status_chip}"
        f"<span class='chip chip-ready' style='font-size:11px;'>{role}</span>"
        f"{brain_chip}"
        f"</div>",
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
    _auth_gate()
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
                colv1, colv2, colv3 = st.columns([3, 1, 1])
                with colv1:
                    st.caption(
                        "Click **Browser mic** to dictate via the Web Speech API "
                        "(no server-side deps). Use **Listen** for the local mic."
                    )
                with colv2:
                    if st.button("Listen", key="voice_listen", use_container_width=True,
                                 help="Server-side microphone (requires PyAudio + voice_io)"):
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
                with colv3:
                    voice_in = st.text_input(
                        "Browser mic transcript",
                        key="browser_voice_text",
                        label_visibility="collapsed",
                        placeholder="(transcript)",
                    )
                    if voice_in and not st.session_state.get("pending_voice_text"):
                        st.session_state["pending_voice_text"] = voice_in
                        st.session_state["browser_voice_text"] = ""

                # Browser-side dictation: writes the transcript into the
                # text_input above by simulating typing + an input event so
                # Streamlit's React runtime picks it up on the next rerun.
                st.html("""
<button id="metis-mic-btn" type="button" class="btn btn-secondary"
        style="width:100%;height:40px;font-size:14px;">
  🎤 Browser mic
</button>
<script>
(function() {
  const btn = document.getElementById('metis-mic-btn');
  if (!btn) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    btn.disabled = true;
    btn.textContent = 'Browser mic (unsupported)';
    btn.style.opacity = '.5';
    return;
  }
  const rec = new SR();
  rec.continuous = false;
  rec.interimResults = false;
  rec.lang = navigator.language || 'en-US';
  let active = false;

  function findStreamlitInput() {
    // Look across the parent document since st.html runs in an iframe.
    const docs = [document];
    try { if (window.parent && window.parent.document) docs.push(window.parent.document); } catch(e) {}
    for (const d of docs) {
      const el = d.querySelector('input[aria-label="Browser mic transcript"]');
      if (el) return el;
    }
    return null;
  }
  function setNativeValue(el, value) {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    ).set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  rec.onresult = (e) => {
    const text = (e.results[0] && e.results[0][0] && e.results[0][0].transcript) || '';
    const el = findStreamlitInput();
    if (el && text) setNativeValue(el, text);
    btn.textContent = '🎤 Browser mic';
    active = false;
  };
  rec.onerror = (e) => {
    btn.textContent = '🎤 Browser mic';
    active = false;
  };
  rec.onend = () => {
    btn.textContent = '🎤 Browser mic';
    active = false;
  };
  btn.addEventListener('click', () => {
    if (active) { rec.stop(); active = false; return; }
    try { rec.start(); active = true; btn.textContent = '🔴 Listening…'; }
    catch (e) { active = false; }
  });
})();
</script>
                """)

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
