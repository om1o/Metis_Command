# Metis Command — V16.3 Apex

**Local-first autonomous AI operating system. Runs 100% on your hardware.**

Metis is a Claude.ai + Codex-style desktop AI that orchestrates a 5-agent CrewAI swarm on top of local Ollama models. Memory persists across sessions via ChromaDB + Supabase. Skills are forged on demand and executed inside a Docker sandbox. Voice and computer-use tools let Metis hear you and drive your desktop.

---

## Feel

- Left sidebar — chat history, persona, hardware tier badge, planning toggle, palette, shortcuts, theme, artifacts toggle, brain backup.
- Main thread — streaming chat with tool-call cards, Show-thinking dropdown, copy/regenerate/read-aloud on every assistant message, drag-drop attachments, voice input.
- Right pane — live Artifacts panel watching `artifacts/` for code, diffs, images, and charts.
- Status bar — active role, tier, live tok/s, session id.
- Gemini-style rotating aura behind the logo, **only while thinking**.

## Architecture

```
User prompt
   │
   ▼
Genius (GLM-4.6 / local glm4:9b) ◄── apex reasoning + synthesis
   │
Manager (qwen2.5-coder:1.5b) ──► Coder (qwen2.5-coder:7b)
                              ├─► Thinker (deepseek-r1)
                              ├─► Scholar (qwen3.5:4b)
                              └─► Researcher (llama3.2:3b)
                              └─► Persistent roster (scheduler, news_digest,
                                  finance_watch, shopper, travel_agent…)
                              └─► Agent Bus (morning_briefing, alerts,
                                  handoff, approvals)

                Brains (per-profile Chroma collection)
                   │  episodic / semantic / procedural
                   │  auto-compacted — "never forget"
                   ▼
                ChromaDB ◄──── memory_loop.inject_context
                   │
                Supabase (RLS) ◄──── memory.persist_turn
                   │
                .mts ◄──── mts_format (AES-GCM)

                Orchestrator Wallet
                   │  cloud_api / plugin / subagent / compute / data
                   │  policies + monthly cap + ledger (logs/wallet.jsonl)
                   └─► Stripe Issuing (opt-in, STRIPE_ISSUING_KEY)

Docker sandbox ◄──── skill_forge.forge_skill
Computer Use ◄──── tools/computer_use (mss + pyautogui, confirm-gated)
Voice I/O  ◄──── tools/voice_io (SpeechRecognition + pyttsx3)
```

### New in 16.4

- **Genius brain (GLM-4.6 via Z.ai)** — set `GLM_API_KEY` to unlock; falls back to local `glm4:9b` via Ollama automatically.
- **Brains** — swappable long-term memory profiles (`brains.create`, `brains.switch`). Each one stores episodic turns, distilled semantic facts, and procedural recipes in its own Chroma collection and gets auto-compacted so the agent never forgets.
- **Orchestrator Wallet** — policy-gated budget (`wallet.charge`, `wallet.top_up`) that bills cloud API calls, plugin purchases, and subagent summons. Defaults to simulated; flip `METIS_WALLET_MODE=stripe_issuing` + set `STRIPE_ISSUING_KEY` to attach a real virtual card.
- **Agent Roster** — 12 data-driven specialists (`identity/roster.json`) including `scheduler`, `news_digest`, `finance_watch`, `shopper`, `travel_agent`, `security_auditor`. Start them as long-running workers via `agent_roster.spawn_persistent(slug)`.
- **Agent Bus** — explicit message bus so agents talk to each other (`agent_bus.publish`, `agent_bus.conversation`). Audit-logged to `logs/agent_bus.jsonl`.
- **Daily plan** — `scheduler.seed_default_schedules()` installs three jobs: `daily_briefing` at 07:00 (writes `artifacts/daily_plan_YYYY-MM-DD.md` and optionally emails via `DAILY_PLAN_EMAIL`), `nightly_brain_compact` at 02:00, `weekly_brain_backup` on Sundays at 03:00.

## Quickstart

1. **Install Ollama** and pull a few models:
   ```powershell
   ollama pull qwen2.5-coder:7b
   ollama pull qwen2.5-coder:1.5b
   ollama pull deepseek-r1:1.5b
   ollama pull qwen3.5:4b
   ollama pull llama3.2:3b
   ollama pull llava:latest
   ```

