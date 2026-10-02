# Pa' Bailar design system

Two themes, one system:

| Theme | Name | Mood | Source |
|---|---|---|---|
| Light | **Fania de día** | A 1970s salsa flyer: cream offset paper, tomato red and marigold ink | New York salsa graphics (Izzy Sanabria, Fania Records), 1968–88 |
| Dark | **Noche Fania** | A dance floor at night: wine-dark, candlelit cream, gold accents | Spanish *bachata sensual* events (Korke & Judith era), 2010s–2020s |

The **structure** (type, motifs, components) comes from Fania. The **mood** of the dark theme comes from bachata sensual. Both themes share every component; only the color values change.

**Theme modes**, like macOS "Auto". The toggle in the top right cycles **Auto → Día → Noche**, and the choice is remembered:
- **Auto** (default): Fania de día from 6:00 to 17:59 and Noche Fania the rest of the day, by the visitor's clock. It switches on its own while the page is open. Bogotá is near the equator, so sunrise and sunset stay close to 6:00 and 18:00 all year.
- **Día / Noche:** always that theme.
- **Without JavaScript:** the device's light/dark setting.

## Files

```
frontend/src/styles/
├─ tokens.css            ← every design decision lives here
├─ base.css              ← element defaults, .container, shared text styles, utilities
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

Themes switch through CSS `color-scheme`: `light dark` (follow the device) when no theme is set, or forced by `html[data-theme="light" | "dark"]`. `scripts/theme.ts` sets `data-theme` (the theme in use) and `data-theme-mode` (auto/light/dark, which picks the toggle's icon). An inline copy of its logic in `BaseLayout.astro` applies the theme before first paint (no flash) and sets the `theme-color` meta for the phone's address bar.

### Semantic colors

| Token | Fania de día | Noche Fania | Use |
|---|---|---|---|
| `--bg` | cream-150 (aged offset paper) | wine-900 | Page background |
| `--surface` | cream-75 | wine-800 | Cards, dialog, buttons |
| `--surface-sunken` | cream-250 | wine-950 | Image wells, callouts |
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
- **Italic headings:** group, day and month headings in Bodoni italic, like a handwritten setlist.

The light theme's creams are the paper of 1970s salsa flyers and sleeves. The page uses the slightly darker, aged tone (`#ECDDC6`) rather than near-white, so it isn't glaring. Cards sit one step lighter so they still lift off the page.

## Upcoming list

- **Grouped by period, not by day** (`groupByPeriod` in `scripts/state.ts`). Days with one or two events share rows instead of each leaving a mostly empty row. The buckets don't overlap, follow the usual calendar "date range" grouping, and split out the weekend because that's when most socials happen:

  | Group | Range |
  |---|---|
  | Hoy | today, always first: what most visitors come for |
  | Esta semana | tomorrow … Thursday of this week (only Monday–Wednesday) |
  | Este fin de semana | Friday … Sunday of this week (Friday night counts as weekend) |
  | Próxima semana | next Monday … Sunday |
  | Más adelante en *mes* | rest of the current month |
  | *Mes* / *Mes de año* | one group per later month (year shown outside the current year) |

  Weeks run Monday to Sunday.
- **Each card says when:** "Hoy / Mañana · 8:00 p. m.", the weekday within a week ("Domingo · 6:00 p. m."), or weekday and date further away ("Martes 20 de oct"). The sticker keeps the date number.
- **Wide screens (960px+):** the group heading sits in a left column.
- **The academy on each card** is a button: it filters the list to that academy and shows "Solo eventos de @academia · Ver todas las academias" under the chips. It sits above the card's stretched click area.
- **Free events** show their price as a green "Gratis" label (WhatsApp green pair, already checked for contrast).
- **Empty results** always offer a way out: "Quitar filtros" when filters are active.
- **Dance styles** are one line of text joined by a middle dot glued to the previous word with a no-break space (`stylesLabel`), never separate elements with CSS separators. The dot stays centered between words, and a wrapped line never starts with a dot.

## Phones: feed, jump bar and filter sheet

