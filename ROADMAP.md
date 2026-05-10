# Metis Command — 18-Phase Roadmap

> Updated 2026-05-10 · v0.38.0 · 56 Python modules, 6 HTML pages, 4 JS files, ~4600-line app.html, 11 local Ollama models, 4 persistent agents running.

---

## Current State (v0.38.0)

### Completed (v0.38.0)
- ✅ **`/stats` slash command** — instant session statistics toast: total messages, your messages vs AI messages, approximate word count, active model
- ✅ **Three new slash commands** — `/quiz` (generate a 5-question quiz with answers), `/pros` (pros & cons analysis with 5+ points per side), `/define` (comprehensive term definition with examples and context); 32 slash commands total
- ✅ **Code block line count badge** — code blocks now display `language · NL` (e.g. `python · 24L`) in the top-left label, giving instant size context at a glance
- ✅ **Draft-saved flash indicator** — a subtle `✓ saved` green flash appears next to the word-count badge whenever the input draft is persisted to localStorage, confirming the auto-save
- ✅ **Message count pill in header** — a live `N msgs` pill sits in the chat header beside the session title; updates after every message sent or received, resets on new chat
- ✅ **`⌘⇧F` session search shortcut** — focuses and selects the session search input without touching the browser's native find-in-page; documented in the keyboard shortcuts modal
- ✅ Version bumped to 0.38.0

---

## Previous State (v0.37.0)

### Completed (v0.37.0)
- ✅ **Auto-scroll lock + jump-to-bottom button** — chat auto-scroll pauses when user scrolls up; a floating `↓` button appears to resume and snap to latest; End key also jumps to bottom; auto-scroll re-enables on every new send
- ✅ **Draft persistence** — textarea content saved to localStorage on every keystroke, restored on page reload, cleared on send; no more lost drafts after accidental refresh
- ✅ **Suggestion card rotation** — empty-state suggestion grid now draws from a pool of 16 diverse prompts (code, research, travel, writing, data, brainstorm, etc.); "More ideas" shuffle button rotates through 4 at a time
- ✅ **Slash command prefix injection** — all slash commands now properly inject natural-language system instructions before the user's content (`/eli5 X` → `Explain the following in the simplest terms…\n\nX`); slash prefix is stripped from the user-visible bubble
- ✅ **Three new slash commands** — `/tone` (adjust tone: formal/casual/friendly), `/expand` (add depth and examples), `/shorten` (strip to essentials); 26 commands total
- ✅ **Message timestamps** — every message now shows a relative timestamp (just now / Xs ago / Nm ago / HH:MM) that fades in on hover; updates live for the first few minutes; absolute time in tooltip
- ✅ **⌘, settings shortcut** — Cmd+Comma opens the Settings panel; End key jumps to chat bottom; both documented in the shortcuts modal
- ✅ Version bumped to 0.37.0

---

## Previous State (v0.36.0)

### Completed (v0.36.0)
- ✅ **Light theme polish** — scrollbars, code blocks, notification/marketplace/tour/scheduler panels, input row, reasoning toggle, thinking timer all styled for light mode
- ✅ **Smooth sidebar collapse animation** — grid-template-columns + opacity transition instead of abrupt snap
- ✅ **Four new slash commands** — `/eli5`, `/rewrite`, `/table`, `/tldr`; 22 commands total
- ✅ **Dynamic time-of-day greeting** — empty state verb rotates: build → create → explore → hack
- ✅ **Word count badge** — shows `Nw · Nc` in the input hint row while typing
- ✅ Version bumped to 0.36.0

---

## Previous State (v0.35.0)

### Completed (v0.35.0)
- ✅ **Slash command input-guard fix** — selecting a slash command no longer sends immediately
- ✅ **Theme toggle shortcut** — ⌘⇧T documented in keyboard help modal
- ✅ **New slash commands** — `/pin`, `/debug`, `/help`
- ✅ Version bumped to 0.35.0

---

## Previous State (v0.33.0)

### Completed (v0.33.0)
- ✅ **Two new slash commands** — `/analyze` (find patterns, trends, and insights in data) and `/outline` (structured outline or table of contents); 14 commands total in autocomplete
- ✅ **Search jump-to-match** — clicking a server search result now loads the session and scrolls directly to the matching message, flashing a violet ring highlight for ~2.8 s so the user can instantly see what matched
- ✅ **Cost-per-message in token badge** — token count badge now includes an estimated cost (`~2.1k tok · $0.0012`) for cloud models using a live price map (GPT-4o, GPT-4, GPT-3.5, Groq Llama/Mixtral/Gemma, GLM); local Ollama models show no cost (free); tooltip explains both figures
- ✅ Version bumped to 0.33.0

