# Pa' Bailar: Go-live implementation plan

Status: **planned, not started.** Written 2026-10-01; this replaces the earlier short version.
Goal: put the site live for **$0**, keep it updated with a **daily sweep**, and set the project
conventions (Git, CI/CD, data, security) that every later change follows.

Contents:
1. Architecture
2. Decisions
3. Repository layout and conventions
4. Git workflow
5. Data layer
6. Backend
7. Frontend
8. GitHub Actions workflows (CI, deploy, daily sweep)
9. Monitoring and alerts
10. Security
11. Free-tier budget
12. Implementation phases (checklists)
13. Runbook (day-to-day operations)
14. Future items

---

## 1. Architecture

Everything is centered on one GitHub repository. There are no servers to maintain.

```
                      ┌──────────────────────────── GitHub repository ────────────────────────────┐
                      │                                                                            │
 you ── git push ───▶ │  main branch: backend/  frontend/  data/  .github/workflows/               │
                      │                                                                            │
                      │  ┌─ ci.yml ─────────── on pull request: lint, test, build (nothing deploys)│
                      │  │                                                                         │
                      │  ├─ deploy.yml ─────── on push to main (frontend/** or data/**),           │
                      │  │                     manual button, or called by the sweep:              │
                      │  │                     build Astro → publish to GitHub Pages               │
                      │  │                                                                         │
                      │  └─ daily-sweep.yml ── every day 6:00 AM Bogotá + manual button:           │
                      │                        run backend → Instagram API → Gemini                 │
                      │                        → commit data/ → call deploy.yml                     │
                      └────────────────────────────────────────────────────────────────────────────┘
                                         │                                   │
                          Instagram Graph API (Meta)              GitHub Pages (public site)
                          Gemini API (Google)                     https://pa-bailar.github.io
```

How the layers map:

| Layer | What | Where it runs | Where it lives |
|---|---|---|---|
| Data collection (backend) | Python pipeline | GitHub Actions runner (daily), or your PC | `backend/` |
| Data (storage) | `events.json`, `meta.json`, flyers | The repo itself (git = database + backup) | `data/` |
| Backend state | Which posts were already analyzed | The repo | `backend/state/` |
| Presentation (frontend) | Static Astro site | GitHub Pages CDN | built from `frontend/` + `data/` |
| Scheduling | Cron | GitHub Actions `schedule` | `.github/workflows/` |
| Secrets | API keys and tokens | GitHub Actions secrets | never in the repo |

---

## 2. Decisions

| # | Decision | Choice | Why | Alternatives rejected |
|---|---|---|---|---|
| D1 | Scheduler | GitHub Actions cron | Runs Python, free, secrets built in, emails on failure | GitLab CI (no advantage); PythonAnywhere (new free accounts have no scheduled tasks, internet whitelist); Cloudflare Workers (JS rewrite); cron-job.org/QStash (only ping URLs) |
| D2 | Database | JSON files in the repo | No server, versioned, free, small data | Firebase (Storage needs card since Feb 2026); Supabase (pauses after 7 idle days); Sheets (extra API layer) |
| D3 | Flyer storage | WebP files in the repo | Already implemented, ~70–100 KB each, few per day | Cloudflare R2 (needs card); external CDNs |
| D4 | Hosting | **Public repo + GitHub Pages** (default) | Simplest; unlimited Actions minutes; free branch protection and secret scanning on public repos | Private repo + Cloudflare Pages (see below) |
| D5 | Data on `main` vs a separate `data` branch | **`main`** | One branch to understand; deploy reads one checkout. Bot commits are clearly prefixed so they're easy to filter in history. | `data` branch: cleaner code history but two checkouts and more moving parts. Revisit if bot commits get annoying. |
| D6 | Sweep → deploy trigger | Sweep **calls** `deploy.yml` (`workflow_call`) | Pushes made with the built-in `GITHUB_TOKEN` intentionally don't trigger other workflows, so the sweep must call deploy itself | Personal access token to re-trigger (extra secret to manage) |

**Pending user decision for D4.** Public vs private repository:
- **Public + GitHub Pages (recommended):** the code and data are visible, but the data is already public on the site and the keys stay in secrets.
- **Private + Cloudflare Pages:** the code stays private. Costs: a Cloudflare account and API token secret, 2,000 Actions min/month (a sweep is ~3–5 min, so ~150 min/month), and no free branch protection on private repos. Bonus: Cloudflare gives preview URLs for pull requests.

The rest of this plan assumes **public + GitHub Pages**. The Cloudflare differences are noted inline.

---

## 3. Repository layout and conventions

Target layout (local folder: `C:\Users\Jhoan\Code\pa-bailar`):

