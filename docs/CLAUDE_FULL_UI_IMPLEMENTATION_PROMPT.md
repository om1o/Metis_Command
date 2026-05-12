# Master prompt: implement full Metis UI from HTML (for Claude)

**Copy everything below the line into Claude.** Replace `[PASTE YOUR HTML FILE HERE]` with your exported HTML (or attach the file and write “the HTML is attached”).

---

## System / context

You are implementing the **Metis Command** product UI. The app is **Python + Streamlit** (`dynamic_ui.py`), with a centralized theme injector **`ui_theme.py`** that:

- Injects global CSS + optional JS
- Exposes: `inject(theme=...)`, `thinking_flag(active)`, `thinking_orb(...)`, `hero(...)`, `agent_card(...)`, `statusbar(...)`
- Uses design tokens as CSS variables (`--metis-bg`, `--metis-text`, `--metis-accent`, `--metis-cyan`, etc.) and themes: `obsidian`, `aurora`, `solar`
- Animates **loading / thinking** via `body.thinking` and classes like `.metis-breath`, `.metis-shimmer`, `.metis-fade-up`, and the **◆** gem in the aura when thinking is active

**Do not** replace the app with a static HTML page. **Port** the design into Streamlit: layout (columns, tabs, sidebar), components, and **all** motion (loading, hover, transitions) using CSS in `ui_theme.py` + `unsafe_allow_html` where needed.

**Repository layout (relevant):**

- `dynamic_ui.py` — main chat UI, sidebar, marketplace tab, file upload, thread rendering, `_aura_header`, status bar
- `ui_theme.py` — tokens, `inject()`, animations, `thinking_orb`, `statusbar`, etc.
- `.streamlit/config.toml` — Streamlit server config (headless, etc.)

---

## Brand + design system (apply unless HTML conflicts; HTML wins for structure, brand wins for tokens if unspecified)

- **Vibe:** Light **athletic**, **playful but professional**, **rounded** geometry  
- **Display / hero type:** **Sora 800** (large headlines)  
- **Body / UI type:** **Inter** (15–16px body, 450–500 weight; tabular numerals for metrics)  
- **Primary (actions):** athletic blue — `#2563EB` (hover `#1D4ED8`, focus ring visible)  
- **Neutrals:** bg `#F7FAFC`, surface `#FFFFFF`, alt `#F1F5F9`, border `#E2E8F0`, text `#0F172A`, muted `#475569`  
- **Radius scale:** 6 / 10 / 12 / 16 / 20 / pill (999px)  
- **Spacing:** 8pt grid; 4, 8, 12, 16, 24, 32, 40, 48, 56  
- **Shadows:** `xs` → `xl`, **no glow**; prefer borders + soft shadow  
- **Motion:** 120–180ms ease-out; card hover lift 2px; no gimmicky effects  

If the pasted HTML uses different colors, **map** them to these tokens in `ui_theme._THEMES` (add or adjust a theme) so **one** theme switch still works.

---

## Your task (step by step)

1. **Ingest the HTML** the user pastes (or attached). Parse structure: header, nav, main, chat area, side panels, modals, buttons, forms, empty states, marketplace/storefront if any.

2. **Produce a concrete plan** in comments or a short markdown section: what maps to:
   - `st.sidebar` vs main column vs `st.columns`
   - `st.tabs` (e.g. Chat / Marketplace)
   - `st.chat_message` / `st.empty()` for streaming
   - `st.file_uploader`, `st.text_input` for input row

3. **Implement in code:**
   - **`ui_theme.py`:** Extend or add theme tokens; add/merge CSS so **every** class from the HTML is represented as Streamlit-styled elements (use `[data-testid=...]` selectors if needed to target Streamlit widgets).
   - **`dynamic_ui.py`:** Rebuild layout to match the HTML: order of blocks, responsive behavior (wide layout already `layout="wide"`). Preserve **Metis** behaviors: new chat, session, persona, tools & outreach toggles, auto-write, artifacts column, update banner, developer token panel if present in repo.
   - **Loading / thinking:** Wire `thinking_flag(True/False)` around the same lifecycle as now (start before stream, clear in `finally`). Keep or improve `thinking_orb` / shimmer so the **loading state** matches the HTML’s intent.
   - **Status bar:** Keep `statusbar(...)` (or restyle) so tier / session / metrics still work.

4. **Accessibility:** Focus rings, contrast (AA) on primary buttons, `prefers-reduced-motion` to reduce nonessential animation.

5. **Deliverables:**  
   - Patches or full-file updates for `ui_theme.py` and `dynamic_user.py` (and only other files if strictly necessary)  
   - List of **CSS class → Streamlit element** mapping  
   - Note any HTML features **not** portably possible in Streamlit (e.g. custom JS); suggest minimal `components.html` only if required.

---

## User HTML (paste below)

`[PASTE YOUR HTML FILE HERE]`

---

## Acceptance checklist

- [ ] Visual layout matches the HTML: sidebar, main, optional right column, tabs  
- [ ] **Thinking / loading** animation is visible and tied to `thinking` state  
- [ ] **Hero / header** (e.g. METIS // CORE or equivalent) matches style  
- [ ] **Chips / suggestion pills** work if the HTML has them (wire to `hero()` or buttons)  
- [ ] **Theme toggle** (obsidian / light) still works or is replaced consistently  
- [ ] **No** broken imports; Streamlit run starts without errors  
- [ ] Tokens centralized; not one-off colors scattered in `dynamic_ui` except rare overrides

---

*Metis product name, version, and support links are in `metis_version.py` — keep or restyle, do not remove without replacement.*
