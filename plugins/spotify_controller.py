"""
Spotify Controller — play, pause, queue, and search via Spotify Web API.

Requires SPOTIFY_ACCESS_TOKEN in .env (short-lived OAuth bearer).
For real deployments, wire a proper OAuth refresh flow; this stub lets
the Coder expand it into a full plugin later.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

API = "https://api.spotify.com/v1"


def _headers() -> dict[str, str]:
    token = os.getenv("SPOTIFY_ACCESS_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def play(device_id: str | None = None) -> dict[str, Any]:
    try:
        params = {"device_id": device_id} if device_id else None
        r = requests.put(f"{API}/me/player/play", headers=_headers(), params=params, timeout=10)
        return {"ok": r.status_code in (200, 202, 204), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pause() -> dict[str, Any]:
    try:
        r = requests.put(f"{API}/me/player/pause", headers=_headers(), timeout=10)
        return {"ok": r.status_code in (200, 202, 204), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def queue(track_uri: str) -> dict[str, Any]:
    try:
        r = requests.post(
            f"{API}/me/player/queue",
            headers=_headers(),
            params={"uri": track_uri},
            timeout=10,
        )
        return {"ok": r.status_code in (200, 202, 204), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search(query: str, *, kind: str = "track", limit: int = 10) -> list[dict[str, Any]]:
    try:
        r = requests.get(
            f"{API}/search",
            headers=_headers(),
            params={"q": query, "type": kind, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        items = (r.json().get(f"{kind}s") or {}).get("items") or []
        return [
            {
                "name":    it.get("name"),
                "artists": [a.get("name") for a in it.get("artists", [])],
                "uri":     it.get("uri"),
                "url":     (it.get("external_urls") or {}).get("spotify"),
            }
            for it in items
        ]
    except Exception as e:
        return [{"error": str(e)}]


if __name__ == "__main__":
    print(json.dumps(search("miles davis"), indent=2)[:800])
