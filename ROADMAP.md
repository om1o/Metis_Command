# Metis Command Roadmap

## Direction Lock

Metis is now a desktop-first automation operator.

Product framing:
- Desktop first platform.
- Browser-control first MVP.
- Operator OS is the long-term category, not the first implementation target.

Current non-goals unless directly required by the browser MVP:
- Chat-first product work.
- Code workspace expansion.
- Plugin-store-first work.
- Media-first work.
- Broad OS control beyond browser execution.

## Current Focus

The current production wedge is:
- manager
- browser cockpit
- approvals and per-job auto mode
- automation board
- inbox with real event history
- manager policies

The first credible release claim is:
`a local manager that can control a browser reliably and operate on your machine`

## MVP Milestones

### Milestone 1: Direction lock
- Add repo-level agent instructions so future agents stop following the old roadmap.
- Update README, roadmap, and prompt docs to describe Metis as a desktop-first browser automation operator.
- Keep the old surfaces in the tree, but remove them from product priority language.

### Milestone 2: Browser backend truth
- Make browser control endpoints complete enough for the cockpit.
- Add wait, audit, session mode, and service policy APIs.
- Tie browser safety defaults to manager policy instead of mock UI state.
- Keep safe mode default and allow per-job auto mode only.

### Milestone 3: Browser cockpit
- Replace the current mock browser page behavior with real backend wiring.
- Show live session state, URL, screenshot refresh, audit log, approval queue, and visible control aura.
- Expose reliable manual controls for navigate, fill, click, wait, and screenshot.

### Milestone 4: Manager and automation integration
- Treat browser work as manager-owned jobs.
- Show browser-backed runs in the automation board and inbox.
- Add manager settings for allowed services, daily limits, safe mode, and warning acknowledgement.

### Milestone 5: Brand and shell
- Use the Metis logo as the visual source of truth.
- Apply a control-room design across splash, browser, manager, automations, and inbox.
- Demote old chat/code emphasis without deleting those pages yet.

### Milestone 6: Hardening
- Add tests for browser session lifecycle, service policy enforcement, safe mode vs auto mode, and audit retrieval.
- Run route, unit, and browser smoke checks before claiming the MVP works.
**Est**: Small

---

## Phase 13 — Multi-Model Comparison
**Goal**: Ask the same question to multiple models and compare responses side-by-side.

- New UI mode: "Compare" — splits chat area into 2-3 columns
- User sends one message, it goes to N models in parallel
- Each column streams independently
- Footer shows per-model timing + token count
- Add `/chat/compare` API route

**Files**: `api_bridge.py`, `manager_orchestrator.py`, `frontend/app.html`
**Est**: Large

---

## Phase 14 — MFA / Two-Factor Auth
**Goal**: Secure accounts with TOTP-based 2FA.

- Add `auth_engine.enroll_totp()` → calls Supabase MFA factors API
- Add `auth_engine.verify_totp()` → validates 6-digit code
- Post-login challenge: if MFA is enrolled, show code input before granting access
- Settings page: "Set up 2FA" button → shows QR code for authenticator app
- Recovery codes fallback

**Files**: `auth_engine.py`, `frontend/login.html`, `frontend/app.html`
**Est**: Medium

---

## Phase 15 — Agent Workflow Builder
**Goal**: Visual editor for creating multi-step agent workflows.

- Drag-and-drop canvas for connecting specialists into pipelines
- Node types: Prompt, Specialist, Condition (if/else), Loop, Human Review
- Save workflows as JSON to `identity/workflows/`
- Execute via `/workflows/{id}/run` API route
- Template library: "Research → Summarize → Email", "Code → Test → Deploy"

**Files**: new `workflows.py`, `api_bridge.py`, new `frontend/workflow.html`
**Est**: Large

---

## Phase 16 — Analytics Dashboard
**Goal**: Understand how you use Metis — response times, specialist usage, costs.

- New `/analytics` page (or sidebar panel)
- Charts: daily message count, avg response time, specialist usage distribution
- Cost breakdown: tokens by model, projected monthly spend
- Session stats: busiest hours, longest conversations
- Data from: wallet ledger, audit log, usage_tracker

**Files**: `api_bridge.py`, new `frontend/analytics.html`
**Est**: Medium

---

## Phase 17 — Desktop Native (Tauri/Electron)
**Goal**: Ship as a proper installable desktop app with system tray.

- Wrap the FastAPI + frontend in Tauri (Rust-based, small binary)
- System tray icon with quick-launch
- Global hotkey (Ctrl+Space) to summon from anywhere
- Auto-update mechanism
- macOS + Windows + Linux builds
- Use `metis_daemon.py` as the process manager

**Files**: new `src-tauri/`, `metis_daemon.py`, build scripts
**Est**: Large

---

## Phase 18 — Mobile Companion App
**Goal**: Access Metis from your phone via a lightweight PWA.

- Progressive Web App manifest + service worker
- Offline-capable: cache recent conversations
- Push notifications for agent alerts
- Responsive layout already works (hamburger menu done)
- Add to home screen support (iOS + Android)
- Sync with desktop via the same Supabase backend

**Files**: `frontend/manifest.json`, new `frontend/sw.js`, `frontend/app.html`
**Est**: Medium

---

## Priority Matrix

| Phase | Impact | Effort | Priority |
|-------|--------|--------|----------|
| 1. Local Memory | 🔴 Critical | Small | **Do first** |
| 2. Context Window | 🔴 Critical | Small | **Do first** |
| 3. Session Titles | 🟡 High | Small | Soon |
| 4. File Upload | 🟡 High | Medium | Soon |
| 5. Export | 🟢 Medium | Small | Soon |
| 6. Search | 🟡 High | Medium | Q3 |
| 7. Marketplace UI | 🟢 Medium | Small | Q3 |
| 8. Voice Input | 🟢 Medium | Small | Q3 |
| 9. Themes | 🟢 Medium | Medium | Q3 |
| 10. Notifications | 🟢 Medium | Medium | Q3 |
| 11. Onboarding | 🟡 High | Small | Q3 |
| 12. Keyboard Power | 🟢 Medium | Small | Q3 |
| 13. Model Compare | 🟢 Medium | Large | Q4 |
| 14. MFA | 🟡 High | Medium | Q4 |
| 15. Workflows | 🟢 Medium | Large | Q4 |
| 16. Analytics | 🟢 Medium | Medium | Q4 |
| 17. Desktop Native | 🔴 Critical | Large | Q4 |
| 18. Mobile PWA | 🟡 High | Medium | 2027 |
