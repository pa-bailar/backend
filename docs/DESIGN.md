# Pa' Bailar design system

Two themes, one system:

| Theme | Name | Mood | Source |
|---|---|---|---|
| Light | **Fania de día** | A 1970s salsa flyer: cream offset paper, tomato red and marigold ink | New York salsa graphics (Izzy Sanabria, Fania Records), 1968–88 |
| Dark | **Noche Fania** | A dance floor at night: wine-dark, candlelit cream, gold accents | Spanish *bachata sensual* events (Korke & Judith era), 2010s–2020s |

The **structure** (type, motifs, components) comes from Fania. The **mood** of the dark theme comes from bachata sensual. Both themes share every component; only the color values change.

By default the theme follows the visitor's device. The toggle (top right) overrides it and is remembered.

## Files

```
frontend/src/styles/
├─ tokens.css            ← every design decision lives here
├─ base.css              ← element defaults, .container, shared text styles
├─ index.css             ← imports, in order: tokens → base → components
└─ components/           ← one file per component, named like the component
   ├─ stripes.css
   ├─ buttons.css
   ├─ tags.css
   ├─ site-header.css
   ├─ toolbar.css
   ├─ event-card.css
   ├─ calendar.css
   ├─ event-dialog.css
   └─ site-footer.css
```

## Tokens

`tokens.css` has three layers:

1. **Palette:** raw named colors (`--wine-900`, `--tomato-600`, `--marigold-400`…). **Components never use these.**
2. **Semantic colors:** what a color is *for* (`--bg`, `--surface`, `--text-muted`, `--accent`, `--action`…). Each is `light-dark(<Fania de día>, <Noche Fania>)`. **Components only use these.**
3. **Scales:** type sizes, spacing, radii, control sizes, motion.

Themes switch through CSS `color-scheme`: `light dark` (follow the device) by default, or forced by `html[data-theme="light" | "dark"]`. `scripts/theme.ts` sets the attribute; an inline script in `BaseLayout.astro` applies a saved choice before first paint (no flash).

### Semantic colors

| Token | Fania de día | Noche Fania | Use |
|---|---|---|---|
| `--bg` | cream-100 | wine-900 | Page background |
| `--surface` | cream-50 | wine-800 | Cards, dialog, buttons |
| `--surface-sunken` | cream-200 | wine-950 | Image wells, callouts |
| `--border` | wine-900 | wine-600 | Outlines of cards, chips, buttons |
| `--divider` | cream-300 | wine-600 | Lines between sections and rows |
| `--text` | wine-900 | cream-100 | Body text |
| `--text-muted` | cocoa-500 | cocoa-300 | Metadata, captions |
| `--text-italic` | wine-500 | rose-300 | Bodoni italic accents |
| `--logo` | tomato-600 | marigold-400 | The wordmark |
| `--accent` | tomato-600 | orange-400 | Event time, active tab, selected day |
| `--action` / `--on-action` | tomato / cream | marigold / wine | The single primary button |
| `--chip-active-*` | wine / cream | marigold / wine | Selected filter chip |
| `--stripe-1..3` | tomato, orange, marigold | brighter tomato, orange, marigold | 70s stripes |
| `--sticker-*` | tomato / cream | marigold / wine | Round date sticker |
| `--type-*` / `--on-type` | per event type | per event type | Type tag, calendar pills and dots |

### Typography

| Token | Font | Use |
|---|---|---|
| `--font-display` | **Shrikhand** | Wordmark, event titles, sticker day number. Echoes 70s salsa lettering without copying the Fania logo. |
| `--font-serif` | **Bodoni Moda Italic** | Tagline, day headings, month title, dialog subheadings: the sensual touch. Always italic, weight 500. |
| `--font-sans` | **Instrument Sans** | Everything else. 400 regular, 600 bold. No other weights. |

Sizes: `--text-2xs` 11 · `xs` 12 · `sm` 13 · `md` 15 (body) · `lg` 17 · `xl` 21 · `2xl` 26 · `3xl` 36 · `logo` 44–72 (fluid).

### Spacing, shape and sizes

- Spacing on a 4px base: `--space-1` 4 · `2` 8 · `3` 12 · `4` 16 · `5` 24 · `6` 32 · `7` 48.
- Corners:
  - `--radius-sm` (2px): tags, chips, buttons, like printed labels
  - `--radius-md` (4px): cards, dialog, calendar cells
  - `--radius-round`: **only** the date sticker and calendar day numbers
- `--border-width` 1.5px everywhere.
- Controls: `--control-height` 40px (buttons, toggle), `--chip-height` 32px, `--sticker-size` 60px.

## Signature motifs

- **70s stripes** (`<Stripes />`): three bands (tomato, orange, marigold). Used in the header, the event dialog and the footer. Don't use them anywhere else; they lose meaning if repeated.
- **Date sticker:** a round "record label" with the day and month, overlapping the bottom-right of each flyer.
- **Italic headings:** day and month headings in Bodoni italic, like a handwritten setlist.

## Events with several posts

An event can be announced by several Instagram posts (a flyer, then a video, a reminder). It's still **one** card:
- **Card:** shows the main post's flyer (images come before videos). A `.media-count` label ("2 publicaciones") sits in the flyer's top-right corner.
- **Dialog:** `.media-tabs` above the flyer, labeled by post type (Flyer / Carrusel / Video), with the same underline style as the main view tabs. Switching tabs changes the image, the "Ver en Instagram" link and the caption.
- **Videos:** the dialog shows the video's preview frame with a "Ver video en Instagram" label (`.event-dialog__play`). Videos play on Instagram, never embedded.

## Component rules

- **Naming:** BEM-style. `block`, `block__element`, `block--modifier`, and state classes `is-*` (`is-today`, `is-selected`, `is-past`). The CSS file is named after the block.
- **Only semantic tokens** inside component CSS. If a value is missing, add a token; never hard-code a color, size or spacing in a component.
- **One primary button per view** (`.btn--primary`). Everything else is the outlined `.btn`. WhatsApp keeps its own green (`.btn--whatsapp`) because people recognize it.
- **Event-type color** is applied with a `.t-<type>` class, which exposes `--type` for that element (tags, pills, dots).
- **No emoji in the UI.** Use text or inline SVG icons.
- **Flyers are never cropped in the dialog** (`object-fit: contain`). Cards crop to 4:5.
- **Accessibility:**
  - Every interactive element is a real `<button>` or `<a>`.
  - Visible focus ring (`--focus`).
  - Contrast ≥ 4.5:1 for text in both themes.
  - Motion is respected via `prefers-reduced-motion`.

## Adding something new

1. Need a new color, size or spacing? Add a token in `tokens.css` (semantic colors need both a light and a dark value).
2. Create `styles/components/<block>.css` and import it in `styles/index.css`.
3. Static markup goes in an Astro component (`src/components/<Block>.astro`); markup rendered from data goes in a view (`src/scripts/views/<block>.ts`).
4. Check both themes and a phone width (375px) before opening the PR.
