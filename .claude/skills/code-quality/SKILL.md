---
name: code-quality
description: Review Pa' Bailar's code for quality and fix what falls short, in pa-bailar (backend) or pa-bailar-web (site), on a branch, a folder or a whole repository. The bar is "pristine": current good practices, the design tokens, the shared utilities and components reused instead of copied, the house style, tests for logic. Use it when the owner asks for a quality, cleanup or good-practices pass, and before a launch. Finding bugs is the bug-squash skill's job.
---

# Code quality pass

The question is: **is this code up to standard?** Not "does it work" (that's `bug-squash`), but would a careful
senior engineer accept it: the shared tokens, utilities and components used instead of copies; one source for
each fact; types, names and comments that make it obvious; tests for the logic; nothing left over.

Fix what's worth fixing, in place, without changing what the visitor or the owner sees (unless that is the
finding). Taste alone is not a finding: the code already has a style, and matching it beats "better".

## 0. Scope

Pick one, and say which in the reply:

- **A branch** (before its PR): `git diff origin/main...HEAD` and the files it touches.
- **An area** the owner named (e.g. "the filters", "the sweep").
- **A whole repository** (a periodic pass, or before a launch): split it by area (below) and give each area to a
  subagent (`Agent`, `general-purpose`) with this skill's checklist for that repository; read their findings and
  verify each yourself (step 3). Keep it to a handful of agents.

Work on a branch (`chore/quality-<area>` or `refactor/<area>`), never on `main`.

## 1. The automatic checks first

They're the floor; a pass never ends with them red. Run them before reading anything, and again at the end.

- Site (`pa-bailar-web/frontend`): `npx vitest run`, `npm run check` (data, `astro check`, contrast, CSS custom
  properties), `npm run build`.
- Backend (`pa-bailar`): `.venv/Scripts/python -m ruff check .`, `ruff format --check .`, `mypy`, `pytest -q`,
  `node --test "admin-web/test/*.test.mjs"`; `media/`: `npx tsc --noEmit`, `node --test "tests/*.test.mjs"`.

## 2. Know what's shared before judging copies

Copies are only visible to someone who knows the originals. Before reviewing, list them:

- Site: `frontend/src/styles/tokens.css` (colors through `light-dark()`, `--space-*`, `--radius-*`, `--text-*`,
  `--icon-*`, `--duration*`, heights like `--control-height`/`--chip-height`), `scripts/lib/*.ts` (e.g. `dom.ts`
  `byId`/`escapeHtml`, `storedValue.ts`/`storedSwitch.ts`/`onceFlag.ts` for storage, `outsideClick.ts`, `sheet.ts`,
  `focus.ts`, `format.ts`, `dates.ts`, `links.ts`, `icons.ts`, `styleFamilies.ts`, `viewTitles.ts`), the components
  in `src/components/`, `docs/DESIGN.md`.
- Backend: `pa_bailar/config.py` (every constant), `text.py` (`fold`…), `normalize.py`, `models.py`, `links.py`,
  `account_options.py`, the `pipeline/` mixins, `commands/answers.py`, the patterns shared by Python and `admin-web`
  (both tested against `tests/fixtures/patterns.json`), the composite action `.github/actions/answer-issue`.

## 3. Review against the checklist

Read the code in scope with the list for its repository. For each candidate finding, **verify it** before it
counts: open the code, confirm it's real (not already handled elsewhere, not an owner decision recorded in the
docs or memory, not a deliberate exception explained in a comment). Discard what doesn't survive.

### Site (TypeScript, Astro, CSS)

- **Design tokens:** no raw colors (hex, rgb, named) outside `tokens.css`; no magic sizes where a token exists
  (spacing, radii, font sizes, icon sizes, durations, heights, z-index `--z-*`); both themes through the tokens,
  never a color only right in one. `npm run check:css` catches undefined tokens, not raw values: grep for them.
- **Reuse:** no second copy of a helper in `lib/` (escaping, `byId`, storage with `try`/`catch`, outside clicks,
  sheets, focus, dates in Bogotá, links); markup that repeats belongs in one function or component; one source for
  each fact (a view's path, a title, a label, a breakpoint: the JS and CSS copies of a media query are tested
  against each other).