```
pa-bailar/
├─ .github/
│  ├─ workflows/
│  │  ├─ ci.yml               # checks on pull requests
│  │  ├─ deploy.yml           # build + publish the site
│  │  └─ daily-sweep.yml      # cron: collect events, commit, deploy
│  └─ dependabot.yml          # weekly dependency update PRs
├─ backend/
│  ├─ pabailar/               # Python package
│  │  ├─ config.py            #   paths, settings, require_env()
│  │  ├─ models.py            #   Pydantic models = the data contract
│  │  ├─ instagram.py         #   Graph API client
│  │  ├─ extraction.py        #   Gemini prompt, retries, model fallback
│  │  ├─ storage.py           #   validated read/write of data/ and state/
│  │  ├─ merging.py           #   one event, many posts: match and merge
│  │  └─ pipeline.py          #   the sweep (orchestration)
│  ├─ tests/                  # pytest tests (offline, no API calls)
│  ├─ state/processed_posts.json
│  ├─ accounts.txt
│  ├─ run_pipeline.py         # CLI: run the sweep
│  ├─ refresh_token.py        # CLI: regenerate the Instagram token
│  ├─ pyproject.toml          # ruff config
│  ├─ requirements.txt        # pinned versions
│  ├─ requirements-dev.txt    # ruff (+ pytest in Phase 2)
│  └─ .env                    # local only, git-ignored
├─ frontend/
│  ├─ src/
│  │  ├─ pages/ layouts/ components/   # Astro markup
│  │  ├─ scripts/             # typed client code: lib/, views/, state, theme, main
│  │  └─ styles/              # tokens.css, base.css, components/*.css (see DESIGN.md)
│  ├─ astro.config.mjs
│  ├─ tsconfig.json           # strict
│  ├─ package.json + package-lock.json
├─ data/
│  ├─ events.json
│  ├─ meta.json               # last run time, stats, schema version
│  └─ flyers/*.webp
├─ docs/
│  ├─ PLAN.md                 # this file
│  ├─ DATA.md                 # data schema and retention rules
│  ├─ RUNBOOK.md              # how to operate (section 13 moves here)
│  └─ DESIGN.md               # design system (after the design phase)
├─ .editorconfig
├─ .gitattributes
├─ .gitignore
├─ .nvmrc                     # Node version (24)
├─ .python-version            # Python version (3.12)
└─ README.md
```

### Backend/frontend boundaries (monorepo)
Backend and frontend share one repo but are kept independent:
- **No shared code.** Neither imports the other. They talk only through files in `data/`.
- **The contract is `data/`.** The backend is the only writer of `data/` and `backend/state/`; the frontend only reads `data/`. The schema is documented in `docs/DATA.md` and versioned with `meta.json.schema_version`.
- **Separate toolchains:** Python and `requirements.txt` in `backend/`; Node and `package.json` in `frontend/`. Each installs and builds on its own.
- **Separate pipelines by path:**
  - CI checks only the side a PR touches (section 8.1).
  - `deploy.yml` only runs for `frontend/**` or `data/**`.
  - The sweep only runs the backend.
- **Separate runtime:** the backend is never "deployed". It runs as a scheduled job, and its output is data. The frontend is deployed as a static site.
- **Commit scopes** say which side changed: `feat(backend): …`, `fix(frontend): …`, `chore(data): …`.
- **Why one repo:** a schema change updates both sides in one PR. There's one place for secrets, workflows and issues, and the frontend build reads `data/` without any cross-repo fetching.
- **When to split:** if the frontend needed live data (not daily), or someone else maintained one side, the backend could publish `data/` somewhere else (a separate repo or a release asset) and the frontend fetch it at build time. Nothing in the current layout blocks that later.

Conventions:
- **Language:** file names, code, comments, commit messages and docs in English. Text visitors see on the site is in Spanish.
- **Pinned toolchain:** Python 3.12 (`.python-version`) and Node 24 LTS (`.nvmrc`). CI reads the same files, so local and CI never drift.
- **Pinned dependencies:**
  - Python: `requirements.txt` with exact versions (`pip freeze` of the direct dependencies).
  - Node: commit `package-lock.json` and install with `npm ci`.
