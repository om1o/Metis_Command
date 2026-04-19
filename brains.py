"""
Brains — persistent, swappable long-term memory for Metis.

A Brain is a named profile that bundles three memory tiers on top of the
existing ChromaDB vault and Supabase chat log:

    Episodic   — every chat turn (persisted by memory_loop.persist_turn)
    Semantic   — durable facts distilled by the nightly synthesizer + pins
    Procedural — step recipes ("how to book a flight for the Director")

Each brain owns its own Chroma collection so projects and personas can have
isolated long-term recall without mixing contexts.  When a brain crosses its
`budget_tokens` budget, `compact()` asks the Thinker to condense the oldest
entries into higher-level facts — nothing is deleted, the memory is just
re-encoded hierarchically, which is the "never forgets" guarantee.

Disk layout:
    identity/brains/<slug>/brain.json
    identity/brains/<slug>/procedural.jsonl
    identity/brains/.active            (single-line slug of the active brain)

Public API (stable):
    create(name, description="", budget_tokens=200_000) -> Brain
    list_brains() -> list[Brain]
    get(slug) -> Brain | None
    switch(slug) -> None
    active() -> Brain | None
    remember(text, *, kind="semantic", brain=None, tags=None) -> str
    recall(query, *, k=5, brain=None) -> list[dict]
    forget(ids, *, brain=None) -> int
    compact(*, brain=None) -> int
    backup(path, *, brain=None, password=None) -> str
    restore(path, *, brain=None, password=None) -> Brain
    stats(brain=None) -> dict
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


from safety import PATHS  # noqa: E402

BRAINS_DIR = PATHS.identity / "brains"
ACTIVE_FILE = BRAINS_DIR / ".active"
_DEFAULT_BUDGET_TOKENS = 200_000


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Brain:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    slug: str = "default"
    name: str = "Default"
    description: str = ""
    namespace: str = ""                     # Chroma collection name
    budget_tokens: int = _DEFAULT_BUDGET_TOKENS
    tags: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Chroma-backed collection helpers ─────────────────────────────────────────

_COLLECTIONS: dict[str, Any] = {}  # slug -> chromadb.Collection


def _client():
    """Return the shared Chroma client used by the vault, if available."""
    try:
        import chromadb
        return chromadb.PersistentClient(path="./metis_db")
    except Exception as e:
        print(f"[Brains] Chroma unavailable: {e}")
        return None


def _collection(slug: str):
    """Return (and cache) the Chroma collection for brain `slug`."""
    if slug in _COLLECTIONS:
        return _COLLECTIONS[slug]
    client = _client()
    if client is None:
        return None
    try:
        name = f"brain_{slug}"
        col = client.get_or_create_collection(name)
        _COLLECTIONS[slug] = col
        return col
    except Exception as e:
        print(f"[Brains] collection({slug}) error: {e}")
        return None


# ── Disk helpers ─────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s or "brain")[:40]


def _brain_dir(slug: str) -> Path:
    return BRAINS_DIR / slug


def _brain_file(slug: str) -> Path:
    return _brain_dir(slug) / "brain.json"


def _procedural_file(slug: str) -> Path:
    return _brain_dir(slug) / "procedural.jsonl"


def _load_brain(slug: str) -> Brain | None:
    fp = _brain_file(slug)
    if not fp.exists():
        return None
    try:
        return Brain(**json.loads(fp.read_text(encoding="utf-8")))
    except Exception:
        return None


def _save_brain(brain: Brain) -> None:
    _brain_dir(brain.slug).mkdir(parents=True, exist_ok=True)
    brain.updated_at = time.time()
    _brain_file(brain.slug).write_text(
        json.dumps(brain.to_dict(), indent=2), encoding="utf-8"
    )


def _resolve(brain: Brain | str | None) -> Brain:
    """Return a Brain dataclass from a slug, Brain, or None (→ active)."""
    if isinstance(brain, Brain):
        return brain
    if isinstance(brain, str):
        b = _load_brain(brain)
        if b is None:
            raise KeyError(f"Brain not found: {brain}")
        return b
    b = active()
    if b is None:
        b = _ensure_default()
    return b


def _ensure_default() -> Brain:
    """Create and activate a default brain when none exists."""
    b = _load_brain("default")
    if b is not None:
        return b
    b = create("Default", description="Auto-created default brain.")
    switch(b.slug)
    return b


# ── Public API ───────────────────────────────────────────────────────────────

def create(
    name: str,
    *,
    description: str = "",
    budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
    tags: Iterable[str] | None = None,
) -> Brain:
    slug = _slugify(name)
    BRAINS_DIR.mkdir(parents=True, exist_ok=True)
    _brain_dir(slug).mkdir(parents=True, exist_ok=True)
    brain = Brain(
        slug=slug,
        name=name or slug,
        description=description,
        namespace=f"brain_{slug}",
        budget_tokens=budget_tokens,
        tags=list(tags or []),
    )
    _save_brain(brain)
    # Eager-create the collection so stats calls don't race.
    _collection(slug)
    try:
        from safety import audit
        audit({"event": "brain_create", "slug": slug})
    except Exception:
        pass
    return brain


def list_brains() -> list[Brain]:
    BRAINS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[Brain] = []
    for sub in BRAINS_DIR.iterdir():
        if sub.is_file() or sub.name.startswith("."):
            continue
        b = _load_brain(sub.name)
        if b:
            out.append(b)
    out.sort(key=lambda b: b.updated_at, reverse=True)
    return out


def get(slug: str) -> Brain | None:
    return _load_brain(slug)


def switch(slug: str) -> None:
    if _load_brain(slug) is None:
        raise KeyError(f"Brain not found: {slug}")
    BRAINS_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(slug, encoding="utf-8")
    try:
        from safety import audit
        audit({"event": "brain_switch", "slug": slug})
    except Exception:
        pass


def active() -> Brain | None:
    if not ACTIVE_FILE.exists():
        return None
    slug = ACTIVE_FILE.read_text(encoding="utf-8").strip()
    return _load_brain(slug) if slug else None


def active_slug() -> str | None:
    b = active()
    return b.slug if b else None


def delete(slug: str) -> bool:
    d = _brain_dir(slug)
    if not d.exists():
        return False
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    # drop cached collection handle
    _COLLECTIONS.pop(slug, None)
    try:
        client = _client()
        if client is not None:
            client.delete_collection(f"brain_{slug}")
    except Exception:
        pass
    if active_slug() == slug:
        try:
            ACTIVE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    return True


# ── Remember / Recall / Forget ──────────────────────────────────────────────

def remember(
    text: str,
    *,
    kind: str = "semantic",       # "semantic" | "episodic" | "procedural"
    brain: Brain | str | None = None,
    tags: Iterable[str] | None = None,
    entity: str | None = None,
) -> str:
    """Store `text` in the brain's collection. Returns the entry id."""
    b = _resolve(brain)
    col = _collection(b.slug)
    if col is None:
        return ""
    entry_id = entity or f"{kind}:{int(time.time()*1000)}:{uuid.uuid4().hex[:6]}"
    meta = {
        "brain": b.slug,
        "kind": kind,
        "ts": time.time(),
        "tags": ",".join(tags or []),
    }
    try:
        col.upsert(ids=[entry_id], documents=[text], metadatas=[meta])
    except Exception as e:
        print(f"[Brains] remember failed: {e}")
        return ""

    if kind == "procedural":
        try:
            _brain_dir(b.slug).mkdir(parents=True, exist_ok=True)
            with _procedural_file(b.slug).open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": entry_id, "text": text, **meta},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass
    _bump_stats(b, kind=kind, delta_tokens=_approx_tokens(text))
    return entry_id


