"""
Cognitive Memory Loop — the 4 Pillars wired together.

inject_context()          -> Pillar 1, the Vector Subconscious (pre-prompt recall)
persist_turn()            -> writes to Supabase + ChromaDB every turn
nightly_synthesizer()     -> Pillar 2, the Background Synthesizer
daily_update_user_matrix  -> Pillar 4, the Identity Matrix file refresh

Reasoning traces are persisted but never surfaced by default — the UI's
"Show thinking" dropdown reads them on demand.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Iterable

from brain_engine import chat_by_role
from memory import load_session, save_message
from memory_vault import MemoryBank


USER_MATRIX_PATH = Path("identity") / "user_matrix.json"
REASONING_DIR = Path("logs") / "reasoning"
IDENTITY_NAMESPACE = "identity"

_bank = MemoryBank()


# ── Pillar 1: pre-prompt context injection ───────────────────────────────────

def inject_context(
    session_id: str,
    user_prompt: str,
    k_recall: int = 5,
    k_history: int = 6,
    brain: str | None = None,
) -> list[dict]:
    """
    Return a list of message dicts ready to prepend to the user's prompt.
    Includes: top-K long-term facts + last N Supabase turns for this session.

    When `brain` is provided (or an active Brain exists), recall is done from
    that Brain's dedicated collection; otherwise we fall back to the shared
    MemoryBank for backward compatibility.
    """
    injected: list[dict] = []

    # Durable facts pulled by semantic similarity.
    try:
        hits: list[dict] = []
        try:
            import brains as _brains
            b = _brains.get(brain) if brain else _brains.active()
            if b is not None:
                hits = _brains.recall(user_prompt, k=k_recall, brain=b)
        except Exception:
            hits = []
        if not hits:
            hits = _bank.search(user_prompt, n_results=k_recall) or []
        if hits:
            bullet_list = "\n".join(f"- {h.get('document','').strip()}" for h in hits if h)
            injected.append({
                "role": "system",
                "content": (
                    "Relevant long-term memory about the Director:\n"
                    f"{bullet_list}\n\n"
                    "Use these facts only if they help; never invent memory."
                ),
            })
    except Exception as e:
        try:
            from safety import log as _safety_log
            _safety_log("memory_recall_failed", error=str(e))
        except Exception:
            pass

    # Recent turns from this session.
    try:
        recent = load_session(session_id, limit=k_history)
        for row in recent:
            role = row.get("role", "user")
            injected.append({"role": role, "content": row.get("content", "")})
    except Exception as e:
        try:
            from safety import log as _safety_log
            _safety_log("memory_session_load_failed", error=str(e))
        except Exception:
            pass

    return injected


# ── Persistence: every turn ──────────────────────────────────────────────────

def persist_turn(
    session_id: str,
    user_msg: str,
    assistant_msg: str,
    reasoning: str | None = None,
    user_id: str | None = None,
) -> None:
    """Write both sides of the exchange to Supabase and upsert a vector."""
    try:
        save_message(session_id, "user", user_msg, user_id=user_id)
        save_message(session_id, "assistant", assistant_msg, user_id=user_id)
    except Exception as e:
        try:
            from safety import log as _safety_log
            _safety_log("memory_supabase_persist_failed", error=str(e))
        except Exception:
            pass

    try:
        turn_id = f"{session_id}:{_short_hash(user_msg)}"
        _bank.store_interaction(
            entity_name=turn_id,
            facts=(
                f"User said: {user_msg}\n"
                f"Assistant replied: {assistant_msg[:600]}"
            ),
        )
    except Exception as e:
        try:
            from safety import log as _safety_log
            _safety_log("memory_vault_upsert_failed", error=str(e))
        except Exception:
            pass

    # Mirror to the active brain's episodic tier so per-brain recall stays current.
    try:
        import brains as _brains
        if _brains.active() is not None:
            _brains.remember(
                f"User said: {user_msg}\nAssistant replied: {assistant_msg[:600]}",
                kind="episodic",
                entity=f"{session_id}:{_short_hash(user_msg)}",
            )
    except Exception as e:
        try:
            from safety import log as _safety_log
            _safety_log("memory_brain_mirror_failed", error=str(e))
        except Exception:
            pass

    if reasoning:
        try:
            REASONING_DIR.mkdir(parents=True, exist_ok=True)
            fp = REASONING_DIR / f"{session_id}.jsonl"
            with fp.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "session_id": session_id,
                    "user_msg": user_msg,
                    "reasoning": reasoning,
                }) + "\n")
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memory_reasoning_write_failed", error=str(e))
            except Exception:
                pass


def load_reasoning(session_id: str) -> list[dict]:
    fp = REASONING_DIR / f"{session_id}.jsonl"
    if not fp.exists():
        return []
    out: list[dict] = []
    with fp.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ── Pillar 2: background synthesizer (runs nightly) ──────────────────────────

def nightly_synthesizer(session_ids: Iterable[str] | None = None) -> list[str]:
    """
    Ask the Thinker to extract durable facts from each session's messages
    and store them under the `identity` ChromaDB namespace.
    Returns the list of facts written.
    """
    facts_written: list[str] = []
    targets = list(session_ids) if session_ids else []
    if not targets:
        return facts_written

    for sid in targets:
        try:
            messages = load_session(sid, limit=200)
            if not messages:
                continue
            transcript = "\n".join(
                f"{m.get('role','?')}: {m.get('content','')}" for m in messages
            )
            prompt = (
                "Extract up to 5 durable personal facts about the Director "
                "from the transcript below. A durable fact is stable over time "
                "(preferences, goals, recurring topics). One fact per line. "
                "No speculation.\n\n"
                f"TRANSCRIPT:\n{transcript[:6000]}"
            )
            reply = chat_by_role("thinker", [{"role": "user", "content": prompt}])
            for line in (reply or "").splitlines():
                line = line.strip("- •\t ").strip()
                if len(line) < 6:
                    continue
                entity = f"{IDENTITY_NAMESPACE}:{_short_hash(line)}"
                try:
                    _bank.store_interaction(entity_name=entity, facts=line)
                    facts_written.append(line)
                except Exception:
                    continue
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memory_synthesizer_session_failed", session=sid, error=str(e))
            except Exception:
                pass
    return facts_written


# ── Pillar 4: daily user_matrix.json refresh ────────────────────────────────

def daily_update_user_matrix(new_facts: Iterable[str] | None = None) -> dict:
    """Merge today's observations into identity/user_matrix.json."""
    USER_MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    matrix: dict = {}
    if USER_MATRIX_PATH.exists():
        try:
            matrix = json.loads(USER_MATRIX_PATH.read_text(encoding="utf-8"))
        except Exception:
            matrix = {}

    matrix.setdefault("history", {})
    matrix.setdefault("traits", [])
    today = date.today().isoformat()
    entry = matrix["history"].setdefault(today, {"facts": []})
    for fact in (new_facts or []):
        if fact and fact not in entry["facts"]:
            entry["facts"].append(fact)
        if fact and fact not in matrix["traits"]:
            matrix["traits"].append(fact)

    USER_MATRIX_PATH.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    return matrix


# ── helpers ──────────────────────────────────────────────────────────────────

def _short_hash(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]
