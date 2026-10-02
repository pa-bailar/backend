# Pa' Bailar · backend (private)

Collects one-time dance events (socials and workshops) from the Instagram accounts of Bogotá's
dance academies (Instagram → Gemini) and publishes them to the site,
[pa-bailar/pa-bailar.github.io](https://github.com/pa-bailar/pa-bailar.github.io) (public), with a
pull request twice a day. The site, its design system and the data contract (`docs/DATA.md`) live there.

```
pa_bailar/            the collector (one Python package)
  commands/           what you run: sweep, discover, refresh_token
  pipeline.py         the sweep: Instagram -> Gemini -> events, merged and stored
  instagram.py        Instagram Graph API (Business Discovery)
  extraction.py       Gemini prompts, models, quotas
  merging.py, ids.py, normalize.py, storage.py, models.py, discovery.py, config.py
tests/                unit and end-to-end tests (no network)
docs/PLAN.md          architecture, decisions and conventions
accounts.txt          the academies to follow
state/                local sweep state (git-ignored; on GitHub: the sweep-state branch)
private/              your own files: Instagram export, App key, discovery results (git-ignored)
```

Local folders: this repository in `Code\pa-bailar`, the site in `Code\pa-bailar-web` (a local
sweep writes into `..\pa-bailar-web\data`; set `DATA_DIR` to change it).

## Requirements

- Python 3.12 (`.python-version`)

## Setup

Secrets live in `.env` (repository root, git-ignored, never commit it):
`GEMINI_API_KEY`, `META_ACCESS_TOKEN`, `IG_USER_ID`, `META_APP_ID`, `META_APP_SECRET`.

First time (from the repository root):

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Run the sweep:

```bash
.venv\Scripts\python -m pa_bailar sweep            # analyze posts from the last 7 days
.venv\Scripts\python -m pa_bailar sweep --days 14  # look further back
```

Lint, format, type check and tests:

```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
.venv\Scripts\python -m mypy                  # type check (strict)
.venv\Scripts\python -m pytest -q              # tests
```

- Accounts to follow: `accounts.txt` (one username per line). Add as many as you like at once:
  a new account's first sweep reads its last 30 posts (30 days), and when the free Gemini quota runs
  out the rest waits for the next day. Accounts already in their regular sweep always go first, so a
  backlog never delays today's events.
- Already-analyzed posts are remembered in `state/processed_posts.json`, so re-runs only
  spend Gemini quota on new posts. On GitHub the state lives in the `sweep-state` branch (local runs
  keep their own copy in `state/`, git-ignored).
- If the Instagram token stops working, paste a new one from the Graph API Explorer into `.env`
  and run `.venv\Scripts\python -m pa_bailar refresh-token`.

### Finding new academies among the accounts you follow

1. Download your Instagram data: Accounts Center → Your information and permissions → Download your information → "Followers and following" (HTML or JSON).
2. Put `following.html` (or `.json`) in `private/`. That folder is git-ignored; your data never leaves your PC.
3. Run:

```bash
.venv\Scripts\python -m pa_bailar discover private\following.html
```

How it works:
- **Instagram** checks each followed account, dance-looking usernames first, 36 s apart (about 100 an hour, half the app's quota, so the daily sweeps always have room). It pauses when Meta reports the app past 60% of its hourly quota and stops at a rate limit; personal and private accounts are skipped.
- **Gemini Flash-Lite** classifies the business accounts with a dance hint: academy, venue, organizer… and whether they're in Bogotá.
- **The report** is written to `private/discovery_report.md`.
- **Runs resume:** run it again to continue where it stopped. Each run is capped (`--max-instagram`, `--max-gemini`) so it doesn't eat the daily sweep's quota.

## Deployment

Everything runs on GitHub Actions:

| Workflow | When | What |
|---|---|---|
| `ci` | Every pull request | Lint, format check and unit tests. The required check on `main`. |
| `daily-sweep` | Every day at 5:23 AM and 12:47 PM Bogotá, or *Run workflow* | Instagram → Gemini, writing into a checkout of the site repository. If events or flyers changed, opens a `data` PR there as the **pa-bailar-bot** GitHub App; its `ci` runs and it merges itself, which deploys the site. Otherwise republishes the site with the check time. The sweep state is saved to the `sweep-state` branch. |

`main` is protected by the `protect-main` ruleset with **no bypass**: changes only arrive through
squash-merged pull requests that pass `ci`; force pushes and deletion are blocked.

Settings → Secrets and variables → Actions:
- Secrets: `GEMINI_API_KEY`, `META_ACCESS_TOKEN`, `IG_USER_ID`, `APP_PRIVATE_KEY` (the pa-bailar-bot
  App's private key), and optionally `HEALTHCHECK_URL`.
- Variables: `APP_ID` (the pa-bailar-bot App's id).

## Monitoring the sweeps

Every run is checked by rules, without AI and without spending any quota (`pa_bailar/health.py`). It is
compared with the previous runs, kept in `run_history.json` on the `sweep-state` branch (two months).

- **Warnings** need a fix or a decision:
  - an account that couldn't be read in 3 runs in a row;
  - Instagram's rate limit, the time budget or post errors in 3 runs in a row;
  - a backlog of pending posts that doesn't go down over 4 runs;
  - a week of posts without a single event.
- **Notices** are worth knowing but need nothing yet:
  - one-off failures;
  - Flash's quota running out;
  - accounts with no posts in 45 days.
- **Events to review** are upcoming events Gemini wasn't confident about, or whose date it doubted.

Where to see it:
- **The run's page** on GitHub Actions has the health report at the top of its summary, warnings as
  annotations, and the per-account tables.
- **The "Sweep health" issue** (label `sweep-health`) is open only while there are warnings.
  - It always holds the latest report.
  - A comment mentioning you is added only when the warnings change, so GitHub emails you once per new
    problem, not every run.
  - It closes itself when everything is clear.
- **healthchecks.io** emails when a run fails or stops arriving. Each ping carries the report, visible in
  the check's event log.

## Contributing

`main` is what's live. Work on a branch (`feat/...`, `fix/...`), open a pull request, and use
[Conventional Commits](https://www.conventionalcommits.org/) messages. Details in
[docs/PLAN.md](docs/PLAN.md#4-git-workflow).
