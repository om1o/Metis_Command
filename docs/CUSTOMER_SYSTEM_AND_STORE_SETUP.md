# Customer system + in-store / field setup (Metis)

This note is the **minimum** you need to wire Metis into a real customer system and to run **in-store** or **on-site** workflows (e.g. plumber, retail counter, field tech).

## 1. Little data to collect (minimum)

| Field | Why |
| --- | --- |
| `customer_id` | Your system of record (UUID / CRM id) |
| Service + constraints | What they need, budget, time window, urgency |
| `location` | **ZIP** or `city+state` (required for local provider search) |
| **Consent** | `sms_opt_in`, `email_opt_in`, `call_opt_in` (and timestamp) — **no outreach without this** |
| **Contact** | phone and/or email for the **end customer** and for **you (Director)** to forward results |
| **Outcomes** | Define “done”: e.g. shortlist vs quote vs appointment booked |
| `job_id` / `request_id` | Ties every Metis run to a ticket/row for audit |

## 2. How we use that to integrate (flow)

1. **Your system** creates a **Job/Request** row: status `open`, source `metis`.
2. **Metis** ingests the job, runs research/tools, writes:
   - **Artifact files** (markdown / exports) under `generated/` and records in the **artifact** system.
   - **Structured results** in Supabase (or your CRM) — leads, messages, follow-up tasks.
3. **State sync**: after each tool action (SMS sent, call logged, reply received), **update the same `job_id`** so nothing lives only in chat.
4. **Sub-agent / follow-up**: a scheduler or Metis “Relationship Keeper” reads **open tasks** with `due_at` and executes the next touch (within policy).

**Rule:** the customer’s DB is **source of truth**; the chat is just the UI.

## 3. In-store or field service (add-on fields)

When the work is **in person** (store, home visit, job site):

| Field | Why |
| --- | --- |
| `venue_type` | `in_store` \| `on_site` \| `remote` |
| `store_id` / `site_id` | Which location |
| `access_notes` | Gate, parking, pets, time window, COI |
| `on_site_contact` | Who opens the door / signs |
| `handoff_owner` | Human owner if Metis only queues the visit |

**Integration pattern:** when Metis “books” a slot, the record must link **customer_id + job_id + calendar_event_id** (or your booking system’s id) so the store/field app can show the work order.

## 4. Tools to implement (gaps vs typical “automation AIs”)

**Already in Metis (examples):** chat UI, file artifacts, Supabase, optional email/SMS plumbing (placeholders), web research patterns.

**Still needed for parity with “full” agent products:**

- **Comms (two-way):** Twilio SMS + call status webhooks; optional voice for outbound; unified **inbox** of replies.
- **Email:** send + **read/parse** replies (Gmail/Graph), thread by `message_id` / `job_id`.
- **Calendar:** create/update events, free/busy (Google / Microsoft); requires OAuth per tenant.
- **Local discovery:** Google Places (or similar) for **real** businesses + hours, not just generic web text.
- **CRM / tickets:** HubSpot, Salesforce, Intercom, Zendesk — create Contact/Deal/Ticket and sync status.
- **Webhooks + queue:** your customer system `POST /events`; Metis **worker** consumes and runs tools with retries.
- **Scheduling:** cron/queue for sub-agent “D+1 / D+3” follow-ups (not only Streamlit session).
- **Document/PDF** output for handouts or quotes.
- **Payments (optional, gated):** Stripe with human approval.
- **Observability:** structured run logs, replay, failure codes.

## 5. “Almost automatic” tool use (governance)

To let Metis use tools by default without surprises:

- **Policy per job:** which tools are allowed, spend caps, quiet hours, rate limits.
- **Draft → confirm** for first contact with a new number or for payments.
- **Idempotent writes** (don’t create duplicate leads on rerun).

## 6. What to do next in this repo

- In the **Streamlit sidebar → Tools & outreach**, turn on SMS / phone / email as needed; set `TWILIO_*` and `EMAIL_*` in `.env`. The model receives your choices in the system prompt; skills `send_sms`, `send_email`, and `place_outbound_call` respect those toggles.
- Extend **Supabase** (or your CRM) with: `jobs`, `leads`, `interactions`, `tasks` linked by `job_id` and `customer_id`.
- Register more tools in **Skill Forge** / agent layer: `log_call`, `create_calendar_event`, `sync_crm` — each checks policy + consent.
- Run follow-ups in a **background worker** (or scheduled job), not only when the browser is open.

---
*Keep PII and consent records in your customer system; Metis should only store what’s necessary for the job.*
