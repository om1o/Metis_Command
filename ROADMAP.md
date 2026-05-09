# Metis Command — 18-Phase Roadmap

> Generated 2026-05-02 after full codebase audit (46 Python modules, 6 HTML pages, 4 JS files, 976-line API bridge, 11 local Ollama models, 4 persistent agents running).

---

## Current State (v0.16.4)

### Working
- Manager orchestrator with 4 specialists (Researcher, Coder, Thinker, Scholar)
- Sequential specialist execution (avoids VRAM thrashing)
- FastAPI backend with 59+ routes on port 7331
- Supabase auth (email/password, Google/GitHub OAuth, PKCE)
- Local install token for desktop use
- 6-step setup wizard (company, manager name/color, personality presets, model picker, director profile, crew)
- Splash screen with Ollama auto-start
- Streaming SSE chat with subagent activity cards
- Markdown rendering with code syntax labels + copy buttons
- Reasoning/thinking collapsible toggle (deepseek-r1)
- Command palette (Cmd+K) with 6 commands
- Mobile hamburger sidebar drawer
- Session management (load, delete)
- Agent health sidebar panel (4 persistent agents)
- Model selector dropdown (11 local + cloud routes)
- Wallet system (simulated budget, policies, ledger)
- Scheduler (interval/daily/once/cron with croniter)
- Memory vault (ChromaDB vectors + Supabase persistence)
- Memory GC (compact_older_than)
- Distributed tracing (trace_id correlation)
- Agent bus with backpressure handling
- Tool runtime with per-tool timeouts
- Confirm gate with TTL expiry
- Secret scanning + path safety
- 5 persona presets (Athena, Atlas, Aria, Kai, Nova)
- Response timing + specialist attribution
- Streaming timeout UI (30s warning)
- Specialist cap at 2 per turn
- Default model: qwen3.5:4b (stronger than 1.5b)

### Known Gaps
- No MFA/2FA
- Notification bell UI not yet wired (backend + routes done; desktop-ui bell needs polling `GET /notifications/count`)
- Search backend done (`GET /sessions/search` with FTS5); no search UI in desktop-ui yet
- No rate limit UI feedback
- Legacy Streamlit UI (`dynamic_ui.py`) remains in the tree for reference; `launch.py` only starts FastAPI

### Completed (v0.16.5)
- ✅ Local conversation memory (SQLite, Phase 1)
- ✅ Multi-turn context window (Phase 2)
- ✅ Session titles auto-generated (Phase 3)
- ✅ File/image upload + drag-drop (Phase 4)
- ✅ Export conversations — MD / JSON / TXT (Phase 5)
- ✅ Search across conversations — FTS5 SQLite + `GET /sessions/search` (Phase 6)
- ✅ Voice input (browser Web Speech API, Phase 8)
- ✅ Dark / Light / Auto theme toggle (Phase 9)
- ✅ Notification system — `notifications.py`, ring buffer + SQLite, 6 API routes, job-complete bell (Phase 10)
- ✅ Onboarding tour — 5-step spotlight (Phase 11)
- ✅ Keyboard shortcuts: ⌘Shift+C copy, ⌘Shift+R regen, ↑ edit last (Phase 12)
- ✅ Plugin Marketplace UI — slide-out panel, filter tabs, install/buy buttons (Phase 7)
- ✅ Analytics Dashboard — /analytics-ui with stat cards, mission bars, token breakdown (Phase 16)
- ✅ Image/Video generation — modes fully live (label cleanup); `POST /generate/image`, `POST /generate/video`
- ✅ memory_loop vector memory opt-in — guard ChromaDB behind METIS_CHAT_VECTOR_MEMORY env flag
- ✅ Model picker priority — fast models float to top; FAST_MANAGER_MODEL = qwen2.5-coder:1.5b
- ✅ PWA foundation (Phase 18) — manifest.json, service worker at /sw.js (root scope), offline shell caching, push notification plumbing, Apple/Android Add-to-Home-Screen meta tags across all HTML pages
- ✅ Multi-model comparison API (Phase 13 backend) — `POST /chat/compare` runs same prompt against N models in parallel via ThreadPoolExecutor, stable result ordering, 90s timeout; `compareModels()` added to api.js
- ✅ Compare panel UI (Phase 13 frontend) — ⚖️ button in header, full-screen side-by-side panel, model chip selector (up to 4), Ctrl+Enter to run, per-column timing display, copy support via command palette

---

## Phase 1 — Local Memory Layer
**Goal**: Chat history works for local-install users without Supabase.

- Add `LocalMemoryStore` in `memory.py` — SQLite file at `identity/local_chat.db`
- Tables: `sessions(id, title, created_at, updated_at)`, `messages(id, session_id, role, content, created_at)`
- Wire `save_message()` and `load_session()` to use SQLite when `user_id == "local-install"`
- Auto-generate session titles from the first user message (first 60 chars)
- Show real session list in sidebar with titles instead of IDs

**Files**: `memory.py`, `api_bridge.py`
**Est**: Small

---

## Phase 2 — Conversation Context Window
**Goal**: Multi-turn conversations actually remember previous messages.

- In `manager_orchestrator.orchestrate()`, call `memory_loop.inject_context()` before planning
- Prepend last 6 turns from the session into the Manager's system prompt
- Prepend top-K relevant vector memories from ChromaDB
- After each turn, call `memory_loop.persist_turn()` to save both sides
- Frontend: show session title in header when a past session is loaded

**Files**: `manager_orchestrator.py`, `memory_loop.py`, `frontend/app.html`
**Est**: Small

---

## Phase 3 — Smart Session Titles
**Goal**: Sessions get human-readable titles instead of `sess-1746192xxx`.