2. **Set up the venv** (a `metis-env` folder already exists):
   ```powershell
   .\metis-env\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Copy `.env.example` → `.env`** and fill in Supabase + Stripe + OpenAI keys. All are optional except `SUPABASE_URL` + `SUPABASE_KEY` if you want cloud features.

4. **Run the Supabase schema** (`schema.sql`) once in the SQL editor.

5. **Launch everything**:
   ```powershell
   python start_metis.pyw
   ```
   This starts the Streamlit UI (`:8501`), the FastAPI bridge (`:7331`), and the system-tray daemon with a global `Ctrl+Space` hotkey.

6. **Optional — add to Windows Startup**:
   ```powershell
   python scripts/install_startup.py install
   ```

## Keyboard shortcuts

| Keys                  | Action                     |
|-----------------------|----------------------------|
| `Ctrl+Space`          | Toggle Metis window        |
| `Ctrl+K`              | Command palette            |
| `Ctrl+Shift+N`        | New chat                   |
| `Ctrl+Enter`          | Send message               |
| `Esc`                 | Stop generation            |
| `Ctrl+/`              | Shortcuts cheat sheet      |
| `Ctrl+B`              | Toggle sidebar             |
| `Ctrl+J`              | Toggle artifacts pane      |
| `Ctrl+M`              | Push-to-talk (mic)         |

## Slash commands

`/code` · `/plan` · `/search` · `/skill` · `/sandbox` · `/remember` · `/forget` · `/model` · `/screenshot` · `/speak` · `/click`

## Smoke test

```powershell
python -m tests.smoke
```

Walks imports → hardware → brain → modules → artifacts → skills → sandbox → `.mts` round-trip → subscription → marketplace → API bridge. Every step is independent, so one missing optional dep won't cascade.

## Docs

- `docs/CHANGELOG_V1_TO_V16.3.md` — full version history.
- `docs/PITCH_DECK.md` — 10-slide VC outline.
- `docs/LANDING_COPY.md` — hero + features + CTA (no GB numbers shown).
- `docs/SECURITY_WHITEPAPER.md` — Zero-Trust Manifesto for Wall Street.

## Files

| File                    | Purpose                                          |
|-------------------------|--------------------------------------------------|
| `brain_engine.py`       | Tri-Core Ollama dispatcher + streaming          |
| `module_manager.py`     | Silent tier downloader (Lite/Standard/Sovereign) |
| `swarm_agents.py`       | 5-agent CrewAI swarm                            |
| `task_manager.py`       | Task factory for chat/plan/code/research modes   |
| `crew_engine.py`        | Hierarchical mission runner with event stream    |
| `memory.py`             | Supabase chat persistence                        |
| `memory_vault.py`       | ChromaDB vector memory                          |
| `memory_loop.py`        | 4 Pillars wired together                         |
| `identity_matrix.py`    | Persona store                                    |
| `skill_forge.py`        | Registry + Docker sandbox + forge_skill         |
| `artifacts.py`          | Artifact dataclass + watchable store            |
| `tools/computer_use.py` | mss + pyautogui (confirm-gated)                  |
| `tools/voice_io.py`     | SpeechRecognition + pyttsx3                      |
| `tools/creative_studio.py` | Stable Diffusion (Sovereign tier)             |
| `dynamic_ui.py`         | Streamlit UI (Claude/Codex style)                |
| `ui_theme.py`           | CSS + aura + status bar                          |
| `marketplace.py`        | Plugin store + Stripe checkout                   |
| `subscription.py`       | Free / Pro / Enterprise gating                   |
| `mts_format.py`         | `.mts` AES-GCM proprietary backup                |
| `api_bridge.py`         | FastAPI local bridge (:7331)                     |
| `metis_daemon.py`       | System-tray + Ctrl+Space + pywebview             |
| `start_metis.pyw`       | Windowless umbrella launcher                     |
| `metis.spec`            | PyInstaller single-exe config                    |
| `brains.py`             | Swappable long-term memory profiles              |
| `wallet.py`             | Orchestrator budget + policies + ledger          |
| `agent_bus.py`          | Inter-agent message bus                          |
| `agent_roster.py`       | Data-driven specialist roster (persistent)       |
| `daily_tasks.py`        | daily_briefing, brain_compact, brain_backup      |
| `providers/glm.py`      | Z.ai / Zhipu GLM-4.6 adapter                     |
| `providers/stripe_issuing.py` | Real-card adapter (opt-in)                  |

## License

Proprietary — Metis Systems 2026. Security reports welcome at `security@metis.systems`.
