"""
Auto-update checker for Metis Command.

Probes GitHub Releases and caches the result locally so the UI can
surface an update badge without slowing down startup.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_FILE = _ROOT / ".update_cache.json"
_RELEASES_URL = "https://api.github.com/repos/om1o/Metis_Command/releases/latest"


def _fetch_latest() -> dict | None:
    try:
        req = urllib.request.Request(
            _RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "MetisCommand-Updater/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def cached_check(max_age_s: float = 3600) -> dict | None:
    """Return latest release info, reading from cache if fresh enough."""
    now = time.time()
    if _CACHE_FILE.exists():
        try:
            cached = json.loads(_CACHE_FILE.read_text())
            if now - float(cached.get("_fetched_at", 0)) < max_age_s:
                return cached
        except Exception:
            pass
    result = _fetch_latest()
    if result:
        result["_fetched_at"] = now
        try:
            _CACHE_FILE.write_text(json.dumps(result))
        except Exception:
            pass
    return result


def latest_tag() -> str | None:
    """Return the latest release tag (e.g. 'v0.16.5'), or None on failure."""
    data = cached_check()
    if isinstance(data, dict):
        return data.get("tag_name")
    return None
