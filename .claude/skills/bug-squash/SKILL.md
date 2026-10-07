---
name: bug-squash
description: Hunt for real bugs in Pa' Bailar, in pa-bailar (backend) or pa-bailar-web (site), on a branch, an area or a whole repository; prove each with a failing test or a reproduction, fix it, and add a guard so it can't come back. Use it when the owner asks for a bug pass or bug squashing, after a big feature, before a launch, or when something "feels off" on the live site. Style and cleanup are the code-quality skill's job.
---

# Bug squashing

The question is: **where does this break?** Read the code as an adversary: which input, order of taps, time of
day, phone, theme or failure makes it do the wrong thing. A bug counts only once it's **reproduced**; everything
else is a suspect, reported apart.

## 0. Scope

Pick one, and say which in the reply:

- **A branch** (before its PR): **the feature the change belongs to, whole**, not the changed lines. A new chip in
  the filters means checking the filters: every way to choose and clear them (the pinned bar, the sheet, the
  toolbar's pills, "Limpiar", an empty result's buttons), in every view, with search, after back and forward, after
  a reload, with the setting remembered and with storage blocked, on a phone and a wide screen. Most bugs sit where
  the new piece meets the old ones, not in the new lines (the bookmark worked; the attribute added next to it broke
  every click). Name the feature, then list its parts before reading (§0.1).
- **An area** (e.g. "Guardados", "the sweep's merges"), or a symptom the owner saw (start from the symptom: §2).
- **A whole repository** (before a launch, or periodically): split by area and give each to a subagent (`Agent`,
  `general-purpose`) with the bug classes for that area (§3) and the rule "report suspects with the exact steps or
  input; don't fix". Then reproduce each suspect yourself (§4). A handful of agents at most.

Start from what changed: `git log --oneline` since the last pass (recorded in `Code/handoff/HANDOFF.md`), to know
which features to check, then check each of those features whole.

### 0.1 Map the feature before hunting

Write down, for the feature in scope: its entry points (controls, addresses, commands, workflows), the modules and
state it reads and writes, its neighbors (what else shares that state, the DOM, history, storage, the data), and
the conditions it runs under (views, themes, widths, time of day, offline, quota left). That list is what gets
checked, one item at a time, against the bug classes below. For a site feature, the docs' sections on it
(`docs/ARCHITECTURE.md`, `docs/DESIGN.md`) are the fastest map; for a backend one, `docs/ARCHITECTURE.md`'s pipeline.

Work on a branch (`fix/<area>`), never on `main`.

## 1. Baseline

All automatic checks green first (the `code-quality` skill's step 1 lists them), so a red one later is yours.

## 2. A symptom from the owner

When the owner reports something ("saving scrolls to the top"): reproduce it first, on the live site if that's
where they saw it (Playwright through `pa-bailar/media/tools/capture.mjs` `openPhone({ now, theme })`, 375×812),
measuring the wrong value (`scrollY` before and after, the URL, the focus). Then find the cause in the code, not a
workaround for the symptom, and ask what else the cause breaks (the `data-view` on `<body>` made every bare click a
tab tap, not just the bookmark's).

## 3. Where bugs live here (look there first)

From this project's own history; each class names a past bug.

### Site

- **Delegated clicks** (`main.ts` `CONTROLS`, found with `closest()`): an ancestor or page-level element carrying a
  control's `data-*` (a `data-view` on `<body>` turned every click into "back to the top"); a click handled twice
  (the delegated listener and a module's own); a redraw replacing the element that had the focus.
- **History and back** (`screenHistory.ts`, overlays, the drawer, the search field): back leaving the site, entries
  piling up, an overlay's entry left behind, forward onto a closed overlay, a reload with an overlay marked, a page
  opened straight on `/calendario/` or `/guardados/`, Android's back hiding only the keyboard.
- **Scroll and place:** jumps after a redraw or a save, the list not coming back where it was left, the pinned bar
  covering a target, `scrollRestoration`, the calendar's day list off screen.
- **Time:** Bogotá vs the device's zone, midnight while the page is open, a night that ends after midnight, a
  multi-day event, a workshop series between sessions, "Hoy"/"Mañana" near midnight, a page left open overnight.
- **Data edges** (docs/DATA.md): a missing optional field (`bar`, `end_date`, times, flyer, price), a story-only
  event, several posts, a past event in a shared link, an empty result, one event, a very long title.
- **Phones:** 320 and 375 px overflow, the keyboard and the visual viewport (iOS's pan, Android's resize), touch
  targets under a sticky or fixed bar, landscape, the installed app.
- **Storage blocked** (private mode): every `localStorage` access through the shared helpers, in `try`.
- **Themes:** a color right in one theme only, contrast in dark (`npm run check:contrast` covers the listed pairs only).
- **Offline and updates** (`sw.js`): a page or build file not precached, an old build's files gone, the first visit.

### Backend

- **Partial failure:** a run stopped by quota, time or an error mid-account leaving state half-written (the record
  must be written last), a rerun duplicating events or resurrecting hidden ones.
- **Quotas and fallbacks:** Gemini's quota ending mid-run (Flash → Flash-Lite → the last resort), `MAX_TOKENS`, an
  unreadable answer, Instagram's usage limit, the time box.
- **Dates:** "ya pasó" at the edges, a year rollover (a December post about January), Bogotá's zone in the
  workflow's UTC, relative words ("este sábado") read on another day.
- **Merging and identity:** two posts of one event not merged, two events merged, a renamed post, an edited caption,
  a story repeated.
- **Model output:** an invented city or venue, styles guessed from nothing, several events in one post, dates the
  caption doesn't say (the safeguards in `normalize.py`).
- **Workflows:** concurrency between a sweep and an admin command, the sweep windows, a secret missing, the GitHub
  runner never assigned (cancelled with no steps: not our bug; re-run).
- **admin-web:** malformed input, the patterns drifting from Python's (`tests/fixtures/patterns.json`).

## 4. Prove it

For each suspect, in order of likely harm (what visitors see, what corrupts data, what loses the owner's work):

- Write the failing test first when the code can be reached from a unit test (fake history, fake clock, fake
  storage, a factory event: `frontend/tests/factories.ts`, `fakeHistory.ts`; backend fixtures).
- Otherwise reproduce it in the browser (a Playwright script in the scratchpad against `astro preview` or the live
  site) or with a small Python run, and note the exact steps.
- Not reproduced after a fair try: it stays a suspect (§6), with what was tried. Don't "fix" what you can't show.

## 5. Fix

- The cause, minimal, in the code's own style; one commit per bug, its message saying the symptom and the cause.
- Every fix gets a **guard**: the failing test now passing, or, for a class of bug, a test that fails if the
  pattern comes back (e.g. "no page-level `data-view`").
- Look for the same cause elsewhere (grep the pattern) and fix those too.
- Anything visible: check it in the browser at 375 px, both themes, scrolled down, a first visit, and a wide screen.

## 6. Ship and report

Ship the usual way (WORKSPACE.md): checks green, commit, `sync-docs`, push, the PR in its own command, merge only
when every check passes (sweep or workflow changes outside the sweep windows: 6:00–7:15 and 20:30–21:45 Bogotá,
the time from `node`, not `TZ=… date`), then check the live site after a deploy.

Report to the owner, short: the bugs fixed (symptom → cause → guard), the suspects not reproduced, and the risky
areas still without tests. Record the pass in `Code/handoff/HANDOFF.md` ("Last bug-squash pass: <date>, <scope>,
PR …").