- After the first assistant response, ask the Manager (1 cheap call) to generate a 4-6 word title
- Save title in the session store (SQLite for local, Supabase metadata for cloud)
- Show titles in sidebar session list
- Add rename button (pencil icon) on hover

**Files**: `memory.py`, `api_bridge.py`, `frontend/app.html`
**Est**: Small

---

## Phase 4 — File Upload & Attachments
**Goal**: Users can drop files into the chat input.

- Add drag-and-drop zone on the input area
- Upload to `POST /upload` → saves to `artifacts/` with metadata
- Include file content (or summary for large files) in the Manager's prompt
- Support: `.py`, `.js`, `.ts`, `.json`, `.csv`, `.txt`, `.md` (text files)
- Show file chip below the input with name + size

**Files**: `api_bridge.py`, `frontend/app.html`
**Est**: Medium

---

## Phase 5 — Export & Share Conversations
**Goal**: Export a conversation as Markdown, JSON, or shareable link.

- Add export button in message actions area
- Formats: `.md` (formatted), `.json` (raw messages), clipboard (plain text)
- Export includes metadata: manager name, model, specialists used, timestamps
- Add `/sessions/{id}/export` API route

**Files**: `api_bridge.py`, `frontend/app.html`
**Est**: Small

---

## Phase 6 — Search Across Conversations
**Goal**: Find anything you've ever discussed with the Manager.

- Add search icon in sidebar header
- Full-text search across all sessions (SQLite FTS5 for local, Supabase text search for cloud)
- Vector search via ChromaDB for semantic matches
- Results show: session title, matched snippet, timestamp
- Click result → opens that session, scrolls to the match

**Files**: `memory.py`, `api_bridge.py`, `frontend/app.html`
**Est**: Medium

---

## Phase 7 — Plugin Marketplace UI
**Goal**: Browse, install, and manage plugins from the sidebar.

- Add "Marketplace" expander in sidebar
- Fetch plugin catalog from `/marketplace`
- Show cards: name, description, author, price, install button
- Installed plugins show a green checkmark + uninstall option
- Wire install to `POST /marketplace/install`

**Files**: `frontend/app.html`, `marketplace.py`
**Est**: Small

---

## Phase 8 — Voice Input
**Goal**: Talk to the Manager via microphone.

- Add 🎤 button next to the chat input
- Use browser `webkitSpeechRecognition` / `SpeechRecognition` API
- Pipe recognized text directly into the input textarea
- Show recording indicator (pulsing red dot) while listening
- Auto-send after 2s of silence (configurable)
- Graceful fallback: hide button if browser doesn't support speech API

**Files**: `frontend/app.html`
**Est**: Small (browser-native, no backend needed)

---

## Phase 9 — Dark/Light/Auto Theme
**Goal**: Let users choose their preferred theme.

- Add theme toggle in settings/sidebar footer (moon/sun icon)
- Three modes: Dark (current), Light, System (follows OS preference)
- CSS custom properties already centralized in `:root` — swap variable sets
- Persist theme choice in `manager_config` or localStorage
- Light theme: white background, dark text, adjusted glassmorphism

**Files**: `frontend/app.html`, `frontend/login.html`, `frontend/setup.html`, `frontend/splash.html`
**Est**: Medium (need to design the light palette)

---

## Phase 10 — Notification System
**Goal**: Background tasks and agents can notify the user.

- Browser Notification API for persistent agent alerts
- Toast notifications for in-app events (already exists via global-polish.v2.js)
- Add `/notifications` API route that agents can POST to
- Notification bell icon in header with unread count badge
- Click opens a dropdown with recent notifications

**Files**: `api_bridge.py`, `frontend/app.html`, new `notifications.py`
**Est**: Medium

---

## Phase 11 — Onboarding Tour
**Goal**: First-time users get a guided walkthrough of the app.

- After setup wizard completes, show a 5-step overlay tour
- Highlights: sidebar, chat input, model selector, command palette, crew panel
- Uses a lightweight spotlight/tooltip approach (no library needed)
- "Skip" and "Next" buttons, progress dots
- Mark as complete in manager_config so it only shows once

**Files**: `frontend/app.html`, `manager_config.py`
**Est**: Small

---

## Phase 12 — Keyboard Power User Features
**Goal**: Make the app as fast as a terminal for power users.

- Slash commands in chat input: `/clear`, `/model <name>`, `/role <persona>`, `/export`, `/search <query>`
- Cmd+Shift+C → copy last response
- Cmd+Shift+R → regenerate
- Up arrow in empty input → edit last message
- Escape while streaming → stop generation (already works)
- Add keyboard shortcut reference modal (Cmd+?)

**Files**: `frontend/app.html`
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
| 6. Search | 🟡 High | Medium | ✅ Done |
| 7. Marketplace UI | 🟢 Medium | Small | ✅ Done |
| 8. Voice Input | 🟢 Medium | Small | Q3 |
| 9. Themes | 🟢 Medium | Medium | Q3 |
| 10. Notifications | 🟢 Medium | Medium | ✅ Done |
| 11. Onboarding | 🟡 High | Small | Q3 |
| 12. Keyboard Power | 🟢 Medium | Small | Q3 |
| 13. Model Compare | 🟢 Medium | Large | ✅ Done |
| 14. MFA | 🟡 High | Medium | Q4 |
| 15. Workflows | 🟢 Medium | Large | Q4 |
| 16. Analytics | 🟢 Medium | Medium | ✅ Done |
| 17. Desktop Native | 🔴 Critical | Large | Q4 |
| 18. Mobile PWA | 🟡 High | Medium | ✅ Foundation done |
