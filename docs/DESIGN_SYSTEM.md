# Reviews Dekho AI — Design System

The goal is a calm, information-first product UI: neutral surfaces, one brand colour and colour reserved for meaning (sentiment). Every token lives in `frontend/src/index.css` (`@theme`) and the chart colours are mirrored in `frontend/src/lib/theme.js`.

## Colour

| Token | Hex | Use |
|---|---|---|
| `canvas` | `#f6f6f4` | Page background (warm off-white) |
| `surface` | `#ffffff` | Panels, tables, inputs |
| `subtle` | `#f9f9f8` | Table headers, row hover |
| `line` / `line-strong` | `#e6e6e2` / `#d3d3cd` | Dividers / input and button borders |
| `ink` / `ink-2` / `ink-3` | `#1b1c1e` / `#4b4e54` / `#686c73` | Primary text / secondary text / captions (≥ 4.5:1 on white) |
| `brand-600` / `brand-700` | `#22577a` / `#1b4663` | Primary buttons, links, active nav, single-series charts |
| `brand-50` / `brand-100` | `#eef4f8` / `#dae6ef` | Active nav background, focus ring |
| `pos` (+ `pos-soft`) | `#2d7a4e` | Positive sentiment |
| `neu` (+ `neu-soft`) | `#8a8f98` | Neutral sentiment (gray midpoint) |
| `neg` (+ `neg-soft`) | `#b4321f` | Negative sentiment, errors |
| `mix` (+ `mix-soft`) | `#9a5b06` | Mixed opinions, demo-data label, warnings |

Rules:
- Sentiment colours are always paired with a text label (never colour alone). Palette checked with a colour-vision-deficiency validator: adjacent pairs pass.
- Single-series charts (ratings, keywords) use `brand-600` only, never a rainbow.
- No gradients, no glass effects.

## Typography

**IBM Plex Sans** (UI) with system fallback; numbers use `tabular-nums`.

| Role | Size / weight |
|---|---|
| Page title | 20px / 600 |
| Section (panel) title | 14px / 600 |
| Body | 14px / 400, line-height 1.5 |
| Caption, table header | 12–13px / 500, `ink-3` |
| Key figure (stat strip) | 24px / 600 |

## Spacing & shape

- 4px base unit. Common steps: 4, 8, 12, 16, 20, 24, 32.
- Page padding 16px (mobile) / 24px / 32px (desktop); content max-width 1160px.
- Panels: 1px `line` border, 8px radius, no shadow. Controls: 6px radius, 36px height.
- Shadows only on floating elements (mobile drawer, tooltips).

## Components

| Component | Behaviour |
|---|---|
| Button | `primary` (filled brand), `secondary` (white + border), `ghost`. 36px tall, visible focus ring, disabled = 50% opacity + `cursor-not-allowed`. |
| Input / Select | 36px, `line-strong` border, brand border + 3px `brand-100` ring on focus, `neg` border + message on error. Labels are always visible (no placeholder-only labels). |
| Panel | Header (title + optional description + actions) separated by a divider from the body. |
| Table | 13–14px, header row on `subtle`, row dividers, numbers right-aligned, hover row tint, horizontal scroll on narrow screens. |
| Badge | 24px tall, 6px radius. Sentiment badges have a coloured dot + label; source badges have an icon + label. |
| Alert | info / warning / error, icon + title + body, left-aligned, no dismiss unless stateful. |
| Empty state | Short explanation of why it's empty + the single next action. |
| Charts | Recharts, recessive gray grid/axes, tooltip on hover, 4px rounded bar ends, titles in the panel header, value labels in ink colours. |
| Navigation | Fixed 232px sidebar on ≥1024px; top bar + slide-in drawer below that. Active item = `brand-50` background + `brand-700` text. |

## Data honesty in the UI

Every product shows a **source badge**: *Demo data* (synthetic), *Uploaded file* or *Product link*. Generated summaries are labelled "Generated from the analysis results", and every percentage is shown next to its review count.