- **`.gitattributes`:** `* text=auto eol=lf`, plus `*.webp binary` and `*.png binary`. This avoids Windows/Linux line-ending noise in diffs.
- **`.editorconfig`:** UTF-8, LF line endings, 2 spaces for web files, 4 for Python.
- **`.gitignore`** (already present): `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, `.astro/`.

---

## 4. Git workflow

### Branches
- `main` is production: whatever is on `main` is what's live, so it must always build.
- Work happens on short-lived branches named by type:
  - `feat/<topic>` for new features (e.g. `feat/telegram-bot`)
  - `fix/<topic>` for bug fixes (e.g. `fix/carousel-flyer`)
  - `chore/<topic>` for maintenance (dependencies, config)
  - `docs/<topic>` for documentation only
  - `design/<topic>` for visual changes
- Merge through a **pull request**, even when working alone. The PR runs CI, so broken code never reaches `main`.
- Use **squash merge**: one clean commit on `main` per PR. Delete the branch after merging.

### Commits
- Use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, in the imperative, under ~72 characters.
  - `feat(frontend): add WhatsApp share button`
  - `fix(backend): pick the carousel slide that shows each event`
  - `chore(deps): bump astro to 7.4`
  - `docs: add runbook`
- The bot's data commits use `chore(data): daily sweep 2026-10-02`. They're easy to spot, and easy to hide with `git log --invert-grep --grep="chore(data)"`.
- Never commit secrets. If one ever leaks, **rotate it first** (removing it from git history isn't enough).

### Branch protection on `main`
(Free on public repos; on private repos it needs a paid plan.)
- Require a pull request before merging.
- Require the `ci` status check to pass.
- Block force pushes and deletions.
- **Allow the GitHub Actions bot to push directly**, so the daily sweep can commit data. Configure this as a ruleset bypass for "GitHub Actions" (it's the only actor allowed to skip the PR rule).

### Working on your PC alongside the bot
The bot commits to `main` every day, so always update before starting work:
```bash
git switch main
git pull --rebase
git switch -c feat/my-change
```
If a PR conflicts with `data/` changes, rebase on `main`. Data files are only written by the pipeline, so conflicts there are rare: keep `main`'s version.

### Releases
No formal versioning; `main` is continuously deployed. Optionally tag milestones (`v1.0` at go-live) for easy rollback reference.

---

## 5. Data layer

### Files

| File | Written by | Read by | Purpose |
|---|---|---|---|
| `data/events.json` | backend | frontend (build time) | List of one-time events (socials, workshops…) |
| `data/meta.json` *(new)* | backend | frontend, monitoring | `schema_version`, `generated_at`, run stats (posts analyzed, events added, errors) |
| `data/flyers/<postId>-<slide>.webp` | backend | frontend (served as static files) | Re-hosted flyer images (Instagram URLs expire) |
| `backend/state/processed_posts.json` | backend | backend | Posts already sent to Gemini, so they're never re-analyzed (saves quota) |
| `backend/accounts.txt` | you | backend | Instagram accounts to follow |

### Schema
- `docs/DATA.md` documents every field of an event: `id`, `title`, `event_type`, `styles`, `date`, `start_time`, `prices[]`, `flyer`, `source{account, post_id, permalink, published, caption}`, etc.
- The Pydantic models in `backend/pabailar/models.py` are the **source of truth**. `meta.json.schema_version` starts at `1` and goes up on breaking changes.
- The backend **validates the whole `events.json`** against the models before saving, so a bad write never gets committed.
- The frontend's TypeScript `AgendaEvent` type mirrors the schema. `astro check` in CI catches mismatches.

### Rules
- **IDs:**
  - Event: `<postId>-<index>` of the first post that announced it. It stays the same when more posts are merged in.
  - Flyer: `<postId>-<slideIndex>.webp`
  - Both are deterministic, so re-runs never duplicate.
- **The right flyer for each event:** Gemini picks the slide that shows the event (`image_index`), never a generic cover when another slide shows it. Events announced together on one image (e.g. a monthly schedule) legitimately share that image. It's saved once and both events point to it.
- **One event, many posts:** academies announce the same event several times (a flyer, then a video, a reminder). Each event stores **all** its posts in `media` (images first, then videos). It never appears twice.
  - **Matching:** Gemini receives the account's known upcoming events and returns `same_as` when a post announces one of them again, even if the wording differs. As a fallback, a rule matches on same account and date, plus the same start time (or the same title when there's no time).
  - **Merging:** the post is added to the event's `media`, and details the event was missing are filled in. Known details are never overwritten.
  - **Re-analysis:** before a post is analyzed again, its contributions are removed (`detach_post`). Events left without posts disappear.
  - Logic in `backend/pabailar/merging.py`, covered by `backend/tests/test_merging.py`.
- **Idempotency:** re-running the sweep the same day changes nothing unless Instagram has new posts.
- **Only one-time events with a date** are stored. Recurring classes are discarded at extraction.
- **Lookback window:** 7 days (`DEFAULT_LOOKBACK_DAYS`).
- **Retention (every sweep, `Sweep._apply_retention`):**
  - Events dated more than `EVENT_RETENTION_DAYS` (30) ago are deleted. Git history is the archive.
  - Their flyers are then deleted by `remove_unused_flyers`, which removes every flyer no event uses.
  - `processed_posts.json` forgets posts analyzed more than `PROCESSED_RETENTION_DAYS` (45) ago. That's longer than the 30-day first sweep and any manual `--days`, so a forgotten post is never fetched, or paid for, again.
- **Backups:** git history is the backup, and every sweep is a commit. To restore: `git revert <sweep commit>`, or `git checkout <commit> -- data/`.

### Growth estimate
- Flyers average about 90 KB. With ~40 academies, maybe 100–200 new flyers a month: **100–200 MB a year** of git history, because deleted flyers stay in history.
- GitHub recommends repos under 1 GB, and GitHub Pages sites under 1 GB. With retention on, the *live* site stays at a few MB.
- If history ever gets too large, lower `FLYER_MAX_SIZE` and `FLYER_WEBP_QUALITY`, move flyers to external storage, or start a fresh repo with history squashed.

---

## 6. Backend

### Changes needed before CI can run it
1. **Paths and config:** already relative to the repo (`pabailar/config.py`). Keys come from environment variables, so on CI they come from secrets. `load_dotenv` is harmless when there's no `.env`.
2. **Exit codes:**
   - Exit non-zero only when the run is **broken**: token invalid, every account failed, or the output can't be written. That makes GitHub mark the run red and email you.
   - A single post failing is not a failure. It's logged and retried the next day.
3. **Token health check at start:**
   - Call `/debug_token`, or do a cheap `GET /{IG_USER_ID}?fields=username`.
   - If the token is invalid, fail immediately with a clear message: "Instagram token invalid: run refresh_token.py and update the META_ACCESS_TOKEN secret". *(Done in the cleanup: `InstagramClient.check_token()` at the start of every sweep.)*
4. **Run summary:**
   - Write `data/meta.json`.
   - Also append a Markdown table to `$GITHUB_STEP_SUMMARY`, so each Actions run page shows what happened: per account, the posts seen, events added and any errors.
5. **Validation before save** (see Data layer).
6. **Pinned dependencies** in `requirements.txt`. Add `requirements-dev.txt` with `ruff` and `pytest`.
7. **Lint and format:** `ruff check` and `ruff format`. Config in `backend/pyproject.toml`.
8. **Tests (offline):** no real API calls in CI checks. Cover:
   - `instagram.image_urls()` for image, carousel and video posts
   - the recurring/undated filter in the pipeline
   - `storage.remove_unused_flyers`, `sort_events` and validation
   - one end-to-end pipeline test with mocked Instagram and Gemini responses (saved JSON fixtures)
9. **Gemini quota behavior** (already in place): pacing, retries, model fallback, and posts that fail stay unprocessed so they retry the next day. See "Gemini on the free tier" below.

### Gemini on the free tier (2026-10-02)

Free quotas as shown in AI Studio (aistudio.google.com/rate-limit). Each model has its own quota:

| Model | Per minute | Per day | Role |
|---|---|---|---|
| gemini-3.8-flash | 5 | 20 | Extraction (first choice) |
| gemini-3.5-flash | 5 | 20 | Extraction (second choice) |
| gemini-3.5-flash-lite | 15 | 500 | Triage of every post; provisional extraction when both Flash are spent |

How the sweep stays inside them (`extraction.py`, `pipeline.py`):
- **Triage first:** every new post gets a cheap yes/no from Flash-Lite (caption plus one 512px image). About half of the posts aren't events, so they never reach Flash.
- **Flash only extracts events.** If both Flash models are out, Flash-Lite extracts and the post is marked `provisional`. On a later run with Flash budget, it's re-extracted with Flash and its events are replaced.
- **Pacing per model** (60 / per-minute limit, plus 0.5 s) and **daily budgets** (limit minus 2). Usage is saved per quota day (midnight Pacific), so manual and scheduled runs share it. A model with no budget is skipped without a request.
- **Daily vs per-minute 429s:** a daily-quota error marks the model as spent; a per-minute one waits 60 s and retries.
- **Nothing is lost:** posts that can't be analyzed today stay pending and are retried on the next run.
- **Expected load with ~30 academies** (~1.3 posts per academy per week): about 6 triage and 3 extraction requests a day, with peaks of ~20 and ~10. Quotas change, so update `MODEL_LIMITS` in `config.py` when AI Studio shows different numbers.

### New accounts (first, deeper sweep)

A newly listed account is swept more deeply until all of it has been analyzed: its last `BACKFILL_POSTS` (30) posts from the last `BACKFILL_DAYS` (30) days, instead of 10 posts and 7 days. Thirty days catches monthly schedules. Progress lives in `state/accounts.json` (`backfill_done`). If the daily budget runs out midway (e.g. many accounts added at once), the account stays "new" and continues on the next run.
10. **Logging:** plain `print` is fine on Actions (it's captured in the log). Never print tokens or keys.

### Running locally (unchanged)
```bash
cd backend
.venv\Scripts\python run_pipeline.py            # last 7 days
.venv\Scripts\python run_pipeline.py --days 14
```
After a local run, commit the data like any other change, or just let the next sweep pick it up. **Avoid running locally and on CI the same day without pulling**, or you'll get data conflicts.

---

## 7. Frontend

### Changes needed for deployment
1. **Address:** the repo lives in the `pa-bailar` GitHub organization as `pa-bailar.github.io`, so GitHub Pages serves it at the root of `https://pa-bailar.github.io` (no name of a person in the URL, no base path). `site` is set in `astro.config.mjs`; asset URLs use `import.meta.env.BASE_URL`, so a base path would still work.
   - The flyer and data URLs already use `import.meta.env.BASE_URL`; verify every link and asset path.
   - Cloudflare Pages or a custom domain would use `base: "/"`.
