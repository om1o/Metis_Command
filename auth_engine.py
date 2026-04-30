from __future__ import annotations

from typing import Any, Literal

from supabase_client import get_client


def sign_up(email: str, password: str) -> dict:
    """Register a new user. Returns the user object on success."""
    client = get_client()
    response = client.auth.sign_up({"email": email, "password": password})
    return {"user": response.user, "session": response.session}


def sign_in(email: str, password: str) -> dict:
    """Sign in with email + password. Returns session and user."""
    client = get_client()
    response = client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    return {"user": response.user, "session": response.session}


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


OAuthProvider = Literal["google", "github"]


def start_oauth(*, provider: OAuthProvider, redirect_to: str) -> str:
    """
    Start an OAuth flow and return a provider authorization URL.

    This is intentionally thin so the UI can keep Supabase completely hidden.
    """
    client = get_client()
    # supabase-py returns an object that may contain `.url` or `.data.url`
    resp: Any = client.auth.sign_in_with_oauth(
        {"provider": provider, "options": {"redirect_to": redirect_to}}
    )
    url = getattr(resp, "url", None)
    if isinstance(url, str) and url:
        return url
    data = getattr(resp, "data", None)
    url = getattr(data, "url", None) if data is not None else None
    if isinstance(url, str) and url:
        return url
    raise RuntimeError("OAuth start failed: missing authorization URL")


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


def complete_oauth(*, code: str) -> dict:
    """
    Complete OAuth by exchanging the returned `code` for a session.

    Returns a dict containing `user` and `session` when available.
    """
    client = get_client()

    # Different supabase-py versions expose slightly different method names /
    # signatures. We try the common variants in a safe order.
    resp: Any | None = None
    last_err: Exception | None = None
    for fn_name, payload in (
        ("exchange_code_for_session", code),
        ("exchange_code_for_session", {"auth_code": code}),
        ("get_session_from_url", code),
        ("get_session_from_url", {"code": code}),
    ):
        fn = getattr(client.auth, fn_name, None)
        if not callable(fn):
            continue
        try:
            resp = fn(payload)
            break
        except Exception as e:
            last_err = e
            resp = None

    if resp is None:
        raise RuntimeError(f"OAuth completion failed: {last_err or 'unknown error'}")

    user = getattr(resp, "user", None) or getattr(getattr(resp, "data", None), "user", None)
    session = getattr(resp, "session", None) or getattr(getattr(resp, "data", None), "session", None)
    return {"user": user, "session": session}
