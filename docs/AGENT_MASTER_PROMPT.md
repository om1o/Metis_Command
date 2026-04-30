# Metis Command — Master agent prompt (paste into AI / Cursor)

Use the following as **system or project instructions** for any coding agent working on this repository. Update the *Current focus* and *Gaps* sections as the product evolves.

---

## Repository & remote

- **Project name:** Metis Command  
- **Git remote:** `https://github.com/om1o/Metis_Command.git` (`origin`)  
- **Version:** see `pyproject.toml` / `metis_version.py` (currently aligned with `0.16.4` family).  
- **License / distribution:** Proprietary (Metis Systems). Do not redistribute secrets, keys, or customer data.

---

## What we are building (vision)

**Metis Command** is a **local-first autonomous AI desktop**: a Claude.ai / Codex-style experience that runs a **multi-agent swarm** on top of **local Ollama** models, with an optional **cloud “Genius” brain (GLM-4.6 / Z.ai)**. Memory persists across sessions via **ChromaDB + Supabase**; skills can be **forged** and run in a **Docker sandbox**; **voice** and **computer-use** tools extend the system beyond chat.

**End state we want:** a **sovereign, policy-gated, auditable** personal AI OS on the user’s machine: five-core swarm + roster specialists, **Orchestrator Wallet** for spend caps, **Brains** (episodic / semantic / procedural) with **safe compaction**, local **FastAPI** bridge, **Streamlit** UI, optional **Tauri** desktop shell, and a **Next.js** marketing site — all testable, documented in-repo, and releasable via GitHub.

---

## What is already built (high level)

- **One-command launch:** `launch.py` + `metis.bat` — venv, deps, Ollama detection/pulls by tier, services, native window.  
- **Streamlit UI:** `dynamic_ui.py` + `ui_theme.py` — multi-column, artifacts, tool cards, slash commands, keyboard shortcuts, status bar, etc.  
- **Brains / memory:** Chroma + Supabase wiring, compaction with trash retention, `memory_loop`, `brains`, `memory_vault`.  
- **Swarm & tools:** `brain_engine.py`, `swarm_agents.py`, `crew_engine.py`, `autonomous_loop.py`, `concurrency`, roster (`identity/roster.json`), `agent_bus`, `agent_roster`.  
- **Wallet & policies:** `wallet.py` — monthly caps, categories, optional Stripe Issuing.  
- **Local API:** `api_bridge.py` on default port **7331** — bearer auth from `identity/local_auth.token`.  
- **Safety:** `safety.py` — audit, file locks, secret scan hooks.  
- **Desktop:** `scripts/desktop_shell.py` (pywebview), Tauri app under `desktop-ui/`.  
- **Marketing site:** `site/` (Vercel-oriented).  
- **CI:** `.github/workflows/ci.yml`.  
- **Tests:** `python -m pytest tests/unit`, `python -m tests.smoke`, `ruff check .` — see `README.md`.

*For file-by-file mapping, always prefer the “Files” table in `README.md`.*

---

## How it should work (operating model)

1. **User** talks to the **Genius** layer (local or GLM), which **delegates** to **Manager** → specialists (**Coder, Thinker, Scholar, Researcher, …**) and **Roster** agents.  
2. **Brains** inject context; turns persist; nightly / weekly jobs maintain durability.  
3. **Wallet** records and limits cloud and premium spend according to policy.  
4. **Autonomy** is bounded: worker limits, stream/tool timeouts, cancellable work, local-only auth on API routes.  
5. **UI** runs on Streamlit (default **8501**, may shift if port busy); **API** on **7331** unless `METIS_*_PORT` overrides.  
6. **Plugins / marketplace** and **subscription** tiers are part of the commercial surface — do not break gating or billing invariants without explicit product intent.