2. **"Updated" stamp from data:** read `data/meta.json.generated_at` instead of the build time, so the page shows when the data was really refreshed.
3. **`npm ci` + `astro check`** (type checking) + `astro build` in CI.
4. **404 page** (`src/pages/404.astro`) in the site's style.
5. **Meta tags for sharing:** Open Graph title, description and image, so the link looks good when pasted into WhatsApp.
6. **Performance budget:**
   - No JS framework. The page is static HTML with one small script.
   - Flyers are lazy-loaded WebP.
   - Check with Lighthouse (in Chrome DevTools) at go-live: aim for 90+ on mobile.
7. **Design system:** separate phase (see `DESIGN.md` once chosen). It doesn't block go-live.

### Local development (unchanged)
```bash
cd frontend
npm run dev      # http://localhost:4321
npm run build    # output in frontend/dist
```

---

## 8. GitHub Actions workflows

General rules for all workflows:
- **Least privilege:** set `permissions:` per workflow, starting from `contents: read`.
- **Pin action versions** (`actions/checkout@v4`). Dependabot keeps them updated.
- **Concurrency groups** so two runs never write data or deploy at the same time.
- **Caching:** `actions/setup-python` with `cache: pip`; `actions/setup-node` with `cache: npm`.
- **Timeouts:** `timeout-minutes` on every job (sweep: 30; others: 10), so a hung run doesn't eat minutes.
- **Times:** cron runs in UTC. Bogotá is UTC−5 all year (no daylight saving), so 6:00 AM Bogotá is `0 11 * * *`.

