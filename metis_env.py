"""
Load environment variables from predictable paths.

The API bridge is often started with ``uvicorn`` from a subdirectory (e.g. ``desktop-ui/``)
or from an IDE with a non-repo cwd. ``load_dotenv()`` alone only checks the process cwd,
so ``GROQ_API_KEY`` / ``GLM_API_KEY`` in the repo root ``.env`` were invisible — Connections
showed "no key" even when the file was correct.

Load order (later layers override earlier keys):
  1. ``<repo>/.env``            — primary project file
  2. ``<cwd>/.env``             — local overlay if it is a different file
  3. ``METIS_ENV_FILE``         — explicit path (highest precedence)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent


def load_metis_env() -> None:
    """Idempotent enough for repeated imports; safe to call from launch + api_bridge."""
    primary = REPO_ROOT / ".env"
    if primary.is_file():
        load_dotenv(primary, override=False)

    try:
        cwd_env = Path.cwd().resolve() / ".env"
        if cwd_env.is_file() and cwd_env.resolve() != primary.resolve():
            load_dotenv(cwd_env, override=True)
    except OSError:
        pass

    explicit = (os.getenv("METIS_ENV_FILE") or "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            load_dotenv(p, override=True)

    # Legacy: dotenv search from cwd upward (cheap no-op when vars already set)
    load_dotenv(override=False)


def dotenv_tip() -> str:
    """Short path hint for UI / health messages."""
    return str(REPO_ROOT / ".env")


def provider_key_hint(env_key: str) -> dict[str, str]:
    """Unified copy for Connections when an API key env var is empty."""
    fp = dotenv_tip()
    return {
        "ok": False,
        "reason": "no key in .env",
        "fix": (
            f'Add `{env_key}=…` to `{fp}` (you can copy from `.env.example`), save the file, '
            "then restart the bridge (`python launch.py` or restart your uvicorn process). "
            "If the keys live outside the repo, set `METIS_ENV_FILE=/full/path/to/env`."
        ),
    }