- **Modules:** each file has one job, named in its header comment; views draw, `lib/` is pure where it can be (and
  tested); no module reaching into another's DOM; files and functions that grew too long split along a real seam.
- **Types:** strict; no `any`, no `as` to silence the compiler, `!` only where the comment says why it's safe;
  values read from the page checked (`isView`, `isFilterGroup`, `historyState`).
- **Events and the page:** one delegated listener per kind (`main.ts` `CONTROLS`); no page-level element carrying a
  control's `data-*` attribute; listeners not added twice on redraw; state in `AppState`, not hidden in the DOM.
- **Accessibility conventions** (`docs/DESIGN.md`): toggles `aria-pressed`, switches `role="switch"`, a dimmed or off
  control `aria-disabled` and still focusable, names starting with the visible words, focus kept after a redraw.
- **CSS:** components in `styles/components/<name>.css`, scoped by class; no `!important` without a comment; no
  rules for markup that no longer exists; phone first, the toolbar's media query reused.
- **Comments and names** in the house style: plain English, the why, owner decisions with their date; no stale
  comment describing old behavior; names that say what (no `data2`, `tmp`, `handle2`).
- **Tests:** pure logic has unit tests; a fixed bug has a guard test; no test asserting implementation details
  that would break on a harmless refactor.
- **Leftovers:** unused exports, functions, CSS classes, icons, files; commented-out code; debug logging.

### Backend (Python, workflows, admin-web, media)

- **Config:** every tunable number, time and name in `config.py`, not inline.
- **Reuse:** text folding, dates in Bogotá, links, account options and answers through their shared modules; the
  patterns shared with `admin-web` checked against `tests/fixtures/patterns.json` on both sides; no copy of a pipeline step between mixins.
- **Types and models:** mypy strict clean without `# type: ignore` (or with the reason); data through the pydantic
  models; no untyped dicts crossing modules.
- **Errors:** specific exception types (`QuotaExhaustedError`, `UnreadableAnswerError`…), never a bare `except`;
  what's swallowed is logged with why; state written last, so a failure leaves nothing half-done.
- **Complexity:** ruff's C901 limit respected by real decomposition, not by moving code into a helper named `_part2`.
- **Workflows:** least `permissions`, `concurrency` set, timeouts, actions pinned to a major version, secrets only
  through `secrets.*`, nothing printed that could hold a token; the composite action used instead of copied steps.
- **admin-web:** input validated, the CSP headers kept strict, its tests covering each route.
- **media/:** paths through the media home (`PA_BAILAR_MEDIA_HOME`), the brand's values from `brand.json`, the
  publisher still disabled unless the owner enabled it.
- **Comments, names, tests, leftovers:** as for the site.

## 4. Fix

- Rank the verified findings: what hurts most first (a copy that already drifted, a raw color wrong in one theme)
  down to small tidying. Fix the worthwhile ones; list the rest with why they wait.
- One commit per kind of fix ("refactor: one storage helper", "style: tokens for the drawer's spacing"), behavior
  unchanged, tests green after each.
- Multi-line edits with the Edit/Write tools or a script file in the scratchpad (WORKSPACE.md).
- Anything the visitor can see (CSS, markup): check it in the browser at 375 px, both themes, scrolled down, and on
  a wide screen; it must look exactly as before unless the finding was visual.
- Don't add dependencies, change copy, or redesign without asking the owner.

## 5. Ship

Run the automatic checks again (step 1), then the usual way (WORKSPACE.md): commit, `sync-docs`, push, open the PR
in its own command, merge only when every check is green (backend changes to the sweep or workflows: outside the
sweep windows, 8:30–9:45 and 20:30–21:45 Bogotá; the time from `node`, not `TZ=… date`), then check the live site
after a site deploy.

## 6. Report

Short, for the owner: what was fixed (grouped), what was found and left (and why), and the PR links. Record the pass
in `Code/handoff/HANDOFF.md` ("Last code-quality pass: <date>, <scope>, PR …") so the next one knows where to start.