### 8.1 `ci.yml` — checks on every pull request
Each side is only checked when its files change. A `changes` job detects which folders a PR touches.
Skipped jobs count as passed, so the single required `ci` check never blocks a PR that only touches
the other side. (Separate workflow files with `paths:` filters would leave a required check pending
forever when skipped, so we use job-level conditions instead.)

```yaml
name: ci
on:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
  pull-requests: read
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      backend: ${{ steps.filter.outputs.backend }}
      frontend: ${{ steps.filter.outputs.frontend }}
    steps:
      - uses: actions/checkout@v4
      - id: filter
        uses: dorny/paths-filter@v3
        with:
          filters: |
            backend:  ["backend/**", ".python-version"]
            frontend: ["frontend/**", "data/**", ".nvmrc"]
  backend:
    needs: changes
    if: needs.changes.outputs.backend == 'true' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version-file: .python-version, cache: pip }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check . && ruff format --check .
      - run: pytest -q
  frontend:
    needs: changes
    if: needs.changes.outputs.frontend == 'true' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version-file: .nvmrc, cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: npm ci
      - run: npx astro check
      - run: npm run build
  ci:                       # single required check: passes if every job passed or was skipped
    needs: [backend, frontend]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - run: |
          if [[ "${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}" == "true" ]]; then exit 1; fi
```
Set `ci` as a required status check on `main`.

### 8.2 `deploy.yml` — build and publish the site
Triggers:
- a push to `main` that touches `frontend/**` or `data/**` (code changes you merge)
- the manual button (`workflow_dispatch`)
- a call from the daily sweep (`workflow_call`)

```yaml
name: deploy
on:
  push:
    branches: [main]
    paths: ["frontend/**", "data/**"]
  workflow_dispatch:
  workflow_call:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with: { ref: main }          # the sweep's fresh data commit
      - uses: actions/setup-node@v4
        with: { node-version-file: .nvmrc, cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: npm ci
        working-directory: frontend
      - run: npm run build
        working-directory: frontend
      - uses: actions/upload-pages-artifact@v3
        with: { path: frontend/dist }
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: { name: github-pages, url: "${{ steps.deployment.outputs.page_url }}" }
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```
One-time setup: repo **Settings → Pages → Source: GitHub Actions**.

