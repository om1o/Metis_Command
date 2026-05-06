"""
Metis Vault — encrypted credential store for accounts the agent created or
the Director saved manually.

Threat model
------------
We protect against:
  - Disk theft (laptop stolen, drive cloned). Vault file at rest is AES-GCM
    encrypted with a key derived from the Director's master password via
    PBKDF2-HMAC-SHA256 (480k iterations).
  - Casual snooping by other processes on the same machine. The unlocked
    derived key lives only in the Python process memory, never on disk, and
    auto-locks after METIS_VAULT_IDLE_S seconds (default 300).
  - Accidental commit. Vault file is `identity/vault.enc` and is gitignored.

We do NOT protect against:
  - Malware running as the same user (it can read process memory while
    unlocked). For higher-trust setups, integrate with the OS keychain
    (Win Credential Manager / macOS Keychain / Linux libsecret) — left as
    a Group-2 follow-up.

File format
-----------
`identity/vault.enc` is a single JSON document:
    {
      "version": 1,
      "kdf": "pbkdf2-sha256",
      "iterations": 480000,
      "salt": <b64 16 bytes>,
      "verifier_nonce": <b64 12 bytes>,
      "verifier_ct":    <b64 ciphertext of "VAULT_OK" — used to confirm pw>,
      "items": [
          { "id": str, "nonce": <b64>, "ct": <b64>, "meta": {...non-secret} }
      ]
    }

Each item's plaintext is a JSON dict like
    {"site": "...", "username": "...", "password": "...",
     "url": "...", "notes": "...", "created_at": "..."}
The `meta` field on each item holds non-sensitive fields (site, username,
created_at, last_used) so the UI can list entries without unlocking.

Public API (sync, thread-safe via _lock):
    is_initialized() -> bool
    init_vault(master_password: str) -> None
    unlock(master_password: str) -> bool
    lock() -> None
    is_unlocked() -> bool
    add_item(payload: dict) -> str
    get_item(item_id: str) -> dict | None
    list_items() -> list[dict]                 # non-secret meta only
    delete_item(item_id: str) -> bool
    update_meta(item_id: str, meta_patch: dict) -> bool
    rotate_master_password(old_pw, new_pw) -> bool
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


VAULT_FILE = Path("identity") / "vault.enc"
_KDF_ITERATIONS = 480_000
_VERIFIER_PLAINTEXT = b"VAULT_OK"
IDLE_LOCK_S = float(os.getenv("METIS_VAULT_IDLE_S", "300"))


# ── In-memory unlocked state ─────────────────────────────────────────────────

_lock = threading.RLock()
_session: dict[str, Any] = {
    "key": None,             # bytes (32) when unlocked, else None
    "unlocked_at": 0.0,      # last activity timestamp
}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _derive_key(password: str, salt: bytes, iterations: int = _KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def _read() -> dict | None:
    if not VAULT_FILE.exists():
        return None
    try:
        return json.loads(VAULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write(data: dict) -> None:
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Public API ───────────────────────────────────────────────────────────────

def is_initialized() -> bool:
    """True iff a vault file exists with a valid header."""
    data = _read()
    return bool(data and data.get("salt") and data.get("verifier_ct"))


def init_vault(master_password: str) -> None:
    """Create a fresh vault. Refuses to overwrite an existing one."""
    if not master_password or len(master_password) < 8:
        raise ValueError("master password must be at least 8 chars")
    if is_initialized():
        raise RuntimeError("vault already initialized — use rotate_master_password")
    salt = os.urandom(16)
    key = _derive_key(master_password, salt)
    aes = AESGCM(key)
    nonce = os.urandom(12)
    verifier_ct = aes.encrypt(nonce, _VERIFIER_PLAINTEXT, None)
    _write({
        "version": 1,
        "kdf": "pbkdf2-sha256",
        "iterations": _KDF_ITERATIONS,
        "salt": _b64(salt),
        "verifier_nonce": _b64(nonce),
        "verifier_ct": _b64(verifier_ct),
        "items": [],
    })
    # Auto-unlock after init so the caller can immediately add items.
    with _lock:
        _session["key"] = key
        _session["unlocked_at"] = time.time()


def unlock(master_password: str) -> bool:
    """Verify the password and unlock the in-memory session."""
    data = _read()
    if not data:
        return False
    try:
        salt = _ub64(data["salt"])
        nonce = _ub64(data["verifier_nonce"])
        ct = _ub64(data["verifier_ct"])
        key = _derive_key(master_password, salt, data.get("iterations", _KDF_ITERATIONS))
        aes = AESGCM(key)
        plain = aes.decrypt(nonce, ct, None)
        if plain != _VERIFIER_PLAINTEXT:
            return False
    except Exception:
        return False
    with _lock:
        _session["key"] = key
        _session["unlocked_at"] = time.time()
    return True


def lock() -> None:
    """Wipe the in-memory key. Subsequent reads require re-unlock."""
    with _lock:
        _session["key"] = None
        _session["unlocked_at"] = 0.0


def is_unlocked() -> bool:
    with _lock:
        if _session["key"] is None:
            return False
        if time.time() - _session["unlocked_at"] > IDLE_LOCK_S:
            _session["key"] = None
            _session["unlocked_at"] = 0.0
            return False
        return True


def _touch() -> None:
    """Refresh the idle timer on any successful operation."""
    with _lock:
        if _session["key"] is not None:
            _session["unlocked_at"] = time.time()


def _require_key() -> bytes:
    if not is_unlocked():
        raise PermissionError("vault is locked")
    _touch()
    return _session["key"]  # type: ignore[return-value]


def add_item(payload: dict) -> str:
    """
    Store a new credential. `payload` is encrypted whole; we copy a small
    set of NON-SENSITIVE fields (site, username, url, created_at) into a
    plaintext `meta` for listing.

    Returns the new item id.
    """
    key = _require_key()
    data = _read() or {}
    items = data.setdefault("items", [])
    item_id = uuid.uuid4().hex[:12]
    nonce = os.urandom(12)
    aes = AESGCM(key)
    payload_with_id = {**payload, "id": item_id, "created_at": payload.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ct = aes.encrypt(nonce, json.dumps(payload_with_id).encode("utf-8"), None)
    meta = {
        "site":       str(payload.get("site") or "").strip(),
        "username":   str(payload.get("username") or "").strip(),
        "url":        str(payload.get("url") or "").strip(),
        "created_at": payload_with_id["created_at"],
    }
    items.append({
        "id": item_id,
        "nonce": _b64(nonce),
        "ct": _b64(ct),
        "meta": meta,
    })
    _write(data)
    return item_id


def get_item(item_id: str) -> dict | None:
    """Decrypt and return a single credential's full payload."""
    key = _require_key()
    data = _read() or {}
    for it in data.get("items", []):
        if it["id"] == item_id:
            try:
                aes = AESGCM(key)
                plain = aes.decrypt(_ub64(it["nonce"]), _ub64(it["ct"]), None)
                return json.loads(plain.decode("utf-8"))
            except Exception:
                return None
    return None


