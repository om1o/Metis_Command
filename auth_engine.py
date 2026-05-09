from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Literal

from supabase_client import get_client

# Verbose by default while we're debugging OAuth — flip METIS_AUTH_DEBUG=0
# in .env to silence once it's stable.
_DEBUG = os.getenv("METIS_AUTH_DEBUG", "1") not in ("0", "false", "False")
_log = logging.getLogger("metis.auth")
if _DEBUG and not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[auth] %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.DEBUG)


def _redact(s: str | None, keep: int = 6) -> str:
    if not s: return "<empty>"
    if len(s) <= keep * 2: return f"{s[:keep]}…"
    return f"{s[:keep]}…{s[-keep:]} ({len(s)} chars)"

# ── PKCE verifier disk cache ─────────────────────────────────────────────────
# st.session_state is per-WebSocket session and is wiped when the browser
# navigates to the OAuth provider and back.  We persist the PKCE code_verifier
# to a temp file on disk so it survives the redirect round-trip.

_PKCE_DIR = Path(tempfile.gettempdir()) / "metis_pkce"


def _save_verifier(state: str, verifier: str) -> None:
    _PKCE_DIR.mkdir(parents=True, exist_ok=True)
    # Save by state (unique per request) instead of just provider.
    (_PKCE_DIR / f"{state}.txt").write_text(verifier, encoding="utf-8")


def _load_verifier(state: str | None = None) -> str | None:
    """Return stored verifier for *state*, or try the most recent as fallback."""
    if not _PKCE_DIR.exists():
        return None
    if state:
        p = _PKCE_DIR / f"{state}.txt"
        if p.exists():
            v = p.read_text(encoding="utf-8").strip()
            # Cleanup after use
            try: p.unlink()
            except Exception: pass
            return v or None
    # Fallback: return the most-recently-modified verifier file
    files = list(_PKCE_DIR.glob("*.txt"))
    if not files:
        return None
    latest = max(files, key=lambda f: f.stat().st_mtime)
    v = latest.read_text(encoding="utf-8").strip()
    return v or None


def sign_up(email: str, password: str) -> dict:
    """Register a new user. Returns the user object on success."""
    client = get_client()
    resp = client.auth.sign_up({"email": email, "password": password})
    # Handle both AuthResponse objects and dicts
    user = getattr(resp, "user", None) or (resp.get("user") if isinstance(resp, dict) else None)
    session = getattr(resp, "session", None) or (resp.get("session") if isinstance(resp, dict) else None)
    return {"user": user, "session": session}


def sign_in(email: str, password: str) -> dict:
    """Sign in with email + password. Returns session and user."""
    client = get_client()
    resp = client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    user = getattr(resp, "user", None) or (resp.get("user") if isinstance(resp, dict) else None)
    session = getattr(resp, "session", None) or (resp.get("session") if isinstance(resp, dict) else None)
    return {"user": user, "session": session}


def sign_out() -> None:
    """Sign out the current user and invalidate the session."""
    client = get_client()
    client.auth.sign_out()


def get_current_user() -> dict | None:
    """Return the currently authenticated user, or None if not signed in."""
    client = get_client()
    response = client.auth.get_user()
    return response.user if response else None


def reset_password(email: str) -> None:
    """Send a password-reset email to the given address."""
    client = get_client()
    client.auth.reset_password_email(email)


def refresh_session() -> dict | None:
    """Refresh the current session token. Returns updated session or None."""
    client = get_client()
    response = client.auth.refresh_session()
    return response.session if response else None


