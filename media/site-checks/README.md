# Site checks

Browser checks of the public site (https://pa-bailar.github.io, the `pa-bailar-web` repository), run by Claude on this
machine to verify a change or chase a bug cheaply: real browsers, a few terse lines of output, no throwaway scripts.

**Local only, never in CI** (the owner, 6 Oct 2026): no workflow runs them (`media-ci.yml` ignores changes to this
folder; `ci.yml`, which `main` requires, checks the backend only). No dependencies of their own: they use the toolkit's
`playwright-core` (`cd media && npm ci`) with the installed Chrome (`channel: "chrome"`) and Playwright's WebKit.

## Run the scenarios

```
node media/site-checks/run.mjs [scenario…|all] [--live | --url <u>] [--engine chrome,webkit]
  [--device desktop,phone,iphone] [--size 1100x800] [--theme light,dark] [--now <iso>] [--fresh] [--shots] [--verbose]
node media/site-checks/run.mjs --help        the scenarios and what each covers
```

- **Where:** the local preview by default (http://localhost:4322/: `npm run build` in `pa-bailar-web/frontend`, then
  the `pa-bailar-web-preview` server of `Code/.claude/launch.json`); `--live` for the published site, `--url` for any.
- **Defaults:** chrome, each scenario's own devices, the light theme. Every combination asked for runs, one after the
  other.
- **Output:** one line per scenario × engine × device × theme (`OK   tour webkit/iphone/dark 19 checks`), the failed
  checks under a `FAIL` line, the parts today's data couldn't exercise as `skipped: …`. `--verbose` adds every step
  (the page's state in one line). Exit code 1 on any failure.
- **Devices:** `desktop` 1280 × 800; `phone` an Android phone at 375 × 812 (touch); `iphone` Playwright's
  "iPhone SE (3rd gen)" (375 × 667, Safari's user agent, touch). `--engine webkit --device iphone` is the closest to
  an iPhone here. `--size 1100x800` gives the device another window size (a half screen, a short laptop: the side
  panel needs 900 × 600).
- **The page:** es-CO, Bogotá's zone, the first-visit hint and the install offer already dismissed (`--fresh`
  leaves them for a first visit), every third party blocked but Google Fonts (so no analytics), the theme forced. `--now` freezes the clock (an ISO date, e.g.
  `2026-10-10T19:00:00-05:00`). Each step waits up to 8 s, each run 4 min: nothing hangs.
- **Errors:** page errors, console errors and failed same-site requests fail the run (`no page errors`).
- **Screenshots:** `--shots` saves the scenarios' screenshots in `media/out/site-checks/shots/` (git-ignored).

| Scenario | Devices | What it checks |
|---|---|---|
| `tour` | phone | A visitor's tour: first visit, scroll, the details and back (the card where it was), a carousel swipe, save → Guardados → reload, the calendar, the search, Filtros and a period's "Ver más", each with back; no horizontal overflow. Runs on any engine and device (on a desktop the bar's parts are the header's) |
| `arrows` | desktop | ↑ ↓: from nothing selected, on the list, with the details and image open; mid-page (the card focused is on screen, clear of the pinned bar); the Cuándo menu keeps its own arrows; the calendar's cards |
| `walk` | desktop | ↓ through the whole list: each period's button is reached, Enter opens it with the focus on its first new event, the walk ends on the last card, the focus never leaves the screen; back folds a period again |
| `panel` | desktop | The side panel and the image beside it: the panel follows the card clicked or focused, its buttons stay usable, → moves both, Escape, × and back close both, the list stays where it was |
| `stage` | desktop | ← → through an event's photos then the next event (← back: its last photo); from the details, every period's block opens on the way down; Escape, back, forward and a reload after a block opened that way |
| `tab` | desktop | Tab: one stop per event, in the list's reading order (like →), never a card's own button, the panel following; Enter into the panel, past its end on to the next event, Shift+Tab back, Escape; out of the page without looping. WebKit: Safari's default (links skipped) |
| `places` | desktop | Where the keys start and the page keeping its place (the fixes of site #145, #167): a click in the list's gaps, a card clicked then Escape (Safari doesn't focus it), the skip link, scrolled away from the card in focus; closing the panel after scrolling; Escape in the search, then again; Guardados and a search from deep in the list start at the top; Enter and Space on "Ver N más" with the panel open |
| `taps` | phone, iphone | A finger's taps on what changes under it (site #165): a period's button and a notice's button double-tapped open no event's details; a tap on the viewer's own edge keeps it open, one on its backdrop closes it |

The scenarios find what they need in today's data (the first card with a carousel, the first folded period…) and
skip a part, saying why, when the data has none.

## Probe: one-off debugging

```
node media/site-checks/probe.mjs [--live | --url <u>] [--engine e] [--device d] [--size WxH] [--theme t] [--now <iso>]
  [--fresh] [--path /calendario/] --do "<action>" --do "<action>" …
```

Prints the page's state after each action, then the errors. Actions: `click:<selector>`, `tap:<selector>`,
`key:ArrowDown*3`, `type:<text>`, `scroll:2000` (or `+500`/`-500`), `goto:/calendario/`, `back`, `forward`, `reload`,
`wait:500`, `eval:<js expression>` (its value printed), `shot:<name>`, `snap` (the whole state as JSON). A selector's
first match is used; `card:<n>` is the visible view's n-th card (from 0), `hit:<n>` its link. `--fresh` leaves the
first-visit flags unset.

```
node media/site-checks/probe.mjs --device iphone --engine webkit --do "tap:hit:3" --do back --do "eval:history.length"
```

The state line: `<path> y=<scroll> focus=<card:id | #id | [period: button text] | tag> drawer=<event id>
stage=<photo n/N | open> open=<other dialogs> screen=<body data-screen> folded=<periods still summarized>
OVERFLOW=<px>`; empty parts are left out.

## Add a scenario

A module in `scenarios/` exporting `{ name, summary, devices, run(ctx) }`; `run.mjs` finds it by itself.

- `ctx` has `page`, `engine`, `device`, `theme`, `touch`, `errors`; `check(label, condition, details)` (a failure
  records `details`: a string, a snapshot or a value), `skip(label, reason)`, `log(label, value)`; `snap()` and
  `step(label)` (the state, logged); `goto(path)`, `tap(locator)` (a tap on touch devices, a click otherwise),
  `key(k, n)`, `back()`, `forward()`, `settle()`, `cards()` (the visible view's cards), `shot(name)` (with `--shots`).
- `lib.mjs` also exports `VIEW` (the view on screen's selector: the other views keep their old cards, hidden),
  `focusedCardId(snapshot)` and `fmt(snapshot)` (a snapshot as one line, for a check's details).
- Throw `new Skip(reason)` (from `lib.mjs`) when the scenario doesn't apply (a desktop feature on a phone).
- Read the page through stable hooks (ids, `data-*` attributes, roles), never through text or layout that changes
  with the day's events; prefer `ctx.settle()` (waits until animations and the scroll stop) over fixed waits.
- Expectations come from the site's docs (`pa-bailar-web/docs/ARCHITECTURE.md`, §5): when a check fails, read them
  before calling it a bug, and fix the check if the site is right.

## What it can't show

WebKit here is Safari's engine, not iOS Safari: no real on-screen keyboard pushing the page, no visual viewport or
toolbar resizing, no home-screen install, no edge-swipe back, and touch is emulated (a tap, not a finger's drag).
Check those on a phone. Chrome's touch emulation is the same kind of approximation for Android.
