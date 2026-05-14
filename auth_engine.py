from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Literal

from supabase_client import get_client

OAuthProvider = Literal["google", "github"]

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
            try:
                p.unlink()
            except Exception:
                pass
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

    The state and PKCE verifier are saved to disk so they survive the redirect.
    """
    client = get_client()
    state = secrets.token_urlsafe(16)
    
    # Explicitly request PKCE flow if the library supports it via options.
    resp: Any = client.auth.sign_in_with_oauth(
        {
            "provider": provider, 
            "options": {
                "redirect_to": redirect_to,
                "skip_browser_redirect": True,
            }
        }
    )
    url = getattr(resp, "url", None)
    if not isinstance(url, str) or not url:
        data = getattr(resp, "data", None)
        url = getattr(data, "url", None) if data is not None else None
    if not isinstance(url, str) or not url:
        raise RuntimeError("OAuth start failed: missing authorization URL")

    # Extract the PKCE code_verifier from the client's internal storage.
    code_verifier: str | None = None
    try:
        storage = getattr(client.auth, "_storage", None)
        storage_key = getattr(client.auth, "_storage_key", "supabase.auth.token")
        if storage and hasattr(storage, "get_item"):
            code_verifier = storage.get_item(f"{storage_key}-code-verifier")
        if code_verifier:
            _save_verifier(state, code_verifier)
    except Exception:
        pass

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
    Complete OAuth by exchanging the returned `code` for a session.

    If ``state`` is passed, we load the specific verifier for that request.
    """
    client = get_client()
    code_verifier = _load_verifier(state)

    # Inject verifier back into the client's in-memory storage so
    # exchange_code_for_session can find it.
    if code_verifier:
        try:
            storage = getattr(client.auth, "_storage", None)
            storage_key = getattr(client.auth, "_storage_key", "supabase.auth.token")
            if storage and hasattr(storage, "set_item"):
                storage.set_item(f"{storage_key}-code-verifier", code_verifier)
        except Exception:
            pass

    resp: Any | None = None
    last_err: Exception | None = None

    attempts: list[tuple[str, Any]] = [
        ("exchange_code_for_session", {"auth_code": code, "code_verifier": code_verifier}),
        ("exchange_code_for_session", {"auth_code": code}),
        ("exchange_code_for_session", code),
    ]

    for fn_name, payload in attempts:
        fn = getattr(client.auth, fn_name, None)
        if not callable(fn):
            continue
        try:
            resp = fn(payload)
            # Treat a response with no session as failure (try next attempt).
            if resp is not None:
                _sess = getattr(resp, "session", None) or getattr(
                    getattr(resp, "data", None), "session", None
                )
                if _sess is None:
                    last_err = RuntimeError("No session in response")
                    resp = None
                    continue
            break
        except Exception as e:
            last_err = e
            resp = None

    if resp is None:
        raise RuntimeError(
            f"OAuth completion failed: {last_err or 'unknown error'}. "
            "Make sure Google/GitHub OAuth providers are enabled in your Supabase project "
            "and the redirect URL is listed in Auth → URL Configuration."
        )

    user = getattr(resp, "user", None) or getattr(getattr(resp, "data", None), "user", None)
    session = getattr(resp, "session", None) or getattr(getattr(resp, "data", None), "session", None)
    return {"user": user, "session": session}
