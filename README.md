# Pa' Bailar · Bogotá

Collects one-time dance events (socials and workshops) from the Instagram accounts of Bogotá's
dance academies and shows them on a web page with a calendar.

```
backend/    Python data collector: Instagram -> Gemini -> data/
frontend/   Astro web page that displays data/
data/       events.json + flyers/ (written by the backend, read by the frontend)
docs/       plan, design system and project documentation
```

- [docs/PLAN.md](docs/PLAN.md): architecture, deployment, Git workflow and conventions
- [docs/DESIGN.md](docs/DESIGN.md): design system (tokens, themes, components)

## Requirements

- Python 3.12 (`.python-version`)
- Node.js 24 (`.nvmrc`)

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
  spend Gemini quota on new posts.
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

## Frontend

From `frontend/`:

```bash
npm ci          # first time
npm run dev     # local preview at http://localhost:4321
npm run check   # type check + color contrast (WCAG AA)
npm run build   # static site in frontend/dist/
```

## Deployment

Live at **https://pa-bailar.github.io**. Everything runs on GitHub Actions:

| Workflow | When | What |
|---|---|---|
| `ci` | Every pull request (and started by the sweep for its data PR) | Backend lint + unit tests, frontend type check + build. The final `ci` job is the required check. |
| `daily-sweep` | Every day 6:00 AM Bogotá, or *Run workflow* | Instagram → Gemini. Only if events or flyers changed: opens a `data` PR, runs `ci` on it and auto-merges it. Every day: republishes the site with the check time. |
| `deploy` | Push to `main` touching `frontend/` or `data/`, started by the sweep, or *Run workflow* | Builds the site and publishes it to GitHub Pages |

`main` is protected by the `protect-main` ruleset with **no bypass**: changes only arrive through
squash-merged pull requests that pass `ci`; force pushes and deletion are blocked. The daily data
follows the same path. Data PRs carry the `data` label, so they're easy to filter or mute.

Secrets (Settings → Secrets and variables → Actions): `GEMINI_API_KEY`, `META_ACCESS_TOKEN`,
`IG_USER_ID`, and optionally `HEALTHCHECK_URL`.

## Contributing

`main` is what's live. Work on a branch (`feat/...`, `fix/...`), open a pull request, and use
[Conventional Commits](https://www.conventionalcommits.org/) messages. Details in
[docs/PLAN.md](docs/PLAN.md#4-git-workflow).
