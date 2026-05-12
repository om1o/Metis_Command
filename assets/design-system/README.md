# Metis AI — Design System

> Light athletic. Rounded. Playful-professional.
> Trust + reliability you can _feel_ in the UI.

---

## What is Metis?

**Metis is an agent operating system** that turns prompts into **shipped artifacts** — code, research, outreach, drafts, lead lists. Instead of "chat that disappears," Metis runs **repeatable missions**: it routes work to specialized agents, uses tools to gather real-world information, and produces concrete files. Every run is captured with **durable memory and an audit trail** so you can see what happened, reproduce results, and keep improving reliability.

It's built for **operators and builders** who want automation they can trust:

- **Prompt → mission → artifacts.** You give a goal; Metis executes steps and delivers files, docs, and structured results — not just suggestions.
- **Multi-agent workflow.** Research, planning, coding, and communication run as coordinated roles.
- **Persistent memory + traceability.** Conversations, decisions, and results are stored so the system improves and stays consistent.
- **Auto-save + cloud sync.** Outputs are first-class artifacts: written to disk, tracked, optionally mirrored to the cloud.
- **Reliability-first controls.** Guardrails, logging/debug views, deterministic artifact generation.

### Surfaces in this system

- **Metis App** — the operator workspace: chat, mission timeline, artifacts library, settings.
- **Marketing site** — outside the scope of the initial request; not built here.

### Sources provided

- `uploads/Gemini_Generated_Image_rmrdumrmrdumrmrd.png` — the Metis brandmark (M with violet→coral gradient and starburst). Saved to `assets/metis-logo-full.png` and cropped in `assets/metis-logomark.png`.
- A written brand brief (palette, type, motion, components) — codified into `colors_and_type.css` and rendered as cards in `preview/`.

> No codebase or Figma was attached. The UI kit is built from the brief alone; visuals follow the prescribed light-athletic palette and shape language. **Flagged substitutions** are documented at the bottom of this README.

---

## Content Fundamentals

**Voice:** short, warm, confident. Written like a coach who has done the rep — never like a hype-bro.

| Do                                                | Don't                              |
| ------------------------------------------------- | ---------------------------------- |
| "Saved." "Synced." "Queued." "Shipped."           | "🎉 Boom! Crushed it!"             |
| "Mission complete — 3 artifacts written."         | "Magic just happened ✨"           |
| "Couldn't connect to local brain. Start Ollama or switch off Local mode." | "Oops! Something went wrong." |
| "Run 14 finished in 1m 42s."                      | "It took a moment, but we got there!" |
| "You" (talking to the operator)                   | "We" / "let's"                     |

**Tone rules**

- **Confirmation-first.** State the outcome up top. "Saved to `~/metis/runs/2026-04-25/notes.md`."
- **Blame-free errors.** Always pair the cause with the fix. "Couldn't reach the GitHub API. Check your token in Settings → Connections."
- **Outcome-focused.** Talk about what was produced, not what the system did internally. "3 artifacts ready" beats "Agent finished orchestration."
- **Skip hype words.** No _magic, insane, crush, supercharge, blazing, unleash_.
- **No exclamation points** in product copy. Period. (Marketing can earn one occasionally.)
- **Imperatives for empty states** — motivating, action-oriented, never childish. "Start a mission" not "Looks like it's a bit empty here 👀".

**Casing**

- **Sentence case** for buttons, labels, and section titles. "Start a new mission" — not "Start A New Mission."
- **Title Case** is reserved for proper nouns and the brand name (Metis, Mission Control, Local Brain).
- **ALL CAPS** is reserved for tiny eyebrow labels (10–12px, +0.08em tracking) and **status chips** at small sizes only.

**Numbers, IDs, code**

- Every metric, cost, timestamp, token count, and ID uses **tabular numerals** + JetBrains Mono.
- Run IDs are short, monospace, copyable: `run_a91f4c`.
- Timestamps relative when fresh, absolute on hover ("2m ago" → tooltip `2026-04-25 14:32:08`).

