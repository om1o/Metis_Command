# Metis — Zero-Trust Security Whitepaper

**Classification:** public · v16.3 · 2026-04

Metis is designed from first principles for environments that cannot legally send data to a cloud vendor — hedge funds, law firms, defense contractors, healthcare, and any business bound by GDPR/HIPAA/SOX/PCI-DSS.

This document explains exactly how your data is protected at every layer.

---

## 1. Threat model

| Threat                                       | Metis mitigation |
|---|---|
| Corporate data ingested into a vendor LLM    | 100% local model execution via Ollama; no outbound inference calls. |
| Credential leak through prompt exfiltration  | No telemetry, no analytics, no silent fetches. |
| Malicious AI-generated code damaging host    | All forged skills execute inside an ephemeral Docker container with no mounts, no network, and 256 MB memory cap. |
| Tampered memory or identity                  | ChromaDB and Supabase under user-controlled keys; `.mts` identity files are AES-GCM encrypted with PBKDF2-SHA256. |
| Account takeover                             | Supabase Auth with Row-Level Security on every table; session tokens never leave the device. |
| Network interception                         | The only outbound traffic is optional Supabase sync; plaintext secrets never written to disk. |

## 2. Execution isolation

Every piece of AI-generated code runs through `skill_forge.run_in_sandbox()`:

- Base image: `python:3.12-slim` (pinned digest recommended in production).
- `--network=none` — zero network access inside the container.
- `--read-only` root filesystem.
- `--memory 256m --cpus 1` caps.
- 10-second hard timeout.
- Container is destroyed immediately after execution.

Fallback: if Docker is unavailable, a constrained subprocess with the same timeout is used and the Artifact is tagged `[SANDBOX-WARNING]` so the user sees the downgrade.

## 3. Memory protection

- ChromaDB stores vectors locally under `metis_db/` — never transmitted.
- Supabase `memory` table uses RLS policy `auth.uid() = user_id`, so a compromised anon key cannot read other users' rows.
- `.mts` backups are encrypted with a user-chosen password:
  - AES-256-GCM (authenticated encryption; tampering is detected).
  - PBKDF2-SHA256 at 200,000 iterations.
  - Random 16-byte salt + 12-byte nonce per file.

## 4. Identity

- The active persona and `user_matrix.json` are exportable and importable via `.mts`.
- Durable identity facts are separated into a dedicated ChromaDB namespace so Zero-Trust audits can enumerate them.

## 5. Network boundary

Metis opens two local ports by default:
- **8501** — Streamlit UI, bound to `127.0.0.1`.
- **7331** — FastAPI bridge, bound to `127.0.0.1`.

Neither binds to `0.0.0.0`. External extensions must tunnel through the loopback interface.

## 6. Audit

Every side-effecting agent action emits a structured `ToolCallEvent` with `{agent, tool, args, result, duration_ms}`. Events can be persisted to a local `logs/` folder and exported for a SOC review.

## 7. Compliance posture

Metis as delivered is not a certified product, but the architecture is deliberately shaped to simplify:

- **SOC 2 Type II** — all user data stays on-device by default.
- **GDPR Art. 17 (right to erasure)** — one-click memory vault wipe.
- **HIPAA** — air-gap mode + Docker sandbox satisfy the technical safeguard rule.
- **PCI-DSS** — no card data ever touches Metis's memory layer; Stripe tokens never leave the browser tab.

## 8. Contact

Found a vulnerability? Email `security@metis.systems` with a PoC. We respond within 48 hours and run a public bounty program.
