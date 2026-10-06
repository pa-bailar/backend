# Pa' Bailar: context for a new session

What an AI starting a fresh session needs to work on this project without rediscovering it. It doesn't repeat the
docs: it says how the pieces fit, where each truth lives, and what bites. Durable facts only; the current state
(open work, next steps) is in the handoff (§1). Kept current by the `handoff` skill.

## 1. Read in this order

1. `WORKSPACE.md` (loaded automatically): the rules. This file (loaded too).
2. **The handoff: `Code/handoff/HANDOFF.md`**, outside both repositories, not versioned: what's in flight, what's
   next, what waits on the owner, the last review passes. Where it and this file disagree on the state, it wins.
3. Memory (`MEMORY.md`, loaded automatically): the owner's preferences and decisions, one file each.
4. Then only the docs the task needs (§2). Verify before trusting: `gh pr list` and `git worktree list` in both
   repositories; `gh run list -R pa-bailar/backend --workflow daily-sweep.yml -L 3`.

## 2. Where each truth lives

| Question | Look in |
|---|---|
| How the sweep works, models, quotas, state, health, runbook | backend `docs/ARCHITECTURE.md` (§5 sweep, §6 pipeline, §7 Gemini, §9 merging, §10 state, §14 quotas, §15 runbook, §16 code map) |
| Admin tools (issues inbox, PB Admin page, commands) | backend `docs/ADMIN.md` |
| Commands, workflows, schedule, setup, Claude Code files | backend `README.md` |
| The video toolkit | backend `media/README.md`, the `teaser` skill |
| How the site is built and runs in the browser | site `docs/ARCHITECTURE.md` (§2 data in, §3 build, §5 browser: start-up, state, drawer and URLs; §9 code map) |
| Design rules, tokens, components, owner's UI decisions | site `docs/DESIGN.md` |
| The data contract between the two | site `docs/DATA.md` (backend `pa_bailar/models.py`, site `types.ts` and `scripts/check-data.mjs` follow it) |
| Which accounts are swept, and how | backend `accounts.txt` (options in `pa_bailar/account_options.py`) |
| Every tunable number | backend `pa_bailar/config.py`; site `frontend/src/styles/tokens.css` |
| Why something is the way it is | the dated decisions in the docs, memory, then `git log`/the PRs |

## 3. The project in one paragraph

A free ($0) site of dance events in Bogotá. Two sweeps a day (9:00 and 21:00 Bogotá) read ~125 organizers' Instagram
posts, Gemini extracts the events, and the site rebuilds. Owner: jzamora5. Two repositories in `C:\Users\Jhoan\Code`:

| Piece | Where |
|---|---|
| Backend (public) | `pa-bailar` → `pa-bailar/backend`. Python 3.12, `python -m pa_bailar sweep\|discover\|admin\|refresh-token` (`.venv/Scripts/python`) |
| Site (public) | `pa-bailar-web` → `pa-bailar/pa-bailar.github.io`. Astro + vanilla TypeScript in `frontend/`, the data in `data/`. https://pa-bailar.github.io (`/`, `/calendario/`, `/guardados/`, `/evento/<id>/`) |
| Images (public) | `pa-bailar/media`, cloned locally as `Code/pa-bailar-images`: the flyers, clips and the archive's small flyers. The site repository ignores `data/flyers/` and `data/previews/` (backend ARCHITECTURE §10.2) |
| PB Admin | Cloudflare Worker from backend `admin-web/`, https://pa-bailar-admin.jzamorac-9.workers.dev (deploys on every push to the backend's `main`) |
| Video toolkit | backend `media/` (Remotion + Python tools); renders go to the media home `D:\AI\pa-bailar-media` |

## 4. How the pieces connect

- **An event's life:** cron-job.org starts `daily-sweep.yml` → `sweep` picks whose turn it is (`accounts.txt`, the
  quiet and dormant tiers) → Instagram Graph API (Business Discovery) → Flash-Lite triage → Flash extraction (the
  `ModelPool`; Lite, then Groq/OpenRouter as the last resort, all provisional) → `normalize.py` safeguards →
  merging into events (`merging.py`, `ids.py`; stored duplicates repaired on every load) → state on the
  `sweep-state` branch; images pushed to `pa-bailar/media` (`media_store.py`), then the data written to the site
  repo through a data PR that merges itself → the site's `deploy.yml` copies the images in, builds and publishes.
  Events 60 days past are archived (`data/archive/<year>.json`), not deleted.
- **The owner's hand:** PB Admin (a share target on the phone) or a GitHub issue → `admin.yml` → `pa_bailar admin`
  (no AI except reading a post or a story) → the bot's answer on the issue. Events can be added from a post or a
  story screenshot, hidden (`/ocultar`, with undo links), or re-read.
- **On the site:** one page with three views (`main.ts` owns `AppState` and `render()`); the events are JSON
  embedded at build time; `lib/` holds the pure logic (filter model, dates in Bogotá, search, links), `views/` draws.
  A service worker makes it installable and offline.
- **Health:** each sweep writes `status.json` (PB Admin's dashboard), pings healthchecks.io, and opens or updates a
  "Sweep health" issue when a rule fails (backend ARCHITECTURE §11).

## 5. Implementation essentials (what bites)

### Site

- **Clicks are delegated:** one listener in `main.ts` (`CONTROLS`, matched with `closest()`). No page-level element
  may carry a control's `data-*`: the view is marked on `<body>` as `data-screen`, never `data-view` (that made every
  click a tap on the current tab; a guard test checks it).
- **History:** `screenHistory.ts` gives screens (a period opened whole, the calendar, Guardados) and overlays (sheets,
  the details, menus, the search field) their own entries; back must never leave the site unexpectedly. Every change
  to navigation needs back, forward, reload and "opened straight on that address" checked.