---

## Previous State (v0.32.0)

### Completed (v0.32.0)
- ✅ **Three new slash commands** — `/draft` (write polished emails/docs/messages), `/fix` (proofread and fix grammar/clarity), `/translate` (translate to a target language); 12 commands total in autocomplete
- ✅ **Session auto-trim** — when in-memory sessions exceed 65, oldest unpinned sessions are pruned down to ~55; pinned sessions are always preserved; localStorage cap raised from 30 → 60 with same pinned protection
- ✅ **Time-aware greeting on empty hero** — replaces static "What can your agent do for you today?" with a contextual greeting based on time of day (Good morning / afternoon / evening / Working late?)
- ✅ Version bumped to 0.32.0

---

## Previous State (v0.31.0)

### Completed (v0.31.0)
- ✅ **Token count badge on agent messages** — backend emits a `turn_complete` SSE event after each turn with an estimated token count (`len(response) // 4`); UI renders a `~N tok` pill next to the "via model" badge on every completed agent response
- ✅ **Slash command prefix injection** — `/code`, `/plan`, `/search`, `/think`, `/summarize`, `/bullets`, and `/remember` now inject a system-level instruction before the user's text when submitted (e.g. `/code fix this bug` becomes `You are helping write, explain, or debug code…\n\nfix this bug`); the slash prefix is stripped from the user-visible message bubble
- ✅ **Two new slash commands** — `/summarize` (condense to 3-5 bullet points) and `/bullets` (format entire response as structured bullets) added to the autocomplete menu; 9 commands total
- ✅ **Shortcuts reference updated** — `⌘ ⇧ C` (Copy last response) and `⌘ ⇧ R` (Regenerate response) added to the Settings → Shortcuts cheat-sheet
- ✅ Version bumped to 0.31.0

---

## Previous State (v0.30.0)

### Completed (v0.30.0)
- ✅ **Markdown table rendering** — `MarkdownView` now parses and renders pipe-syntax markdown tables with alternating row shading, header styling, and inline formatting in cells; horizontal rules (`---`) also supported
- ✅ **Slash command autocomplete** — typing `/` in the composer shows an animated floating menu with 7 built-in commands (`/code`, `/plan`, `/search`, `/think`, `/remember`, `/clear`, `/help`); arrow-key navigation, Tab/Enter to select, Escape to dismiss; `/clear` starts a new session, `/help` opens Settings
- ✅ **⌘Shift+C copy last response** — new global shortcut copies the last agent message to clipboard (in addition to the per-message copy button)
- ✅ **⌘Shift+R regenerate** — new global shortcut retriggers the last turn (same as the Retry hover button)
- ✅ **Session pinning** — hover any session → 📌 pin button; pinned sessions float to a "Pinned" group at the top of the sidebar regardless of date; pin state persists via `localStorage`; pinned indicator replaces the dot with a pin icon
- ✅ Version bumped to 0.30.0

---

## Previous State (v0.29.0)

### Completed (v0.29.0)
- ✅ **Session date grouping** — sidebar SessionsList now groups conversations under "Today / Yesterday / This Week / Earlier" section headers; flat list is restored automatically when a search query is active
- ✅ **Streaming markdown rendering** — agent messages now render through `MarkdownView` while streaming instead of plain whitespace-pre-wrap text; code blocks, headers, and lists format live as they arrive
- ✅ **Up-arrow edit last message** — pressing ↑ in an empty composer recalls the last user message for inline editing; cursor placed at end; resizes the textarea automatically
- ✅ **Export shortcut documented** — `⌘E` and "Edit last message" (↑) added to the Settings → Shortcuts reference list
- ✅ Version bumped to 0.29.0

---

## Previous State (v0.28.0)

### Completed (v0.28.0)
- ✅ **Session rename persistence** — `renameSession()` now calls `POST /sessions/:id/rename` after updating local state; renames survive page reload
- ✅ **Export conversation** — `⌘E` (and the ↓ button in the chat header) downloads the active session as a `.md` file; `MetisClient.exportSession()` + `exportSessionUrl()` added
- ✅ **Session keyboard navigation** — `⌘[` / `⌘]` jump to the previous / next session in the sidebar list (was documented in v0.21 but missing from the React shortcuts handler)
- ✅ **Connections in collapsed sidebar** — Globe icon button (with health-status dot) added to the collapsed icon strip; it was missing despite every other panel being present
- ✅ **Composer character count** — displays `N chars` next to the attach button when the draft exceeds 400 characters; turns amber at >3000
- ✅ Version bumped to 0.28.0