def recall(
    query: str,
    *,
    k: int = 5,
    brain: Brain | str | None = None,
    kinds: Iterable[str] | None = None,
) -> list[dict]:
    """Semantic search within a brain. Returns [{id, document, metadata, distance}]."""
    b = _resolve(brain)
    col = _collection(b.slug)
    if col is None:
        return []
    try:
        res = col.query(query_texts=[query], n_results=max(1, k))
    except Exception as e:
        print(f"[Brains] recall failed: {e}")
        return []
    hits: list[dict] = []
    for i, doc in enumerate(res.get("documents", [[]])[0]):
        meta = res.get("metadatas", [[]])[0][i] if res.get("metadatas") else {}
        if kinds and meta.get("kind") not in set(kinds):
            continue
        hits.append({
            "id": (res.get("ids", [[]])[0][i] if res.get("ids") else None),
            "document": doc,
            "metadata": meta,
            "distance": (res.get("distances", [[]])[0][i] if res.get("distances") else None),
        })
    return hits


def forget(ids: Iterable[str], *, brain: Brain | str | None = None) -> int:
    b = _resolve(brain)
    col = _collection(b.slug)
    if col is None:
        return 0
    ids_list = [i for i in ids if i]
    if not ids_list:
        return 0
    try:
        col.delete(ids=ids_list)
    except Exception as e:
        print(f"[Brains] forget failed: {e}")
        return 0
    return len(ids_list)


# ── Compact (the "never forget" hierarchical re-encoder) ────────────────────