- **The filter model is pure** (`lib/filterModel.ts`, `state.ts` `matchesFilters`): every path that shows events goes
  through it. Guardados ignores the filters; the search applies everywhere.
- **Bogotá time** everywhere (`lib/dates.ts`), never the device's zone; events past midnight end at their end time.
- **Design tokens only** (`tokens.css`, colors through `light-dark()` for the two themes); shared helpers in `lib/`
  (storage through `storedValue`/`storedSwitch`/`onceFlag`, never bare `localStorage`).
- **Checks:** `npx vitest run`, `npm run check` (data, `astro check`, contrast, CSS tokens), `npm run build`.

### Backend

- **Tunables in `config.py`;** the pipeline is a package of mixins (`pipeline/`); answers to the owner in
  `commands/answers.py`; prompts in `prompts.py`. State is written last so a stopped run leaves nothing half-done.
- **Quota is the real constraint:** Gemini's free tier and Instagram's usage. **Each Gemini model has its own daily
  quota**, so each role takes several (`config.py`: `LITE_MODELS`, `EXTRACTION_MODELS`, `PROVISIONAL_MODELS`); the
  real limits and today's use per model are on AI Studio's rate-limit page (the owner can paste it; our own counter
  can differ: Google counts failed requests). The model ids: list them with the API (`client.models.list()`), not
  from memory. Reads by a lighter model are provisional and re-read with Flash later, the soonest events first; a
  sweep leaves the day's later sweep half of Flash. Flash often answers 503 "overloaded" for hours (Google's
  capacity, not shown on its status page): the pool pauses a busy model instead of retrying.
- **`accounts.txt` options:** `bar` (only special nights, `bar: true`), `solo:<styles>` (a focus filter); silent
  accounts commented out with why.
- **The admin bot is not AI:** fixed patterns (shared with `admin-web` through `tests/fixtures/patterns.json`).
- **Checks:** `ruff check .`, `ruff format --check .`, `mypy`, `pytest -q`, `node --test "admin-web/test/*.test.mjs"`.

## 6. This machine (Windows) and the tools

- **Bogotá time in a shell: use `node`**
  (`node -e "console.log(new Date().toLocaleTimeString('en-GB',{timeZone:'America/Bogota'}))"`). Git Bash ignores
  `TZ=America/Bogota` and prints UTC.
- **Multi-line edits:** the Edit/Write tools or a Python script in the scratchpad; heredocs with regexes or
  backslashes get mangled (one turned `\b` into a control character).
- **`gh` with a `/word` argument** (`/agregar`): `MSYS_NO_PATHCONV=1`, or Git Bash turns it into a Windows path.
- **`gh pr create` runs in its own command** (the docs-sync hook reads the command; chained after a commit it blocks).
- **Parallel shell commands share one working directory:** a `cd` in one can land another in the wrong repository
  (a PR got the other repository's description). Name the target explicitly: `gh … -R pa-bailar/<repo>`,
  `git -C <path>`.
- **Worktrees** for parallel agents. A site or media worktree has a `node_modules` junction: `cmd //c rmdir` it
  BEFORE `git worktree remove`, or the real folder goes with it.
- **Browser checks:** first `pa-bailar/media/site-checks/` (its README): `run.mjs` runs the scenarios (`tour`,
  `arrows`, `walk`, `panel`, `stage`, `tab`) on chrome or webkit, desktop, phone or iPhone, both themes, against the local
  preview or `--live`, printing only failures; `probe.mjs --do "tap:…" --do back …` prints the page's state after
  each action, for one-off debugging. Add a scenario there instead of a throwaway script. Local only, never in CI
  (the owner, 6 Oct 2026). For videos, `media/tools/capture.mjs` (`openPhone({ now, theme })`). Preview servers through `Code/.claude/launch.json` and the
  `preview_start` tool, not Bash. `astro preview` refuses a second instance ("already running": reuse its port).
- **GitHub Actions:** a job cancelled after ~15 min with no steps run is GitHub not assigning a runner (incidents
  happen), not a failure of ours: re-run it. Both repositories are public (the backend since 6 Oct 2026): Actions
  minutes are free. A ruleset on `main` requires `ci`, so `ci.yml` has no path filter (a skipped required check
  leaves a PR unmergeable). Public means every push is public: never a key in a commit.
- **WebKit (Safari's engine) in Playwright** is installed with the toolkit: use it for Safari checks. It isn't iOS
  (no real keyboard, toolbar or home-screen app). A screenshot injects a style the site's CSP refuses: those console
  errors are the test's, not the site's.

## 7. Working agreements and lessons

The rules are in `WORKSPACE.md`; these are the lessons behind them.

- **Merge only when every check reports pass** (not "mergeable": two PRs were merged early). Changes to the sweep path
  or workflows only outside the sweep windows (8:30–9:45 and 20:30–21:45 Bogotá).
- **Verify before claiming:** an unconfirmed "free Flash ends 20 Oct" came from news about the Gemini app, not the
  API. Say what was checked and what wasn't.
- **Test like a visitor:** 375 px, both themes, scrolled down, a first visit, back and reload; the live site after
  a deploy. A feature is checked whole (its neighbors too), not just its new lines.
- **The owner directs, Claude orchestrates:** ask only for direction, money, accounts or keys; decide the rest with
  sensible defaults and report what shipped (memory: `minimize-review-requests`).
- **Skills:** `sync-docs` (every PR; docs are architecture and decisions, not pixels), `bug-squash`,
  `code-quality`, `handoff`, `teaser`. When each runs: `WORKSPACE.md`, "Review process".