def start_oauth(*, provider: OAuthProvider, redirect_to: str) -> tuple[str, str]:
    """
    Start an OAuth flow and return ``(authorization_url, state)``.

    The state and PKCE verifier are saved to disk so they survive the
    redirect (the in-memory storage on the client may be lost across
    requests / processes).
    """
    client = get_client()
    state = secrets.token_urlsafe(16)
    _log.debug("start_oauth provider=%s redirect_to=%s state=%s",
               provider, redirect_to, _redact(state))

    resp: Any = client.auth.sign_in_with_oauth(
        {
            "provider": provider,
            "options": {
                "redirect_to": redirect_to,
                "skip_browser_redirect": True,
            },
        }
    )
    url = getattr(resp, "url", None)
    if not isinstance(url, str) or not url:
        data = getattr(resp, "data", None)
        url = getattr(data, "url", None) if data is not None else None
    if not isinstance(url, str) or not url:
        raise RuntimeError("OAuth start failed: missing authorization URL")

    # Pull the PKCE verifier the supabase library just generated so we
    # can persist it across the browser redirect. supabase-auth 2.x
    # stores it at `{_storage_key}-code-verifier`.
    code_verifier: str | None = None
    try:
        storage = getattr(client.auth, "_storage", None)
        storage_key = getattr(client.auth, "_storage_key", "supabase.auth.token")
        if storage and hasattr(storage, "get_item"):
            code_verifier = storage.get_item(f"{storage_key}-code-verifier")
        if code_verifier:
            _save_verifier(state, code_verifier)
            _log.debug("start_oauth saved verifier=%s for state=%s",
                       _redact(code_verifier), _redact(state))
        else:
            _log.warning("start_oauth: NO verifier found in storage after "
                         "sign_in_with_oauth. PKCE will fail at exchange. "
                         "storage=%r storage_key=%r",
                         type(storage).__name__ if storage else None, storage_key)
    except Exception as e:
        _log.warning("start_oauth verifier extract failed: %s", e)

    # Append state to the URL if not already present
    if url and "state=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}state={state}"

    return url, state


# ── MFA / 2FA (TOTP) ─────────────────────────────────────────────────────────

def enroll_totp(*, friendly_name: str = "Metis Authenticator") -> dict:
    """
    Begin TOTP MFA enrollment.

    Returns a dict with:
        factor_id: id to pass to verify_totp() and challenge()
        qr_code:   base64 SVG/PNG payload the user scans into Authy/1Password
        secret:    raw TOTP secret (for manual entry)
        uri:       otpauth:// URI for direct registration

    Raises if Supabase MFA is not enabled for the project.
    """
    client = get_client()
    resp: Any = client.auth.mfa.enroll({
        "factor_type": "totp",
        "friendly_name": friendly_name,
    })
    data = getattr(resp, "data", None) or resp
    factor = getattr(data, "totp", None) or (data.get("totp") if isinstance(data, dict) else None) or {}
    return {
        "factor_id": getattr(data, "id", None) or (data.get("id") if isinstance(data, dict) else None),
        "qr_code":   getattr(factor, "qr_code", None) or (factor.get("qr_code") if isinstance(factor, dict) else None),
        "secret":    getattr(factor, "secret", None)  or (factor.get("secret")  if isinstance(factor, dict) else None),
        "uri":       getattr(factor, "uri", None)     or (factor.get("uri")     if isinstance(factor, dict) else None),
    }


def verify_totp(*, factor_id: str, code: str) -> dict:
    """
    Verify a 6-digit TOTP code against an enrolled factor.

    On success, the user's session AAL is upgraded so MFA-gated routes
    will accept them. Returns the new session payload.
    """
    client = get_client()
    challenge: Any = client.auth.mfa.challenge({"factor_id": factor_id})
    challenge_id = (
        getattr(challenge, "id", None)
        or (challenge.get("id") if isinstance(challenge, dict) else None)
        or (getattr(challenge, "data", None) and getattr(challenge.data, "id", None))
    )
    verify: Any = client.auth.mfa.verify({
        "factor_id": factor_id,
        "challenge_id": challenge_id,
        "code": code.strip(),
    })
    data = getattr(verify, "data", None) or verify
    return {
        "user": getattr(data, "user", None) or (data.get("user") if isinstance(data, dict) else None),
        "session": getattr(data, "session", None) or (data.get("session") if isinstance(data, dict) else None),
    }


def list_mfa_factors() -> list[dict]:
    """Return a list of enrolled factors for the current user."""
    client = get_client()
    resp: Any = client.auth.mfa.list_factors()
    data = getattr(resp, "data", None) or resp
    factors = getattr(data, "all", None) or (data.get("all") if isinstance(data, dict) else None) or []
    out: list[dict] = []
    for f in factors:
        out.append({
            "id": getattr(f, "id", None) or (f.get("id") if isinstance(f, dict) else None),
            "factor_type": getattr(f, "factor_type", None) or (f.get("factor_type") if isinstance(f, dict) else None),
            "friendly_name": getattr(f, "friendly_name", None) or (f.get("friendly_name") if isinstance(f, dict) else None),
            "status": getattr(f, "status", None) or (f.get("status") if isinstance(f, dict) else None),
        })
    return out


