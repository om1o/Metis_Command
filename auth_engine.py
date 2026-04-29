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
