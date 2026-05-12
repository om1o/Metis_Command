"""
Discord Automator — post, edit, and schedule Discord messages.

Uses Discord's incoming webhook API. Set DISCORD_WEBHOOK_URL in .env
OR pass one explicitly to send().
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


def send(content: str, *, webhook_url: str | None = None, username: str | None = None) -> dict[str, Any]:
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        return {"ok": False, "error": "missing webhook url"}
    payload = {"content": content[:1900]}
    if username:
        payload["username"] = username
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return {"ok": True, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def broadcast(messages: list[str], *, webhook_url: str | None = None) -> list[dict[str, Any]]:
    return [send(m, webhook_url=webhook_url) for m in messages]


if __name__ == "__main__":
    print(json.dumps(send("Metis Discord test."), indent=2))