def unenroll_totp(*, factor_id: str) -> bool:
    """Remove a TOTP factor."""
    client = get_client()
    try:
        client.auth.mfa.unenroll({"factor_id": factor_id})
        return True
    except Exception:
        return False


def complete_oauth(*, code: str, state: str | None = None) -> dict:
    """
    Complete OAuth by exchanging the returned ``code`` for a Supabase
    session.

    Supabase's PKCE flow needs the ``code_verifier`` that was generated
    when ``start_oauth`` ran. The library normally pulls it from
    ``client.auth._storage`` — but in our case the initial sign-in
    happened in a different process / WebSocket session, so we
    persisted the verifier to disk keyed by the OAuth state and
    re-inject it here.

    Compatible with supabase-auth 2.x where
    ``exchange_code_for_session(params: CodeExchangeParams)``
    expects a dict (TypedDict). We do NOT fall back to passing a
    bare string — that signature was removed in 2.x and produces
    a misleading ``'str' object has no attribute 'get'`` error.
    """
    client = get_client()
    code_verifier = _load_verifier(state)
    _log.debug("complete_oauth state=%s code=%s verifier=%s pkce_dir=%s files=%s",
               _redact(state), _redact(code), _redact(code_verifier),
               _PKCE_DIR, [p.name for p in _PKCE_DIR.glob("*.txt")] if _PKCE_DIR.exists() else [])

    # Re-inject the verifier so the storage-fallback inside
    # exchange_code_for_session can also find it.
    if code_verifier:
        try:
            storage = getattr(client.auth, "_storage", None)
            storage_key = getattr(client.auth, "_storage_key", "supabase.auth.token")
            if storage and hasattr(storage, "set_item"):
                storage.set_item(f"{storage_key}-code-verifier", code_verifier)
                _log.debug("complete_oauth re-injected verifier into _storage")
        except Exception as e:
            _log.warning("complete_oauth verifier re-inject failed: %s", e)

    fn = getattr(client.auth, "exchange_code_for_session", None)
    if not callable(fn):
        raise RuntimeError(
            "Installed Supabase client lacks exchange_code_for_session. "
            "Upgrade `supabase` and `supabase-auth` in requirements."
        )

    # Build the params dict. Always include auth_code; include
    # code_verifier only if we actually have one (otherwise
    # supabase-auth's storage-fallback handles it).
    params: dict[str, Any] = {"auth_code": code}
    if code_verifier:
        params["code_verifier"] = code_verifier

    try:
        resp = fn(params)
        _log.debug("complete_oauth exchange OK; got session=%s",
                   bool(getattr(resp, "session", None)))
    except Exception as e:
        _log.error("complete_oauth exchange FAILED: %r", e)
        # Most common real-world failures, in priority order:
        #   - "invalid request: both auth code and code verifier should be non-empty"
        #     → start_oauth never persisted the verifier (storage extraction failed).
        #   - "PKCE flow not supported"
        #     → Supabase project misconfigured.
        #   - "invalid grant" / "code expired"
        #     → user took >10 min between redirect and submit, OR refreshed callback.
        # Surface the underlying error so the UI can show something useful.
        raise RuntimeError(f"OAuth code exchange failed: {e}") from e

    session = (
        getattr(resp, "session", None)
        or getattr(getattr(resp, "data", None), "session", None)
    )
    user = (
        getattr(resp, "user", None)
        or getattr(getattr(resp, "data", None), "user", None)
    )
    if session is None:
        raise RuntimeError(
            "OAuth exchange returned no session. "
            "Check that Google/GitHub providers are enabled in Supabase "
            "and that http://127.0.0.1:3000/oauth/callback is in the "
            "Auth → URL Configuration → Redirect URLs allowlist."
        )
    return {"user": user, "session": session}
