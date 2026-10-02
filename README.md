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

- Accounts to follow: `backend/accounts.txt` (one username per line).
- Already-analyzed posts are remembered in `backend/state/processed_posts.json`, so re-runs only
  spend Gemini quota on new posts.
- If the Instagram token stops working, paste a new one from the Graph API Explorer into `.env`
  and run `.venv\Scripts\python refresh_token.py`.

## Frontend

From `frontend/`:

```bash
npm ci          # first time
npm run dev     # local preview at http://localhost:4321
npm run check   # type check (astro check)
npm run build   # static site in frontend/dist/
```

## Contributing

`main` is what's live. Work on a branch (`feat/...`, `fix/...`), open a pull request, and use
[Conventional Commits](https://www.conventionalcommits.org/) messages. Details in
[docs/PLAN.md](docs/PLAN.md#4-git-workflow).
