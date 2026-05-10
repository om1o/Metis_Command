"""
Gmail API client — the right way to read mail.

Browser automation against Gmail loses to Google's bot detection
every time. The Gmail API doesn't care: one OAuth handshake, refresh
tokens forever, structured email objects.

Setup (one-time, ~3 min):

    1. Open https://console.cloud.google.com/apis/credentials
    2. Create a new project (or reuse one)
    3. Enable the Gmail API for that project
    4. Create OAuth client ID → Application type: Desktop app
    5. Download the JSON, save it as identity/gmail_credentials.json
    6. Add yourself as a "test user" on the OAuth consent screen

Then call ``oauth_login()`` once. A browser window opens for the
Google consent screen — the consent screen accepts every browser,
no automation involved on our side.

After consent, identity/gmail_token.json holds the refresh token.
Every later call (``list_recent``, ``summarize_recent``) refreshes
silently, no user prompt.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Any

CREDENTIALS_FILE = Path("identity") / "gmail_credentials.json"
TOKEN_FILE = Path("identity") / "gmail_token.json"

# The minimum scope to read mail. Modify to add send/draft etc.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

try:
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    _GOOGLE_OK = True
except Exception:
    _GOOGLE_OK = False


# ── Auth ─────────────────────────────────────────────────────────────────────

def _load_credentials() -> Any | None:
    """Load saved OAuth credentials and refresh if needed."""
    if not _GOOGLE_OK or not TOKEN_FILE.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            return None
    return creds if creds and creds.valid else None


def is_logged_in() -> bool:
    """Cheap check used by the manager before delegating."""
    return _load_credentials() is not None


def oauth_login() -> dict[str, Any]:
    """Run the OAuth consent flow. Opens a browser to Google's own
    consent screen — that page accepts every browser, no automation
    on our side. After the user clicks "Allow", we save the token."""
    if not _GOOGLE_OK:
        return {
            "ok": False,
            "error": "google-api libs not installed",
            "hint": "pip install google-auth google-auth-oauthlib google-api-python-client",
        }
    if not CREDENTIALS_FILE.exists():
        return {
            "ok": False,
            "error": "credentials missing",
            "hint": (
                f"Save your OAuth client JSON to {CREDENTIALS_FILE}. "
                "Get it from https://console.cloud.google.com/apis/credentials "
                "→ Create OAuth client ID → Desktop app."
            ),
        }
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return {"ok": True, "saved_to": str(TOKEN_FILE)}


def logout() -> dict[str, Any]:
    """Wipe the saved token."""
    try:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Reading ─────────────────────────────────────────────────────────────────

@dataclass
class EmailHeader:
    id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    snippet: str
    date_iso: str
    unread: bool
    has_attachment: bool
    labels: list[str]


def _service():
    creds = _load_credentials()
    if not creds:
        raise RuntimeError(
            "not signed in — run gmail_api.oauth_login() once first"
        )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def list_recent(hours: int = 24, max_results: int = 25) -> list[EmailHeader]:
    """Return the user's last ``hours`` of inbox messages, newest first."""
    svc = _service()
    after_ts = int(time.time()) - hours * 3600
    # Gmail's search-query language. "newer_than" takes day units, but
    # epoch-anchored "after:" is exact.
    q = f"in:inbox after:{after_ts}"
    listing = (
        svc.users().messages()
        .list(userId="me", q=q, maxResults=max_results)
        .execute()
    )
    out: list[EmailHeader] = []
    for m in listing.get("messages", []):
        full = (
            svc.users().messages()
            .get(userId="me", id=m["id"], format="metadata",
                 metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = full.get("payload", {}).get("headers", [])
        sender_full = _header(headers, "From")
        sender_name, sender_email = parseaddr(sender_full)
        labels = full.get("labelIds", [])
        out.append(EmailHeader(
            id=full["id"],
            thread_id=full.get("threadId", ""),
            sender=sender_name or sender_email,
            sender_email=sender_email,
            subject=_header(headers, "Subject"),
            snippet=full.get("snippet", ""),
            date_iso=_header(headers, "Date"),
            unread="UNREAD" in labels,
            has_attachment="HAS_ATTACHMENT" in labels,
            labels=[l for l in labels if l not in ("INBOX", "UNREAD", "HAS_ATTACHMENT")],
        ))
    return out


def get_body(message_id: str, *, max_chars: int = 4000) -> str:
    """Fetch the plain-text body of a single message."""
    svc = _service()
    full = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = full.get("payload", {})
    return _extract_text(payload)[:max_chars]


def _extract_text(payload: dict) -> str:
    """Walk Gmail's mime tree and pull text/plain bodies."""
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")
    if data and mime.startswith("text/plain"):
        try:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        except Exception:
            return ""
    parts = payload.get("parts") or []
    chunks: list[str] = []
    for p in parts:
        chunks.append(_extract_text(p))
    return "\n".join(c for c in chunks if c)


# ── LLM-friendly summary helpers ────────────────────────────────────────────

def briefing_payload(hours: int = 24, max_results: int = 25) -> dict[str, Any]:
    """Compact JSON the manager LLM can chew on to produce a 5-bullet
    priority briefing. Each entry has just enough metadata to
    triage; bodies are not included to keep the payload small."""
    items = list_recent(hours=hours, max_results=max_results)
    return {
        "window_hours": hours,
        "count": len(items),
        "messages": [
            {
                "id": e.id,
                "from": f"{e.sender} <{e.sender_email}>".strip(),
                "subject": e.subject,
                "snippet": e.snippet[:200],
                "date": e.date_iso,
                "unread": e.unread,
                "has_attachment": e.has_attachment,
                "labels": e.labels,
            }
            for e in items
        ],
    }


def to_dicts(items: list[EmailHeader]) -> list[dict[str, Any]]:
    return [
        {
            "id": e.id,
            "from": f"{e.sender} <{e.sender_email}>".strip(),
            "subject": e.subject,
            "snippet": e.snippet,
            "date": e.date_iso,
            "unread": e.unread,
        }
        for e in items
    ]