**Emoji:** **No** in product UI. Status is communicated by colored dots, chips, and icons. (Marketing prose may use one sparingly; product surfaces never.)

**Sample copy**

> _Empty mission list:_ "No missions yet. Spin one up — we'll save every step."
> _Successful run:_ "Shipped. 4 files written to `~/metis/run_a91f4c/`."
> _Soft fail:_ "Run paused at step 3. The web tool returned 429. Retry, or edit the step."
> _Sync nudge:_ "Synced 12 minutes ago. Cloud is up to date."

---

## Visual Foundations

### Color

A **light-athletic palette**: bright surfaces, strong structure, fast feedback. The **logo's violet→coral gradient is heritage** — used for the brandmark and very rare hero moments only. Day-to-day UI runs on cool neutrals with **blue as the action color** and **green as energy** (used sparingly — it should feel earned).

| Role          | Token             | Hex      |
| ------------- | ----------------- | -------- |
| Background    | `--bg`            | `#F7FAFC` |
| Surface       | `--surface`       | `#FFFFFF` |
| Surface alt   | `--surface-alt`   | `#F1F5F9` |
| Border        | `--border`        | `#E2E8F0` |
| Text          | `--text`          | `#0F172A` |
| Text muted    | `--text-muted`    | `#475569` |
| **Primary**   | `--primary`       | `#2563EB` |
| Energy        | `--energy`        | `#22C55E` |
| Warning       | `--warning`       | `#F59E0B` |
| Error         | `--error`         | `#EF4444` |
| Heritage gradient | `--heritage-grad` | violet → coral |

### Type

Two families, one optional mono.

- **Display** — Sora (700–800). Confident, friendly, mildly geometric. H1–H4, hero numerics, big mission titles.
- **Body** — Inter (400–650). UI text, paragraphs, controls.
- **Mono** — JetBrains Mono. Code, run IDs, costs, timestamps, token counts. Always with **tabular numerals** in metrics.

Scale: 44 / 32 / 24 / 18 / 16 / 14. See `colors_and_type.css` for full token list.

### Spacing

**8pt grid.** Major rhythm: 16 / 24 / 32 / 40 / 56. Wide gutters, generous whitespace. Dense screens (tables, settings) compress to a 4pt grid where needed.

### Shape language

- **Cards** — `--radius-lg` (16px). 1px hairline border + `--shadow-md`. Hover: lift 2px and bump shadow to `--shadow-lg`.
- **Inputs/buttons** — `--radius-md` (12px).
- **Chips/badges** — `--radius-pill` (999px). Always pill-shaped.
- **Modals/sheets** — `--radius-xl` (20px) on outer corners.

### Backgrounds & imagery