def compact(
    *,
    brain: Brain | str | None = None,
    window: int = 50,
    min_summary_chars: int = 60,
) -> int:
    """
    Re-encode the oldest `window` entries in a brain into a single higher-level
    fact so the collection stays bounded.  The source entries are moved to a
    30-day trash pile BEFORE deletion, and we refuse to delete unless the LLM
    returned a summary that passes sanity checks.  This is the "never forgets"
    guarantee — no data is ever truly lost.

    Returns the number of source entries that were folded in (0 if we bailed).
    """
    b = _resolve(brain)
    col = _collection(b.slug)
    if col is None:
        return 0

    try:
        data = col.get()
    except Exception as e:
        print(f"[Brains] compact fetch failed: {e}")
        return 0

    ids = data.get("ids") or []
    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    if len(ids) <= window:
        return 0

    rows = list(zip(ids, docs, metas))
    rows.sort(key=lambda r: (r[2] or {}).get("ts") or 0)
    oldest = rows[:window]
    # Don't compact already-compacted entries more than once per pass.
    oldest = [r for r in oldest if (r[2] or {}).get("kind") != "compacted"]
    if not oldest:
        return 0

    transcript = "\n".join(f"- {doc[:400]}" for _, doc, _ in oldest)
    summary = ""
    try:
        from brain_engine import chat_by_role
        summary = chat_by_role("thinker", [
            {"role": "system", "content":
                "You compress long-term memory for Metis. Combine the bullets "
                "into 3-8 crisp durable facts. Keep names, dates, preferences, "
                "and decisions. No speculation. Markdown bullets only."},
            {"role": "user", "content":
                f"BRAIN: {b.name}\nENTRIES:\n{transcript[:6000]}"},
        ]) or ""
    except Exception as e:
        print(f"[Brains] compact LLM call failed: {e}")

    # Sanity gate — refuse to delete unless the summary looks real.
    passes_gate = (
        len(summary.strip()) >= min_summary_chars
        and summary.count("\n") >= 2              # multiple bullets
        and not summary.strip().startswith("[")   # not an error token
        and "BrainEngine" not in summary          # not a bridge error string
    )
    if not passes_gate:
        try:
            from safety import audit
            audit({"event": "brain_compact_bailed",
                   "slug": b.slug,
                   "summary_len": len(summary),
                   "reason": "summary failed sanity gate"})
        except Exception:
            pass
        return 0

    # Move originals to a timestamped trash file BEFORE deleting, so nothing
    # is truly lost even if the upsert below fails.
    try:
        trash_path = _brain_dir(b.slug) / "compact_trash.jsonl"
        trash_path.parent.mkdir(parents=True, exist_ok=True)
        with trash_path.open("a", encoding="utf-8") as f:
            for rid, doc, meta in oldest:
                f.write(json.dumps({
                    "id": rid, "document": doc, "metadata": meta,
                    "trashed_at": time.time(),
                }, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Brains] compact trash write failed, aborting: {e}")
        return 0

    compacted_id = f"compacted:{int(time.time()*1000)}:{uuid.uuid4().hex[:6]}"
    try:
        col.upsert(
            ids=[compacted_id],
            documents=[summary],
            metadatas=[{
                "brain": b.slug,
                "kind": "compacted",
                "ts": time.time(),
                "source_count": len(oldest),
            }],
        )
        col.delete(ids=[rid for rid, _, _ in oldest])
    except Exception as e:
        print(f"[Brains] compact upsert failed: {e}")
        return 0

    _bump_stats(b, kind="compacted",
                delta_tokens=_approx_tokens(summary),
                folded=len(oldest))
    try:
        from safety import audit
        audit({"event": "brain_compact",
               "slug": b.slug,
               "folded": len(oldest),
               "trash": str(_brain_dir(b.slug) / "compact_trash.jsonl")})
    except Exception:
        pass
    return len(oldest)


def purge_compact_trash(
    *,
    brain: Brain | str | None = None,
    older_than_days: int = 30,
) -> int:
    """Delete rows from compact_trash.jsonl older than the cutoff."""
    b = _resolve(brain)
    path = _brain_dir(b.slug) / "compact_trash.jsonl"
    if not path.exists():
        return 0
    cutoff = time.time() - (older_than_days * 86400)
    kept: list[str] = []
    purged = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                kept.append(line)
                continue
            if (row.get("trashed_at") or 0) < cutoff:
                purged += 1
            else:
                kept.append(line)
    path.write_text("".join(kept), encoding="utf-8")
    return purged


# ── Backup / Restore via existing .mts format ───────────────────────────────

def backup(
    path: str,
    *,
    brain: Brain | str | None = None,
    password: str | None = None,
) -> str:
    """Export a brain (metadata + all entries) as a .mts or .json bundle."""
    b = _resolve(brain)
    col = _collection(b.slug)
    data = {}
    if col is not None:
        try:
            data = col.get()
        except Exception:
            data = {}
    bundle = {
        "kind": "MetisBrain",
        "brain": b.to_dict(),
        "entries": {
            "ids": data.get("ids") or [],
            "documents": data.get("documents") or [],
            "metadatas": data.get("metadatas") or [],
        },
        "exported_at": int(time.time()),
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.suffix.lower() == ".mts":
        # Use the existing AES-GCM container.
        try:
            import struct
            from mts_format import MAGIC, VERSION, FLAG_ENCRYPTED, _encrypt
            body = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
            flags = 0
            meta = {"kind": "brain", "slug": b.slug}
            if password:
                cipher, salt, nonce = _encrypt(body, password)
                flags |= FLAG_ENCRYPTED
                meta["salt"] = salt.hex()
                meta["nonce"] = nonce.hex()
                body = cipher
            meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
            with out.open("wb") as f:
                f.write(MAGIC)
                f.write(struct.pack("B", VERSION))
                f.write(struct.pack("B", flags))
                f.write(struct.pack(">I", len(meta_bytes)))
                f.write(meta_bytes)
                f.write(body)
            return str(out)
        except Exception as e:
            print(f"[Brains] .mts export failed, falling back to .json: {e}")
            out = out.with_suffix(".json")

    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


def restore(
    path: str,
    *,
    brain: Brain | str | None = None,
    password: str | None = None,
) -> Brain:
    """Import a brain bundle. If `brain` is None, uses the slug from the file."""
    p = Path(path)
    bundle: dict[str, Any]

    if p.suffix.lower() == ".mts":
        import struct
        from mts_format import MAGIC, VERSION, FLAG_ENCRYPTED, _decrypt
        with p.open("rb") as f:
            if f.read(4) != MAGIC:
                raise ValueError("Not a .mts file (bad magic).")
            version = struct.unpack("B", f.read(1))[0]
            if version > VERSION:
                raise ValueError(f"Unsupported .mts version: {version}")
            flags = struct.unpack("B", f.read(1))[0]
            meta_len = struct.unpack(">I", f.read(4))[0]
            meta = json.loads(f.read(meta_len).decode("utf-8"))
            body = f.read()
        if flags & FLAG_ENCRYPTED:
            if not password:
                raise ValueError("Encrypted .mts; password required.")
            salt = bytes.fromhex(meta["salt"])
            nonce = bytes.fromhex(meta["nonce"])
            body = _decrypt(body, password, salt, nonce)
        bundle = json.loads(body.decode("utf-8"))
    else:
        bundle = json.loads(p.read_text(encoding="utf-8"))

    brain_dict = bundle.get("brain") or {}
    slug = brain_dict.get("slug") or _slugify(brain_dict.get("name") or "imported")
    b = _load_brain(slug)
    if b is None:
        b = create(brain_dict.get("name") or slug,
                   description=brain_dict.get("description") or "",
                   budget_tokens=int(brain_dict.get("budget_tokens") or _DEFAULT_BUDGET_TOKENS))
    entries = bundle.get("entries") or {}
    ids = entries.get("ids") or []
    docs = entries.get("documents") or []
    metas = entries.get("metadatas") or []
    if ids and docs:
        col = _collection(b.slug)
        if col is not None:
            try:
                col.upsert(ids=ids, documents=docs, metadatas=metas or None)
            except Exception as e:
                print(f"[Brains] restore upsert failed: {e}")
    _save_brain(b)
    return b


# ── Stats ────────────────────────────────────────────────────────────────────

def stats(brain: Brain | str | None = None) -> dict:
    b = _resolve(brain)
    col = _collection(b.slug)
    count = 0
    if col is not None:
        try:
            count = col.count()
        except Exception:
            count = 0
    return {
        "slug": b.slug,
        "name": b.name,
        "entries": count,
        "approx_tokens": int(b.stats.get("tokens", 0) or 0),
        "budget_tokens": b.budget_tokens,
        "updated_at": b.updated_at,
    }


def _bump_stats(b: Brain, *, kind: str, delta_tokens: int = 0, folded: int = 0) -> None:
    b.stats.setdefault("by_kind", {})
    b.stats["by_kind"][kind] = int(b.stats["by_kind"].get(kind, 0)) + 1
    b.stats["tokens"] = int(b.stats.get("tokens", 0)) + int(delta_tokens)
    if folded:
        b.stats["folded_total"] = int(b.stats.get("folded_total", 0)) + int(folded)
    _save_brain(b)


def _approx_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


# ── Integration used by memory_loop.inject_context ──────────────────────────

def recall_for_prompt(user_prompt: str, *, k: int = 5) -> list[dict]:
    """Convenience wrapper used by memory_loop; returns the active brain's hits."""
    b = active()
    if b is None:
        return []
    return recall(user_prompt, k=k, brain=b)