*Cloudflare variant:* replace the upload/deploy steps with `cloudflare/wrangler-action` (`pages deploy frontend/dist --project-name=pa-bailar`), using `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets.

### 8.3 `daily-sweep.yml` — collect events every morning
```yaml
name: daily-sweep
on:
  schedule:
    - cron: "0 11 * * *"     # 6:00 AM Bogotá
  workflow_dispatch:
    inputs:
      days: { description: "Lookback days", default: "7" }
permissions:
  contents: write            # commit data
concurrency:
  group: data
  cancel-in-progress: false
jobs:
  sweep:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    outputs:
      changed: ${{ steps.commit.outputs.changed }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version-file: .python-version, cache: pip }
      - run: pip install -r backend/requirements.txt
      - name: Run pipeline
        run: python backend/run_pipeline.py --days "${{ inputs.days || '7' }}"
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          META_ACCESS_TOKEN: ${{ secrets.META_ACCESS_TOKEN }}
          IG_USER_ID: ${{ secrets.IG_USER_ID }}
      - name: Commit data
        id: commit
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/ backend/state/
          if git diff --cached --quiet; then echo "changed=false" >> "$GITHUB_OUTPUT"; exit 0; fi
          git commit -m "chore(data): daily sweep $(date -u +%F)"
          git pull --rebase origin main
          git push
          echo "changed=true" >> "$GITHUB_OUTPUT"
  deploy:
    needs: sweep
    if: needs.sweep.outputs.changed == 'true'
    uses: ./.github/workflows/deploy.yml
    permissions: { contents: read, pages: write, id-token: write }