---

## Previous State (v0.27.0)

### Completed (v0.27.0)
- ✅ **session_title SSE** — `send()` now handles the `session_title` event the backend emits after each turn, updating the session title in the sidebar without a page reload
- ✅ **project_slug in chat** — `MetisClient.chat()` accepts `projectSlug` option and forwards it as `project_slug` to the backend; the active workspace is now always injected into every chat turn
- ✅ **Regenerate response** — Hover the last agent message → "Retry ↺" button replaces the message in-place and re-streams from the same user prompt
- ✅ **Session rename** — Hover a session in the sidebar → pencil icon → inline rename input (Enter/blur to save, Escape to cancel)
- ✅ **Absolute timestamp tooltips** — Hovering any message timestamp shows the full date/time (e.g. "May 10, 2:34 PM")
- ✅ Version bumped to 0.27.0

---

## Previous State (v0.26.0)

### Completed (v0.26.0)

- ✅ Message feedback — thumbs up/down buttons on agent messages in React UI; `postMessageFeedback()` added to `MetisClient`; optimistic state stored per-message; wired to `POST /messages/feedback`
- ✅ Active project name in header — header pill and sidebar badge now show the project **name** instead of its URL slug; `onActiveChange(slug, name)` callback updated in `ProjectsPanel`
- ✅ Fixed collapsed sidebar — Briefing (⌘D) and Missions (⌘O) icon buttons were missing from the collapsed icon strip; added alongside all other panels
- ✅ Fixed keyboard shortcuts modal — "Projects (⌘W)" was absent from the Settings → Shortcuts list; added in correct position
- ✅ Version bumped to 0.26.0

---

## Previous State (v0.25.0)

### Completed (v0.25.0)
- ✅ Projects / Workspaces — `ProjectsPanel` slide-out with full CRUD (create, rename, custom instructions, delete, activate/deactivate), active-project indicator, expand/collapse sections
- ✅ Active project context injection — backend prepends project instructions on every chat turn when a project is active
- ✅ Project badge in header — `📁 ProjectName` pill next to conversation title; click to open panel
- ✅ Sidebar "Projects" nav item (⌘W) with active-project indicator dot in collapsed mode
- ✅ Version bumped to 0.25.0

---

## Current State (v0.23.0)

### Completed (v0.23.0)
- ✅ Host Automation MVP — `POST /automation/browser` (Playwright Chromium: start, goto, snapshot, click, fill, extract, screenshot, close) + `POST /automation/shell` (allow-listed shell with 428 confirm-gate)
- ✅ `AutomationPanel` — full-screen modal (⌘T) with Browser tab (URL nav, click, fill, extract) and Shell tab (allow-listed programs chip bar, stdout/stderr rendered separately, exit-code badge)
- ✅ `HostAutomationMvp` — compact version embedded in Settings with click/fill/extract sub-panels and smart output rendering (renders text/title for snapshots, exit-code + stdout/stderr for shell)
- ✅ `MetisClient.automationBrowser()` + `automationShell()` — typed TypeScript methods covering all actions
- ✅ Sidebar "Automation" nav button (⌘T, collapsed icon) alongside Jobs/Inbox/Relationships
- ✅ `METIS_BROWSER_ALLOW_LOCALHOST` env flag — safely allows automation against 127.0.0.1 dev servers
- ✅ Connections panel now shows endpoint URL on cloud-provider failure for easier debugging
- ✅ Version bumped to 0.23.0

---

## Previous State (v0.22.0)

### Completed (v0.22.0)
- ✅ Projects / Workspaces — `projects.py` fully wired: `GET/POST /projects`, `GET/PATCH/DELETE /projects/{slug}`, `POST /projects/{slug}/activate`, `GET/DELETE /projects/active`
- ✅ Projects sidebar panel — collapsible list of projects with active indicator, create button, delete button; clicking a project toggles it as the active workspace
- ✅ Project context injection — when a project is active, its custom instructions and description are prepended to every chat message via `wire_message` in the orchestration pipeline
- ✅ Project badge in header — shows `📁 ProjectName` pill next to the Direct badge; click to clear the active project
- ✅ Projects in api.js — `createProject`, `activateProject`, `clearActiveProject`, `updateProject`, `deleteProject`, `activeProject` methods added to the API client
- ✅ `chatStream` updated — now accepts and forwards `projectSlug` to the backend `project_slug` field
- ✅ `/project` slash command and Command Palette entry for quick workspace switching
- ✅ Version bumped to 0.22.0