When you change behavior, keep **reliability guarantees** in `README.md** (locks, token auth, CORS, compaction safety) as first-class constraints unless the task explicitly revises them.

---

## What we need from the agent (non-negotiables)

- **Read before write:** open the files you touch; match naming, types, and patterns already in the tree.  
- **Minimal diffs:** solve the task; avoid drive-by refactors and unrelated file churn.  
- **Security:** never commit real API keys, `.env` secrets, or `identity/local_auth.token`; rely on `.env` templates and documented env vars.  
- **Pre-commit:** if the user has `pre-commit` installed, respect it; `ruff` and secret scan must pass for commits.  
- **Tests:** run `pytest` / smoke relevant to the change; fix regressions you introduce.  
- **Versioning & packaging:** if you bump user-visible behavior, coordinate version strings (`pyproject.toml`, `metis_version`, release notes) per existing project practice.

---

## How to debug this codebase

1. **Reproduce:** note OS (often Windows), Python **3.12+**, and whether Ollama / Docker / Supabase are required for the path under test.  
2. **Logs:** check Streamlit terminal, API bridge output, and any `artifacts/` or scheduler output mentioned in the failing feature.  
3. **Unit tests:** `python -m pytest tests/unit` — fast feedback.  
4. **Smoke:** `python -m tests.smoke` — broad import / wiring checks.  
5. **Lint:** `ruff check .` (and `ruff format` if the repo uses it consistently).  
6. **Auth for API:** `Get-Content identity\local_auth.token` (Windows) or `cat identity/local_auth.token` — use `Authorization: Bearer <token>` to `http://127.0.0.1:7331/...`.  
7. **Isolation:** for agent/stream bugs, reduce to a single model tier (`--tier Lite`) or `--skip-models` when the bug is not model-related.  
8. **Grep & docs:** `README.md` and `docs/CHANGELOG_*.md` (if present) often document intentional behavior; search before “fixing” what might be a spec.

If stuck after a few attempts: write down **observed vs expected**, **minimal repro**, and **suspect module**; then narrow (smaller function, test-only harness).

---

## Version control: commit & push to GitHub (Metis Command)

**Expectation for coding agents:** work should land in **git** on `origin` so the team always has a traceable history.

1. **Branch:** work on a feature branch unless the user says otherwise (`git checkout -b short-topic-desc`).  
2. **Granularity:** after each **complete, coherent change** (feature, bugfix, or doc that stands alone) — or at the end of a session if changes are one atomic fix — do **all** of the following:  
   - `git status` / `git diff` — review your own diff.  
   - `git add` only the files that belong to this change.  
   - `git commit -m "Clear, present-tense summary of what and why"`.  
   - `git push -u origin HEAD` (or the branch name the user is using).  
3. **Never push** broken `main` if the project uses PRs — push the branch and open a PR (e.g. `gh pr create`) when that’s the team workflow.  
4. If **pre-commit** fails, fix the issue (or fix the false positive in config) **before** pushing.  
5. If the user’s machine is **not authenticated** to GitHub, stop and report: do not embed tokens in the repo; ask the user to run `gh auth login` or configure SSH/HTTPS.

**Rationale:** “Do something” means a deliberate **commit + push** so Metis Command on **GitHub** always reflects the latest working tree for collaboration, review, and CI.

---

## Current focus & gaps (edit these lines per sprint)

*Maintainers: keep this section short and current.*

- **Current focus:** *(e.g. UI theme polish, wallet edge cases, roster reliability)*  
- **Known gaps / next:** *(e.g. tests for X, docs for Y, performance on Z)*  
- **Out of scope unless asked:** *(e.g. changing licensing, removing local-first guarantees)*

---

## Short recap for the model (one block to paste at top of a chat)

You are working on **Metis Command** — a **local-first AI desktop** (Ollama + optional GLM, Streamlit UI, FastAPI bridge, Chroma+Supabase memory, wallet, multi-agent swarm). **Remote:** `https://github.com/om1o/Metis_Command.git`. Match existing code style; run **pytest/smoke** and **ruff**; never leak secrets. **When you finish a coherent change, `git add`, `commit`, and `push` to `origin` on your branch** so the team can review and CI can run. Debug with unit tests, smoke, logs, and minimal repro. *See `docs/AGENT_MASTER_PROMPT.md` in-repo for the full spec.*

---

*This document is a living prompt — update *Current focus* and product facts as Metis Command evolves.*
