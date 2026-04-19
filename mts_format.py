"""
Metis Thought State (.mts) — proprietary identity backup/restore format.

File layout:
    magic      4 bytes   b"MTS1"
    version    1 byte    currently 0x01
    flags      1 byte    bit 0 = encrypted
    meta_len   4 bytes   big-endian uint32
    meta       meta_len  UTF-8 JSON header
    payload    remainder encrypted (AES-GCM) or plain UTF-8 JSON

If a password is supplied, payload is AES-GCM encrypted with a
PBKDF2-SHA256 derived key. Meta contains salt + nonce.
"""

from __future__ import annotations

import json
import os
import struct
import time
from pathlib import Path
from typing import Any

MAGIC = b"MTS1"
VERSION = 0x01
FLAG_ENCRYPTED = 0x01

_PBKDF2_ITERATIONS = 200_000


# ── Crypto helpers ───────────────────────────────────────────────────────────

def _encrypt(plaintext: bytes, password: str) -> tuple[bytes, bytes, bytes]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=MAGIC)
    return ciphertext, salt, nonce


def _decrypt(ciphertext: bytes, password: str, salt: bytes, nonce: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data=MAGIC)


# ── Payload assembly ─────────────────────────────────────────────────────────

def _collect_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind":       "MetisThoughtState",
        "created_at": int(time.time()),
        "persona":    None,
        "user_matrix": None,
        "identity_facts": [],
    }

    try:
        from identity_matrix import get_active_persona
        payload["persona"] = get_active_persona()
    except Exception:
        pass

    matrix_path = Path("identity") / "user_matrix.json"
    if matrix_path.exists():
        try:
            payload["user_matrix"] = json.loads(matrix_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    try:
        from memory_vault import MemoryBank
        bank = MemoryBank()
        # Pull everything under the identity namespace.
        hits = bank.search("identity durable fact about the Director", n_results=100)
        payload["identity_facts"] = [h.get("document") for h in hits if h]
    except Exception:
        pass

    return payload


def _apply_payload(payload: dict[str, Any]) -> None:
    persona = payload.get("persona")
    if persona:
        try:
            from identity_matrix import save_persona
            save_persona(persona)
        except Exception:
            pass

    matrix = payload.get("user_matrix")
    if matrix:
        Path("identity").mkdir(parents=True, exist_ok=True)
        Path("identity", "user_matrix.json").write_text(
            json.dumps(matrix, indent=2),
            encoding="utf-8",
        )

    facts = payload.get("identity_facts") or []
    if facts:
        try:
            from memory_vault import MemoryBank
            bank = MemoryBank()
            for i, fact in enumerate(facts):
                if not fact:
                    continue
                bank.store_interaction(
                    entity_name=f"imported:{int(time.time())}:{i}",
                    facts=str(fact),
                )
        except Exception:
            pass


# ── Public API ───────────────────────────────────────────────────────────────

def export_identity(path: str, password: str | None = None) -> str:
    payload = _collect_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    flags = 0
    meta: dict[str, Any] = {"compressed": False, "items": list(payload.keys())}
    if password:
        cipher, salt, nonce = _encrypt(body, password)
        flags |= FLAG_ENCRYPTED
        meta["salt"] = salt.hex()
        meta["nonce"] = nonce.hex()
        body = cipher

    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("B", VERSION))
        f.write(struct.pack("B", flags))
        f.write(struct.pack(">I", len(meta_bytes)))
        f.write(meta_bytes)
        f.write(body)
    return str(out)


def import_identity(path: str, password: str | None = None) -> dict[str, Any]:
    with open(path, "rb") as f:
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
            raise ValueError("File is encrypted; password required.")
        salt = bytes.fromhex(meta["salt"])
        nonce = bytes.fromhex(meta["nonce"])
        body = _decrypt(body, password, salt, nonce)

    payload = json.loads(body.decode("utf-8"))
    _apply_payload(payload)
    return payload