- **Feed like Instagram:** under 720px each event is a full-width post, the flyer edge to edge at full size and the details right below, separated by a line instead of boxed cards. Nothing is shrunk into thumbnails.
- **Jump bar** (`JumpBar.astro`, `scripts/views/jumpBar.ts`):
  - **What it is:** one slim row (`--jump-bar-height`, 56px) stuck to the top, with "Filtros" and a chip per period ("Hoy · Finde · Próx. semana · Nov").
  - **Jumping:** tapping a period jumps there, and the period on screen is highlighted (scroll-spy).
  - **Hides like Instagram's header:** it hides while scrolling down and returns on any scroll up. It never hides near the top of the page, while it holds focus, or during a jump.
  - **Where it shows:** wherever the full toolbar isn't sticky (phones, short windows).
- **Filter sheet** (`FilterSheet.astro`):
  - **Opening:** "Filtros" opens the type and style chips in a sheet that slides up from the bottom, so the list stays where it was. Chips wrap, so every option is visible.
  - **Results:** "Ver N eventos" closes it. The bar's button shows how many filters are active ("Filtros · 2").
  - **One renderer:** the same chips render into the toolbar and the sheet (`[data-filter-row]`).

## Events with several posts

An event can be announced by several Instagram posts (a flyer, then a video, a reminder). It's still **one** card:
- **Card:** shows the main post's flyer (images come before videos). A `.media-count` label ("2 publicaciones") sits in the flyer's top-right corner.
- **Dialog:** `.media-tabs` above the flyer, labeled by post type (Flyer / Carrusel / Video), with the same underline style as the main view tabs. Switching tabs changes the image, the "Ver en Instagram" link and the caption.
- **Videos:** the dialog shows the video's preview frame with a "Ver video en Instagram" label (`.event-dialog__play`). Videos play on Instagram, never embedded.

## Event detail: dialog and page

- **Same markup in both** (`scripts/views/eventDetail.ts`): the home page's dialog and each event's own page (`pages/evento/[id].astro`, one static page per event).
- **The dialog has a URL:** opening it pushes `/evento/<id>/` to the address bar, so the phone's back button closes it, and a copied link opens that event's page.
- **Shared links open the event page.** Its preview (WhatsApp, Instagram) shows the flyer as a small JPEG made at build time (`pages/og/[id].jpg.ts`), and search engines get schema.org `Event` data.
- **Missing details say "Por confirmar"** in their own row (hora, lugar, precio), in muted italics. Gemini's free-text doubts are not shown; a low-confidence extraction gets one note asking to confirm in the post.
- **"Cómo llegar"** after the venue opens Google Maps (only when there's a venue or address).
- **Icons** (`scripts/lib/icons.ts`): Instagram and WhatsApp marks (Simple Icons, CC0) and drawn calendar and pin icons, inline SVG in the text color, hidden from screen readers.

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
  - Contrast meets WCAG 2.2 AA in both themes: ≥ 4.5:1 for text, ≥ 3:1 for large text and for the outlines and indicators people need to see (borders, focus ring, selected states).
  - `npm run check` runs `scripts/check-contrast.mjs`, which reads `tokens.css` and checks every pair the components use; CI fails if one drops below AA. New color pairs go in its `PAIRS` list.
  - Don't dim text with `opacity`: use `--text-muted`. Colored marks that aren't text (calendar dots) get a `--border` outline.
  - `--divider` and the stripes are decorative and exempt.
  - Motion is respected via `prefers-reduced-motion`.

## Adding something new

1. Need a new color, size or spacing? Add a token in `tokens.css` (semantic colors need both a light and a dark value).
2. Create `styles/components/<block>.css` and import it in `layouts/BaseLayout.astro`, after the other components. Don't chain CSS with `@import`: the dev server doesn't reload imported files.
3. Static markup goes in an Astro component (`src/components/<Block>.astro`); markup rendered from data goes in a view (`src/scripts/views/<block>.ts`).
4. Check both themes and a phone width (375px), and run `npm run check`, before opening the PR.
