"""
Auto-update checker.

Compares the locally-installed Metis version against the latest GitHub
release.  Stdlib-only so it can run before the venv exists (used by
launch.py) and cached to disk so we don't hammer GitHub's API.

Public API:
    check() -> dict
        {"current": "0.16.4", "latest": "0.17.0", "url": "...",
         "update_available": True, "checked_at": <unix_ts>}

    cached_check(max_age_s=3600) -> dict
        returns the last check() result if it's recent, else a fresh one.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


_REPO = "om1o/Metis_Command"
_RELEASES_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_CACHE_DIR = Path(__file__).resolve().parent.parent / "logs"
_CACHE_FILE = _CACHE_DIR / "update_check.json"


# Conservative version parser - returns a tuple for comparison.
_VER_RX = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _parse(ver: str) -> tuple[int, int, int]:
    m = _VER_RX.search(ver or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _current_version() -> str:
    # Prefer reading from the API bridge module so there's one source of truth.
    try:
        import api_bridge
        return str(getattr(api_bridge, "METIS_VERSION", "0.0.0"))
    except Exception:
        pass
    # Fallback: look for a VERSION file in dist/.
    root = Path(__file__).resolve().parent.parent
    vfile = root / "dist" / "VERSION.txt"
    if vfile.exists():
        try:
            return vfile.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "0.0.0"


def check(timeout: float = 5.0) -> dict[str, Any]:
    """Hit GitHub's releases API and return an update status dict.

    Never raises: network errors degrade to {"update_available": False,
    "error": "..."}.
    """
    current = _current_version()
    out: dict[str, Any] = {
        "current": current,
        "latest": current,
        "url": None,
        "update_available": False,
        "checked_at": int(time.time()),
    }
    try:
        req = urllib.request.Request(
            _RELEASES_API,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "metis-command-updater"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        out["error"] = f"HTTP {e.code}"
        return _save(out)
    except (urllib.error.URLError, OSError, ValueError) as e:
        out["error"] = str(e)[:160]
        return _save(out)

    tag = str(data.get("tag_name") or data.get("name") or "")
    out["latest"] = tag.lstrip("v") or current
    out["url"] = data.get("html_url") or None
    out["update_available"] = _parse(out["latest"]) > _parse(current)
    return _save(out)


def cached_check(max_age_s: float = 3600.0) -> dict[str, Any]:
    """Return the last check() result if it's recent, else do a fresh one."""
    if _CACHE_FILE.exists():
        try:
            row = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            age = time.time() - float(row.get("checked_at", 0))
            if age < max_age_s:
                return row
        except Exception:
            pass
    return check()


def _save(result: dict[str, Any]) -> dict[str, Any]:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result


if __name__ == "__main__":
    import sys
    print(json.dumps(check(), indent=2))
    sys.exit(0)
