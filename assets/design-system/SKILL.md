---
name: metis-design
description: Use this skill to generate well-branded interfaces and assets for Metis AI, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## Quick orientation

- **Tokens:** `colors_and_type.css` — all colors, type scale, spacing, radii, shadows, motion as CSS vars.
- **Brand assets:** `assets/` — logomark (PNG), wordmark (SVG), starburst glyph (SVG), favicon.
- **Component reference:** `preview/` — small HTML cards demonstrating each component, color, and type spec.
- **Operator app:** `ui_kits/metis-app/` — full click-thru recreation; lift `components/*.jsx` and `app.css` for production-flavored prototypes.

## Brand voice in one line

Light athletic. Rounded. Confident, never hypey. **"Saved." "Synced." "Shipped."** — never "🎉 Boom!"

## When in doubt

- Action color is **`#2563EB`** (blue). Save **`#22C55E`** (energy green) for "synced/success" moments.
- Reserve the **violet→coral heritage gradient** for the logomark, hero auth screens, and the "shipped" celebration. Never on buttons or full backgrounds.
- 8pt grid, 16px card radius, 12px button radius, pill chips. Subtle shadows — no glow.
- Sora for headings, Inter for body, JetBrains Mono with `tabular-nums` for any metric, ID, or timestamp.
- Lucide icons at 1.5px stroke, paired with text labels.
