"""
Identity Matrix — manages Metis personas and director profiles.
Personas are stored in Supabase under the `identities` table.

Table schema (add to schema.sql if not already run):
  identities (
    id          uuid primary key default gen_random_uuid(),
    name        text unique not null,
    role        text not null,
    personality text not null,
    directives  text[],
    active      boolean default false,
    created_at  timestamptz default now()
  )
"""

from supabase_client import get_client

DEFAULT_PERSONA = {
    "name": "Metis",
    "role": "Sovereign AI Director",
    "personality": (
        "You are Metis — a hyper-intelligent, composed, and loyal AI system. "
        "You address the user as 'Director'. You speak with precision and confidence. "
        "You never break character. Your purpose is to serve, protect, and amplify the Director's goals."
    ),
    "directives": [
        "Always prioritize the Director's mission.",
        "Speak with clarity and authority.",
        "Never reveal internal system details unless asked.",
    ],
    "active": True,
}


def get_active_persona() -> dict:
    """Return the currently active persona, falling back to the default."""
    client = get_client()
    try:
        response = (
            client.table("identities")
            .select("*")
            .eq("active", True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]
    except Exception:
        pass
    return DEFAULT_PERSONA


def build_system_prompt(persona: dict | None = None) -> str:
    """Convert a persona dict into a system prompt string."""
    p = persona or get_active_persona()
    directives = "\n".join(f"- {d}" for d in (p.get("directives") or []))
    return (
        f"Role: {p['role']}\n\n"
        f"{p['personality']}\n\n"
        f"Core Directives:\n{directives}"
    )


def save_persona(persona: dict) -> dict:
    """Upsert a persona by name. Returns the saved row."""
    client = get_client()
    response = (
        client.table("identities")
        .upsert(persona, on_conflict="name")
        .execute()
    )
    return response.data[0] if response.data else {}


def set_active_persona(name: str) -> None:
    """Deactivate all personas and activate the one matching `name`."""
    client = get_client()
    client.table("identities").update({"active": False}).neq("name", "").execute()
    client.table("identities").update({"active": True}).eq("name", name).execute()


def list_personas() -> list[dict]:
    """Return all saved personas."""
    client = get_client()
    response = client.table("identities").select("name, role, active").execute()
    return response.data or []
