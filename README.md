# Pa' Bailar · backend (private)

Collects one-time dance events (socials and workshops) from the Instagram accounts of Bogotá's
dance academies (Instagram → Gemini) and publishes them to the site,
[pa-bailar/pa-bailar.github.io](https://github.com/pa-bailar/pa-bailar.github.io) (public), with a
pull request twice a day. The site, its design system and the data contract (`docs/DATA.md`) live there.

```
backend/    Python collector: Instagram -> Gemini -> the site repository's data/
docs/       plan, architecture and conventions (PLAN.md)
```

Local folders: this repository in `Code\pa-bailar`, the site in `Code\pa-bailar-web` (a local
sweep writes into `..\pa-bailar-web\data`; set `DATA_DIR` to change it).

## Requirements

- Python 3.12 (`.python-version`)

## Backend

Secrets live in `backend/.env` (git-ignored, never commit it):
`GEMINI_API_KEY`, `META_ACCESS_TOKEN`, `IG_USER_ID`, `META_APP_ID`, `META_APP_SECRET`.

First-time setup (from `backend/`):

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Run the sweep:

```bash
.venv\Scripts\python run_pipeline.py            # analyze posts from the last 7 days
.venv\Scripts\python run_pipeline.py --days 14  # look further back
```

Lint and format:

```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
```

- Accounts to follow: `backend/accounts.txt` (one username per line). Add as many as you like at once:
  a new account's first sweep reads its last 30 posts (30 days), and when the free Gemini quota runs
  out the rest waits for the next day. Accounts already in their regular sweep always go first, so a
  backlog never delays today's events.
- Already-analyzed posts are remembered in `backend/state/processed_posts.json`, so re-runs only
  spend Gemini quota on new posts. On GitHub the state lives in the `sweep-state` branch (local runs
  keep their own copy in `backend/state/`, git-ignored).
- If the Instagram token stops working, paste a new one from the Graph API Explorer into `.env`
  and run `.venv\Scripts\python refresh_token.py`.

### Finding new academies among the accounts you follow

1. Download your Instagram data: Accounts Center → Your information and permissions → Download your information → "Followers and following" (HTML or JSON).
2. Put `following.html` (or `.json`) in `backend/private/`. That folder is git-ignored; your data never leaves your PC.
3. Run:

```bash
.venv\Scripts\python discover_accounts.py private\following.html
```

How it works:
- **Instagram** checks each followed account, dance-looking usernames first, 20 s apart. Personal and private accounts are skipped.
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

## Contributing

`main` is what's live. Work on a branch (`feat/...`, `fix/...`), open a pull request, and use
[Conventional Commits](https://www.conventionalcommits.org/) messages. Details in
[docs/PLAN.md](docs/PLAN.md#4-git-workflow).