```
Notes:
- `git pull --rebase` before pushing handles the case where you merged something during the run.
- If nothing changed, nothing is committed and nothing is deployed, so no minutes are wasted.
- Scheduled workflows on public repos are disabled after 60 days without repo activity. The daily commits (or any push) keep them alive. If there are no events for 60 days, GitHub emails a warning first.

### 8.4 `dependabot.yml` — keep dependencies current
Weekly, grouped PRs for `pip` (`/backend`), `npm` (`/frontend`) and `github-actions` (`/`). CI runs on each PR; merge if green.

---

## 9. Monitoring and alerts (all free)

| What can go wrong | How you find out |
|---|---|
| Sweep fails (token, quota, code bug) | GitHub emails the repo owner on failed scheduled runs. The run page shows the step summary. |
| Sweep silently stops running (schedule disabled, Actions outage) | **healthchecks.io** free plan: the sweep's last step pings a URL. If no ping arrives in 26 h, it emails you. Store the ping URL as secret `HEALTHCHECK_URL`. |
| Data is stale on the site | The page shows "actualizado el …" from `meta.json`. Optionally show a warning if it's more than 2 days old. |
| Instagram token revoked | The token health check fails the run immediately with clear instructions. |
| Gemini quota exhausted | Posts stay unprocessed and retry the next day. The run summary lists them. |
| Site down | GitHub Pages status (githubstatus.com). Rare; nothing to run. |

---

## 10. Security

- **Secrets** live only in GitHub Actions secrets (repo **Settings → Secrets and variables → Actions**):

  | Secret | Used by | Notes |
  |---|---|---|
  | `GEMINI_API_KEY` | sweep | From aistudio.google.com |
  | `META_ACCESS_TOKEN` | sweep | Non-expiring Page token (from `backend/refresh_token.py`) |
  | `IG_USER_ID` | sweep | Not secret, but kept with the others for simplicity |
  | `HEALTHCHECK_URL` | sweep | Optional monitoring ping |
  | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | deploy | Only if Cloudflare Pages |

  `META_APP_SECRET` **is not uploaded**. It's only needed on your PC to regenerate the token.
- **Never** print secrets in logs. GitHub masks them, but don't rely on that.
- **Secret scanning + push protection** (free on public repos): turn on in **Settings → Code security**. It blocks pushes that contain tokens.
- **`.env` is git-ignored.** Before the first commit, verify with `git status` that `.env` doesn't appear.
- **Least-privilege workflow permissions** (section 8). Forks' pull requests don't get secrets (GitHub's default), so outsiders can't steal keys through a PR.
- **Rotation:** if a key leaks, revoke it at the provider, create a new one and update the secret. For the Meta token: generate a new one in the Graph API Explorer → run `refresh_token.py` → update the secret.
- **Content/legal:**
  - Credit every flyer with the @account and a link to the original post (already done).
  - Honor removal requests: delete the event, add its `post_id` to an ignore list, and run deploy.
  - Consider asking the main academies for an OK.

---

## 11. Free-tier budget

| Service | Free allowance | Expected use | Headroom |
|---|---|---|---|
| GitHub Actions (public repo) | Unlimited standard-runner minutes | ~5 min/day sweep + ~2 min per deploy + CI on PRs | Plenty |
| GitHub Actions (if private) | 2,000 min/month | ~150–250 min/month | ~8× |
| GitHub Pages | 1 GB site, ~100 GB/month bandwidth (soft limits) | A few MB; low traffic | Plenty |
| Repo size | Recommended < 1 GB | 50–100 MB/year of history | Years |
| Instagram Graph API | ~200 calls/hour per user | 1 call per account per day (+1 health check) | Fine up to ~150 accounts per run |
| Gemini API free tier | Per-model daily/minute quotas (shown in AI Studio) | ~5–15 calls/day | Fine; fallback models and retries |
| healthchecks.io | Free hobby plan (20 checks) | 1 check | Fine |
| Cloudflare Pages (if used) | 500 builds/month, unlimited bandwidth | ~30–60 deploys/month | Fine |

Optional and **not free**: a custom domain (e.g. `pabailar.co`, ~$10–40/year). Not needed; the free subdomain works.

---

## 12. Implementation phases

Each phase ends in a working state. Work happens on a branch → PR → merge (once the repo exists).

### Phase 0 — Prerequisites
- [x] Close VS Code and Notepad++, then rename the folder `agenda-salsera` → `pa-bailar`.
- [x] Recreate `backend/.venv` (venvs hold absolute paths) and reinstall the requirements.
- [x] Update `C:\Users\Jhoan\Code\.claude\launch.json` to the new path (config name `pa-bailar-web`).
- [x] User: create or confirm a **GitHub account** → `jzamora5`.
- [x] User: decide **public (GitHub Pages)** or **private (Cloudflare Pages)** → **public**: https://github.com/jzamora5/pa-bailar
- [x] Install the GitHub CLI (`winget install GitHub.cli`) and `gh auth login` (scopes: repo, workflow).

**Done when:** the project runs from `C:\Users\Jhoan\Code\pa-bailar`, and the account and hosting choice are known.

### Phase 1 — Repository hygiene and first commit
- [x] Add `.gitattributes`, `.editorconfig`, `.nvmrc` (24) and `.python-version` (3.12).
- [x] Pin `backend/requirements.txt`; `requirements-dev.txt` with ruff (pytest is added in Phase 2 with the tests).
- [x] Update `README.md` (what it is, layout, local setup, link to docs).
- [x] `git init -b main`; check `git status` shows **no `.env`**; first commit: `chore: initial commit`.
- [x] Create the GitHub repo `pa-bailar` and push. Commits use the noreply email `15051424+jzamora5@users.noreply.github.com`.
- [x] Turn on secret scanning + push protection and Dependabot alerts.

**Done when:** the code is on GitHub, with no secrets in it.

### Phase 2 — Backend ready for CI
- [x] Token health check at start; clear error message. *(cleanup PR)*
- [x] Exit codes: fail only on broken runs (invalid token, missing secret, every account failed). *(cleanup PR)*
- [x] Write `data/meta.json` + `$GITHUB_STEP_SUMMARY` table (per-account).
- [x] Validate `events.json` against the Pydantic models on load and save. *(cleanup PR)*
- [x] `ruff` config; fix lint issues. *(cleanup PR)*
- [x] Offline tests with fixtures, incl. an end-to-end sweep with fake Instagram/Gemini (`tests/test_sweep.py`).
- [x] `docs/DATA.md` (schema + rules).

**Done when:** `ruff check`, `pytest` and a local pipeline run all pass.

### Phase 3 — Frontend ready for hosting
- [x] `site` in `astro.config.mjs`; asset URLs verified with a base path too.
- [x] "Updated" date from `meta.json`.
- [x] `404.astro`, Open Graph meta tags (preview image = next event's flyer).
- [x] `astro check` passes.

**Done when:** `npm run build` output works at the final address.

### Phase 4 — CI
- [x] `.github/workflows/ci.yml`.
- [x] Open a test PR; both jobs are green (#3: ci passed, auto-merged).
- [x] Ruleset `protect-main` on `main`: require a squash-merged PR + the `ci` check, block force pushes and deletion, **no bypass at all** (owner's decision, 2026-10-02). The daily sweep therefore publishes data through its own auto-merged PR (see Phase 6).

**Done when:** a PR with a deliberately broken test is blocked, and a fixed one merges.

### Phase 5 — Deploy
- [x] **Settings → Pages → Source: GitHub Actions** (carried over to the `pa-bailar` org).
- [x] `.github/workflows/deploy.yml`.
- [x] Run it: first deploy on the #3 merge, then started by the sweep. **Live at https://pa-bailar.github.io (2026-10-02).**

**Done when:** the site is live at `https://pa-bailar.github.io`, with flyers loading.