def list_items() -> list[dict]:
    """Return non-secret metadata for every item.  Doesn't require unlock."""
    data = _read() or {}
    out: list[dict] = []
    for it in data.get("items", []):
        m = dict(it.get("meta") or {})
        m["id"] = it["id"]
        out.append(m)
    return out


def delete_item(item_id: str) -> bool:
    _require_key()
    data = _read() or {}
    before = len(data.get("items", []))
    data["items"] = [it for it in data.get("items", []) if it["id"] != item_id]
    _write(data)
    return len(data["items"]) < before


def update_meta(item_id: str, meta_patch: dict) -> bool:
    """Update non-secret metadata (e.g. last_used). Doesn't change ciphertext."""
    _require_key()
    data = _read() or {}
    for it in data.get("items", []):
        if it["id"] == item_id:
            it["meta"] = {**(it.get("meta") or {}), **(meta_patch or {})}
            _write(data)
            return True
    return False


def rotate_master_password(old_pw: str, new_pw: str) -> bool:
    """Re-encrypt every item under a new master password."""
    if not unlock(old_pw):
        return False
    if not new_pw or len(new_pw) < 8:
        raise ValueError("new password must be at least 8 chars")
    data = _read() or {}
    old_key = _session["key"]
    new_salt = os.urandom(16)
    new_key = _derive_key(new_pw, new_salt)
    aes_old = AESGCM(old_key)  # type: ignore[arg-type]
    aes_new = AESGCM(new_key)
    new_items: list[dict] = []
    for it in data.get("items", []):
        plain = aes_old.decrypt(_ub64(it["nonce"]), _ub64(it["ct"]), None)
        nonce = os.urandom(12)
        ct = aes_new.encrypt(nonce, plain, None)
        new_items.append({**it, "nonce": _b64(nonce), "ct": _b64(ct)})
    nonce = os.urandom(12)
    verifier_ct = aes_new.encrypt(nonce, _VERIFIER_PLAINTEXT, None)
    _write({
        "version": 1,
        "kdf": "pbkdf2-sha256",
        "iterations": _KDF_ITERATIONS,
        "salt": _b64(new_salt),
        "verifier_nonce": _b64(nonce),
        "verifier_ct": _b64(verifier_ct),
        "items": new_items,
    })
    with _lock:
        _session["key"] = new_key
        _session["unlocked_at"] = time.time()
    return True