---

## Previous State (v0.21.0)

### Completed (v0.21.0)
- ✅ Session date grouping — sidebar now groups conversations into Today / Yesterday / This Week / Earlier
- ✅ Message feedback — thumbs up/down buttons on every assistant response; stored to `identity/feedback.jsonl`; `GET /messages/feedback/summary` for aggregate stats
- ✅ Keyboard session navigation — `Ctrl+[` / `Ctrl+]` to jump to previous / next session in the list
- ✅ Model ID display — the header model selector now shows the actual model slug alongside the tier name (Fast · qwen2.5-coder)
- ✅ Five new workflow templates — Competitor Analysis, Bug Triage → Fix → Verify, Content Pipeline, Deep Research Loop added alongside the original four
- ✅ Backend feedback endpoint — `POST /messages/feedback`, `GET /messages/feedback/summary`
- ✅ Shortcuts modal updated — `⌘[` / `⌘]` session navigation documented

---

## Previous State (v0.20.0)

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

### Completed (v0.20.0)
- ✅ Sidebar collapse toggle — Ctrl+B collapses/expands the left panel; state persisted in localStorage; sidebar toggle button added to main header (desktop only)
- ✅ Keyboard shortcuts reference modal — Ctrl+/ opens a full cheat-sheet modal covering navigation, conversation, and all slash commands
- ✅ Slash command inline menu — typing `/` in the chat input shows a floating autocomplete menu for `/code`, `/plan`, `/search`, `/model`, `/remember`, `/forget`, `/clear`, `/export`; arrow keys + Tab/Enter to select
- ✅ Direct mode header badge — ⚡ Direct pill appears in the header when Direct mode is active
- ✅ Ctrl+M push-to-talk — global shortcut triggers the mic button
- ✅ Always-visible pin star — pinned sessions show the star permanently (not just on hover)
- ✅ Ctrl+/ → shortcuts modal (previously focused input); Ctrl+B, Ctrl+M wired globally
- ✅ Shortcuts modal added to command palette
- ✅ Sidebar toggle added to command palette

### Known Gaps
- Notification bell UI is wired (polls `/notifications/count` every 30s — ✅ done)
- Session FTS5 search UI wired in sidebar (✅ done)
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
- ✅ MFA / Two-Factor Auth (Phase 14) — `enroll_totp`, `verify_totp`, `list_mfa_factors`, `unenroll_totp` in `auth_engine.py`; API routes `POST /auth/mfa/enroll`, `POST /auth/mfa/verify`, `GET /auth/mfa/factors`, `POST /auth/mfa/unenroll`; login challenge step (auto-triggers after sign-in when TOTP factor present); Settings panel Security section with QR code enroll/disable flow; rate-limit 429 toast feedback in `api.js`
- ✅ Agent Workflow Builder (Phase 15) — `workflows.py` engine (6 node types, 4 built-in templates, run/save/delete); 7 API routes; `frontend/workflow.html` visual canvas with drag-and-drop, pan/zoom, bezier edges, properties panel, run-results drawer; workflow button + command palette entry in `app.html`; compare panel now renders markdown

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

## Phase 15 — Agent Workflow Builder ✅
**Goal**: Visual editor for creating multi-step agent workflows.

- ✅ Drag-and-drop canvas for connecting specialists into pipelines
- ✅ Node types: Prompt, Specialist, Condition, Loop, Human Review, Output
- ✅ Save workflows as JSON to `identity/workflows/`
- ✅ Execute via `POST /workflows/{id}/run` API route
- ✅ Template library: "Research → Summarize", "Code → Review → Test", "Plan → Execute → Human Review", "Daily Briefing"
- ✅ Pan / zoom canvas, edge bezier curves, properties panel, run-results drawer

**Files**: `workflows.py`, `api_bridge.py`, `frontend/workflow.html`, `frontend/static/js/api.js`
**Shipped**: v0.19.0

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
| 14. MFA | 🟡 High | Medium | ✅ Done |
| 15. Workflows | 🟢 Medium | Large | ✅ Done |
| 16. Analytics | 🟢 Medium | Medium | ✅ Done |
| 17. Desktop Native | 🔴 Critical | Large | Q4 |
| 18. Mobile PWA | 🟡 High | Medium | ✅ Foundation done |