- Default: clean **`--bg`** (#F7FAFC). No textures, no patterns, no gradients on regular surfaces.
- **Heritage gradient** (`violet → coral`) is reserved for: the logomark, the auth/onboarding hero, and the highest-level "Mission shipped" celebration moment. Never a button background. Never a card background.
- **Grain / noise:** none.
- **Full-bleed photography:** none in the app. (Marketing only, if/when built.)
- Empty-state illustrations use **flat geometric shapes** in `--primary-soft` + `--border` tones — never childish, never gradient-heavy.

### Borders

- Hairline `1px solid var(--border)`. Always crisp; never doubled.
- On hover for interactive surfaces: step up to `--border-strong`.
- Focus state replaces border-color with `--primary` and adds `--shadow-focus`.

### Shadows

- **Subtle, practical** — never glowy.
- `--shadow-sm` for resting controls; `--shadow-md` for cards; `--shadow-lg` for menus and floating surfaces; `--shadow-xl` for modals.
- No colored shadows. No drop-shadow filters.

### Motion

- **120–180ms ease-out** for most interactions (`--dur-base 160ms` is the default).
- **Hover:** lift 2px + shadow step.
- **Press:** down 1px + slight scale (0.99).
- **Loading:** prefer determinate progress; reserve shimmer for skeleton placeholders only.
- **Streaming text** (chat): tokens fade in over 80ms with a translateY(2px) → 0.
- **No bounces, no spring overshoot.** This is a training app, not a toy.

### Transparency & blur

- Used **only** for sheet backdrops (`rgba(15, 23, 42, 0.40)` + `backdrop-filter: blur(8px)`) and the floating composer drop shadow.
- Never on cards or chips.

### Cards (canonical)

```
background: var(--surface);
border: 1px solid var(--border);
border-radius: var(--radius-lg);
box-shadow: var(--shadow-sm);
padding: var(--space-5);

hover { box-shadow: var(--shadow-md); transform: translateY(-2px); border-color: var(--border-strong); }
```

### Layout rules

- **Max content width:** 1240px for dense pages (settings, tables); 720px for prose/chat threads.
- **Sidebar:** fixed 264px in the app shell.
- **Top app bar:** 56px, sticky, hairline border, surface background.
- **Mobile** is out of scope for v1; the system targets desktop SaaS first.

---

## Iconography

**Library:** **Lucide** (loaded via CDN). It's the closest stylistic match to the brand: 1.5px stroke, rounded line caps, geometric, friendly without being cartoony — exactly the playful-professional energy we want.

```html
<script src="https://unpkg.com/lucide@latest"></script>
<i data-lucide="sparkles"></i>
```

> **Substitution flag:** no proprietary icon set was provided. Lucide is a stand-in. If Metis has a custom icon font/sprite, drop it into `assets/icons/` and update this section.

**Usage rules**

- **Stroke 1.5px** at 20–24px display size; bump to 1.75px below 16px.
- **Color:** inherit `currentColor`. Default to `--text-muted`; promote to `--text` on hover; `--primary` for active nav.
- **Pair with text labels** in nav, buttons, and headers — icons are decorative or supportive, never the only signifier of meaning.
- **Status icons** (in chips, alerts) use the matching semantic color, not muted text.

**Brand glyph:** the **starburst** from the logomark is the only fully custom icon. It appears as the "mission ready / shipped" celebration mark and as the brand favicon. See `assets/metis-mark-starburst.svg`.

**Emoji:** never in product UI. **Unicode chars** as icons: never (use Lucide).

---

## Index

```
README.md                    ← you are here
SKILL.md                     ← Claude Skill manifest
colors_and_type.css          ← all design tokens

assets/
  metis-logo-full.png        ← logomark + wordmark (raster, on white)
  metis-logomark.png         ← cropped M (no wordmark)
  metis-wordmark.svg         ← MEMS wordmark, vector
  metis-mark-starburst.svg   ← brand glyph, single-color
  favicon.svg                ← 32×32 favicon

preview/                     ← design-system cards (registered)
  type-*.html                ← typography cards
  color-*.html               ← color cards
  spacing-*.html             ← spacing / radius / shadow cards
  component-*.html           ← buttons / inputs / cards / chips / etc.
  brand-*.html               ← logo, brand glyph

ui_kits/
  metis-app/                 ← operator workspace
    index.html               ← live click-thru: chat → mission → artifacts
    components/*.jsx         ← Button, Card, Input, Sidebar, Chat, …
    README.md
```

---

## Substitutions to verify

Things this system stood in because no source was provided. **Please review:**

1. **Fonts:** Sora + Inter + JetBrains Mono are loaded from Google Fonts. If Metis has licensed brand fonts (e.g. a custom Sora cut, or a different display family), drop the `.woff2` files into `fonts/` and update `colors_and_type.css`.
2. **Icons:** Lucide is the stand-in for a proprietary icon set. If you have one, swap it in `assets/icons/`.
3. **Logomark crop:** `assets/metis-logomark.png` is a raster crop of the supplied PNG. A vector source (SVG/PDF) would render crisper at every size.
4. **Marketing site:** not built. Brief was app-focused; if you need a marketing surface, give me a screenshot/Figma to mirror.
