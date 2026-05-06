"""
Cloud Sync — uploads local Metis artifacts (skills, configs, profiles)
to Supabase Storage and keeps a manifest in the `sync_log` table.

Storage bucket:  metis-artifacts  (create in Supabase dashboard)
Table schema:    see schema.sql
"""

import os
import mimetypes
from pathlib import Path
from supabase_client import get_client

BUCKET = "metis-artifacts"


# ── File upload / download ────────────────────────────────────────────────────

def upload_file(local_path: str, remote_path: str | None = None) -> str:
    """
    Upload a local file to Supabase Storage.
    Returns the public URL of the uploaded file.
    """
    client = get_client()
    local = Path(local_path)
    destination = remote_path or local.name
    mime, _ = mimetypes.guess_type(str(local))
    mime = mime or "application/octet-stream"

    with open(local, "rb") as f:
        client.storage.from_(BUCKET).upload(
            path=destination,
            file=f,
            file_options={"content-type": mime, "upsert": "true"},
        )

    public_url = client.storage.from_(BUCKET).get_public_url(destination)
    _log_sync(local_path=str(local), remote_path=destination, action="upload", url=public_url)
    return public_url


def download_file(remote_path: str, local_path: str) -> None:
    """Download a file from Supabase Storage to a local path."""
    client = get_client()
    data = client.storage.from_(BUCKET).download(remote_path)
    Path(local_path).write_bytes(data)
    _log_sync(local_path=local_path, remote_path=remote_path, action="download")


def list_remote_files(prefix: str = "") -> list[dict]:
    """List files in the storage bucket, optionally filtered by prefix folder."""
    client = get_client()
    response = client.storage.from_(BUCKET).list(path=prefix)
    return response or []


# ── Sync log ──────────────────────────────────────────────────────────────────

def _log_sync(local_path: str, remote_path: str, action: str, url: str = "") -> None:
    """Record a sync event in the sync_log table."""
    client = get_client()
    client.table("sync_log").insert({
        "local_path": local_path,
        "remote_path": remote_path,
        "action": action,
        "url": url,
    }).execute()


def get_sync_log(limit: int = 20) -> list[dict]:
    """Return the most recent sync events."""
    client = get_client()
    response = (
        client.table("sync_log")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []
