"""Auth token lifecycle."""

from __future__ import annotations


def test_first_call_creates_token(_sandbox_paths):
    import auth_local
    t1 = auth_local.get_or_create()
    assert t1 and len(t1) >= 32
    # Idempotent - second call returns the same token.
    assert auth_local.get_or_create() == t1
    assert auth_local.TOKEN_FILE.exists()


def test_verify_success_and_failure(_sandbox_paths):
    import auth_local
    t = auth_local.get_or_create()
    assert auth_local.verify(t) is True
    assert auth_local.verify(t + "x") is False
    assert auth_local.verify("") is False
    assert auth_local.verify(None) is False


def test_rotate_invalidates_old(_sandbox_paths):
    import auth_local
    old = auth_local.get_or_create()
    new = auth_local.rotate()
    assert old != new
    assert not auth_local.verify(old)
    assert auth_local.verify(new)


def test_bearer_header_shape(_sandbox_paths):
    import auth_local
    h = auth_local.bearer_header()
    assert h["Authorization"].startswith("Bearer ")
    assert len(h["Authorization"].split(" ", 1)[1]) >= 32
