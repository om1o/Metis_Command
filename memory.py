"""
Memory module — persists Metis conversation history to Supabase.

Expected table schema (run schema.sql against your Supabase project):
  memory (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid references auth.users(id) on delete cascade,
    session_id  text not null,
    role        text not null,   -- 'user' | 'assistant' | 'system'
    content     text not null,
    created_at  timestamptz default now()
  )
"""

from supabase_client import get_client


def save_message(session_id: str, role: str, content: str, user_id: str | None = None) -> dict:
    """Append a message to the memory table and return the inserted row."""
    client = get_client()
    payload = {
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    if user_id:
        payload["user_id"] = user_id

    response = (
        client.table("memory")
        .insert(payload)
        .execute()
    )
    return response.data[0] if response.data else {}


def load_session(session_id: str, limit: int = 50) -> list[dict]:
    """Retrieve the last `limit` messages for a session, oldest-first."""
    client = get_client()
    response = (
        client.table("memory")
        .select("role, content, created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return response.data or []


def clear_session(session_id: str) -> None:
    """Delete all memory rows for a given session."""
    client = get_client()
    client.table("memory").delete().eq("session_id", session_id).execute()


def list_sessions(user_id: str) -> list[str]:
    """Return distinct session IDs belonging to a user."""
    client = get_client()
    response = (
        client.table("memory")
        .select("session_id")
        .eq("user_id", user_id)
        .execute()
    )
    seen: set[str] = set()
    sessions = []
    for row in response.data or []:
        sid = row["session_id"]
        if sid not in seen:
            seen.add(sid)
            sessions.append(sid)
    return sessions