### Phase 6 — Daily sweep
- [x] Add secrets `GEMINI_API_KEY`, `META_ACCESS_TOKEN` and `IG_USER_ID` (they survived the move to the org).
- [x] `.github/workflows/daily-sweep.yml`, data through PRs, and **only when events or flyers change**:
  - The sweep pushes a `data/sweep-…` branch, opens a PR labeled `data`, starts `ci` on it, and enables auto-merge (squash). After the merge it starts `deploy`.
  - Days without new events open no PR. `backend/state/processed_posts.json` survives between runs in the Actions cache and is committed with the next real change.
  - Every day the sweep starts `deploy` with `checked_at`, so "Actualizado el …" shows the time of the check.
  - The workflow token can't trigger push/PR workflows, so the sweep starts `ci` and `deploy` with `workflow_dispatch`.
  - Requires "Allow GitHub Actions to create and approve pull requests" (repo and org settings).
- [x] Run it manually with `days = 7` (2026-10-02): token OK, 5 accounts read, no new posts → no PR (as designed), deploy started with the check time, site shows "Actualizado el 2 de octubre".
- [ ] First run **with** new events: check that the `data` PR opens, `ci` passes on it, it auto-merges and the deploy follows. (Not exercised yet: there were no new posts.)
- [ ] Wait for the first scheduled run the next morning.

**Done when:** two consecutive scheduled runs succeed on their own.

### Phase 7 — Monitoring, security, maintenance
- [ ] healthchecks.io check + `HEALTHCHECK_URL` secret (ping step is ready and skips itself until the secret exists; needs a healthchecks.io account).
- [x] `.github/dependabot.yml`.
- [ ] `docs/RUNBOOK.md` (section 13).
- [ ] Optional: stale-data warning on the page.

**Done when:** pausing the workflow for a day produces a healthchecks.io email.

### Phase 8 — Go-live
- [ ] Lighthouse check on mobile (aim 90+).
- [ ] Test the WhatsApp share preview of the site link.
- [ ] Tag `v1.0`.
- [ ] Share the link with the WhatsApp groups.

### After go-live (separate plans)
- Design system (directions A/B/C; recommendation A, "Cartel popular") → `DESIGN.md` + restyle, through `design/*` branches and PRs.
- More accounts (academies, then bars).
- Telegram bot or submission form for Stories and personal accounts. This may need a small free backend (e.g. Cloudflare Worker + D1), and would get its own plan.

---

## 13. Runbook (moves to `docs/RUNBOOK.md` in Phase 7)

| Task | How |
|---|---|
| Add an Instagram account | Edit `backend/accounts.txt` in a PR (or directly on GitHub's web editor) → merge. The next sweep picks it up. To fetch it now: Actions → daily-sweep → **Run workflow**. |
| Run the sweep now | Actions → daily-sweep → **Run workflow** (optionally set `days`). |
| Redeploy without new data | Actions → deploy → **Run workflow**. |
| Fix a wrong event by hand | Edit `data/events.json` in a PR → merge → deploy runs automatically. (If the post is re-analyzed later, the edit can be overwritten. Remove the post from `processed_posts.json` only when you *want* it re-analyzed.) |
| Remove an event (e.g. the academy asks) | Delete it from `events.json` + add the post ID to an ignore list (to build in Phase 2) → merge. |
| Re-analyze a post | Remove its ID from `backend/state/processed_posts.json` and its events from `events.json` → run the sweep with enough `days`. |
| Instagram token stopped working | On your PC: Graph API Explorer → new token into `backend/.env` → `.venv\Scripts\python refresh_token.py` (from `backend/`) → copy the new `META_ACCESS_TOKEN` into the GitHub secret → run the sweep. |
| Gemini key leaked or revoked | Create a new key in AI Studio → update the `GEMINI_API_KEY` secret. |
| Roll back a bad sweep | `git revert <sweep commit>` in a PR → merge → deploy runs. |
| Scheduled runs stopped (60-day rule) | Actions → daily-sweep → **Enable workflow**. |
| Work locally | `git pull --rebase` first (the bot commits daily), then branch → PR. |

---

## 14. Future items (not part of go-live)

Known gaps from the 2026-10-01 audit (not fixed yet, by design):
- "Actualizado el …" shows the build date, not the data date. Fixed by `meta.json` in Phase 2.
- Merging a post fills in missing details but keeps the old `doubts` (e.g. "sin hora" after a video supplies the time).
- Images are sent to Gemini as JPEG without checking the actual format (Instagram serves JPEG today).
- Gemini's `same_as` linking hasn't been exercised on a real repost yet; check the first runs.
- View tabs don't support arrow-key navigation (full ARIA tabs pattern).
- Fonts load from Google Fonts. Self-hosting them would remove a third-party request.

- Pull-request preview deploys (needs Cloudflare Pages).
- Custom domain.
- Telegram bot / submission form.
- Simple privacy-friendly analytics (e.g. GoatCounter free for non-commercial use) to see if the groups use it.
