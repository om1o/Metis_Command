"""
Local auth token — per-install bearer token every non-health API call must
present.  Generated on first boot; stored in identity/local_auth.token
(0600 on POSIX), gitignored so it never leaves the machine.
"""

from __future__ import annotations

import os
import secrets
import stat

from safety import PATHS

TOKEN_FILE = PATHS.identity / "local_auth.token"


def get_or_create() -> str:
    if TOKEN_FILE.exists():
        try:
            return TOKEN_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    return token


def verify(presented: str | None) -> bool:
    if not presented:
        return False
    stored = get_or_create()
    if len(stored) != len(presented):
        return False
    return secrets.compare_digest(stored, presented)


def rotate() -> str:
    try:
        TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return get_or_create()


def bearer_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_or_create()}"}
