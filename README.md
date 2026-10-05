# Pa' Bailar · backend (private)

Collects one-time dance events (socials, workshops and dated workshop series, festivals, congresses,
competitions, shows and concerts for dancing) from the Instagram accounts of Bogotá's
dance academies, organizers and artists (teachers, dancers, orchestras, DJs) (Instagram → Gemini) and
publishes them to the site,
[pa-bailar/pa-bailar.github.io](https://github.com/pa-bailar/pa-bailar.github.io) (public), with a
pull request twice a day. The site, its design system and the data contract (`docs/DATA.md`) live there.

**How it all fits together, with diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).**

```
pa_bailar/            the collector (one Python package; every module in docs/ARCHITECTURE.md, Code map)
  commands/           what you run: sweep, discover, refresh_token, admin (answers.py: the admin tools' answers)
  pipeline/           the sweep: Instagram -> Gemini -> events, merged and stored; and the admin tools' add a
                      post or a story, hide a story or an event (one module each)
  instagram.py        Instagram Graph API (Business Discovery)
  public_post.py      one post from its public page, when the API can't give it (admin tools)
  stories.py          a story's event from screenshots shared to the admin page: dates, crop, account
  extraction.py       triage then extraction; prompts.py has the prompts, gemini.py the models and quotas
  merging.py, ids.py, normalize.py, clips.py, storage.py, models.py, config.py
  health.py, status.py, why.py, inbox.py, links.py, patterns.py, sweep_state.py, discovery.py, text.py, logs.py
tests/                unit and end-to-end tests (no network); fixtures/patterns.json is shared with admin-web/test
.github/              the workflows (ci, admin, daily-sweep), the answer-issue action, the admin issue form
docs/ARCHITECTURE.md  how the whole system works: services, sweep, pipeline, monitoring (start here)
docs/ADMIN.md         the admin tools: the admin page, the inbox, the commands
docs/PLAN.md          the original go-live plan, kept for its decisions
admin-web/            the admin page, a Cloudflare Worker (docs/ADMIN.md); its tests in admin-web/test;
                      .dev.vars.example: its secrets' names for local development
media/                the video toolkit for Instagram Stories and Reels: tools, a Remotion library, one folder
                      per video (media/README.md is its catalog; nothing in it runs in the sweep)
accounts.txt          the accounts to follow: academies, companies, organizers, artists
state/                local sweep state (git-ignored; on GitHub: the sweep-state branch)
.claude/              Claude Code: workspace instructions, skills, hooks (Working with Claude Code, below)
private/              your own files: Instagram export, App key, discovery results (git-ignored)
```

Local folders: this repository in `Code\pa-bailar`, the site in `Code\pa-bailar-web` (a local
sweep writes into `..\pa-bailar-web\data`; set `DATA_DIR` to change it).

## Requirements

- Python 3.12 (`.python-version`)
- Node.js (24 on CI), for the admin page's tests and the video toolkit in `media/`

## Setup

Secrets live in `.env` (repository root, git-ignored, never commit it): copy `.env.example`, which lists the keys
with what each is for (`GEMINI_API_KEY`, `META_ACCESS_TOKEN`, `IG_USER_ID`, `META_APP_ID`, `META_APP_SECRET`,
`MEDIA_GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`), and below them, commented out, the optional settings
that only change a default. `GROQ_API_KEY` and `OPENROUTER_API_KEY` are optional: they're the sweep's last resort
for extraction when Gemini runs out of quota (Groq first, then OpenRouter's free models), and without them the posts wait for
Gemini's next quota day, as before. The admin page's secrets for local development go in `admin-web/.dev.vars` (copy
`admin-web/.dev.vars.example`).

First time (from the repository root):

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Run the sweep:

```bash
.venv\Scripts\python -m pa_bailar sweep            # analyze posts from the last 7 days (accounts whose turn it is)
.venv\Scripts\python -m pa_bailar sweep --days 14  # look further back (at most 30)
.venv\Scripts\python -m pa_bailar sweep --all      # read every account now, not only those whose turn it is
.venv\Scripts\python -m pa_bailar sweep --post <link> [--account @x] [--again]  # add one post by hand (docs/ADMIN.md)
```

Lint, format, type check and tests:

```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
.venv\Scripts\python -m mypy                  # type check (strict)
.venv\Scripts\python -m pytest -q              # tests
node --test "admin-web/test/*.test.mjs"       # the admin page's tests
```

- Accounts to follow: `accounts.txt` (one username per line, by section: academies, dance companies,
  event organizers, teachers and artists, salsa bars). A bar's line says `bar` after the name, and a general bar
  or club `bar solo:salsa,bachata` (only those nights count): docs/ARCHITECTURE.md, section 6.1. Add as many as you like at once:
  a new account's first sweep reads its last 30 posts (30 days), and when the free Gemini quota runs
  out the rest waits for the next day (or, with their keys set, Groq and OpenRouter read some of it
  provisionally, docs/ARCHITECTURE.md section 7.3). Accounts already in their regular sweep always go first, so a
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
- **Instagram** checks each followed account, dance-looking usernames first, 36 s apart (about 100 an hour, half the app's quota, so the daily sweeps always have room). It pauses when Meta reports the app past 60% of its quota and stops at a rate limit; personal and private accounts are skipped.
- **Gemini Flash-Lite** classifies the business accounts with a dance hint: academy, venue, organizer, dance company, teacher (a teacher, dancer or couple), musician (an orchestra, band or DJ)… and whether they're in Bogotá.
- **The report** is written to `private/discovery_report.md`. It recommends academies, venues, organizers and companies, and teachers and musicians only when their posts announce one-time events (their own workshops, intensives, socials, shows), not just videos and regular classes.
- **Runs resume:** run it again to continue where it stopped. Each run is capped (`--max-instagram`, `--max-gemini`) so it doesn't eat the daily sweep's quota.
- **Recheck "personal" accounts** now and then with `--recheck-personal 100`: some turn out to be business accounts (they switched, or Instagram's first answer was wrong).

## Deployment

Everything runs on GitHub Actions:

| Workflow | When | What |
|---|---|---|
| `ci` | Every pull request and push to `main` | Lint, format check, types (mypy), tests and the admin page's Worker tests. Its `media` job type-checks the video toolkit and runs its Node tests, only when `media/` changes. |
| `admin` | A new issue or comment from `jzamora5` (the admin page opens such issues) | The admin inbox (only issues labelled `admin`, or texts with a request): answers with a comment (check a post, add an account, the status); adding a post (or reading one again) or a story, and hiding a story or an event, start `daily-sweep` for that one request. See [docs/ADMIN.md](docs/ADMIN.md) |
| `daily-sweep` | Every day at 9:00 AM and 9:00 PM Bogotá (started by cron-job.org, below), or *Run workflow* | Instagram → Gemini for the accounts whose turn it is (each about once a day, half per sweep), writing into a checkout of the site repository. If events or flyers changed, opens a `data` PR there as the **pa-bailar-bot** GitHub App; its `ci` runs and it merges itself, which deploys the site. Otherwise republishes the site with the check time. The sweep state is then saved to the `sweep-state` branch (if the data PR couldn't be opened, the run's posts stay unread for the next run, and `site/data` is kept as the run's artifact). With `post_url` (from `admin`), it adds that one post instead (with `again`, even if it was read before and hasn't changed) and answers on the admin issue; with `story` or `hide`, it adds a story or takes a story or an event off the site. |

`main` is **not protected**: rulesets on private repositories need a paid GitHub plan (Pro or Team).
Changes go through squash-merged pull requests and `ci` runs on every one of them by convention, but
nothing enforces it. The site repository, which is public, does enforce it (`protect-main`).

Settings → Secrets and variables → Actions:
- Secrets: `GEMINI_API_KEY`, `META_ACCESS_TOKEN`, `IG_USER_ID`, `APP_PRIVATE_KEY` (the pa-bailar-bot
  App's private key), and optionally `HEALTHCHECK_URL`, `GROQ_API_KEY` and `OPENROUTER_API_KEY` (the last
  resort when Gemini runs out: without them it's never used).
- Variables: `APP_ID` (the pa-bailar-bot App's id).

### What starts the sweep

**cron-job.org** (free) starts the two daily runs, not GitHub's own `schedule` trigger. That trigger
never fired in this repository: it's a known, undocumented problem of new private repositories, with no
fix from GitHub.

- **The jobs:** `pa-bailar sweep 9:00` and `pa-bailar sweep 21:00`, in the America/Bogota time zone.
- **What each job does:** it calls GitHub's API to run the workflow, the same as pressing *Run workflow*:
  - `POST https://api.github.com/repos/pa-bailar/backend/actions/workflows/daily-sweep.yml/dispatches`
  - body `{"ref":"main"}`
  - headers `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28` and
    `Content-Type: application/json`
  - `Authorization: Bearer <token>`
- **The token:** a fine-grained token owned by `pa-bailar`, limited to this repository and to the
  **Actions: read and write** permission. It can start or cancel runs, but can't read the code or the secrets.
- **When it fails:**
  - cron-job.org emails if a call fails, for example a `401` once the token expires.
  - healthchecks.io emails if no run arrives.
  - When the token expires, create a new one the same way and replace it in both jobs.
- **Don't add a `schedule:` trigger back.** If GitHub's scheduler started working, every run would happen
  twice. They would never overlap (the `data` concurrency group queues them), but the second one would
  spend Instagram quota for nothing.

## Monitoring the sweeps

Every run is checked by rules, without AI and without spending any quota (`pa_bailar/health.py`). It is
compared with the previous runs, kept in `run_history.json` on the `sweep-state` branch (two months).

- **Warnings** need a fix or a decision:
  - an account that couldn't be read in 3 tries in a row (each account is tried about once a day);
  - a Gemini model the key can't use, in 3 runs in a row;
  - Groq or OpenRouter refusing their key or asking for credit, in 3 runs in a row;
  - Instagram's rate limit, the time budget or post errors in 3 runs in a row;
  - a backlog of pending posts that doesn't go down over 4 runs;
  - a week of posts without a single event.
- **Notices** are worth knowing but need nothing yet:
  - one-off failures;
  - Flash's quota running out;
  - the last resort (Groq, OpenRouter) used because Gemini ran out, with what each model did;
  - accounts with no posts in 45 days.
- **Events to review** are upcoming events Gemini wasn't confident about, or whose date it doubted, events it
  couldn't place in Bogotá or another account's post called cancelled, several events of one post read only by a
  lighter model (their times and prices may be mixed up), and congresses or festivals dated on a single day (their
  other days may be missing).

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

## Dependencies

- **Direct dependencies** are listed and pinned in `requirements.in` (the sweep) and
  `requirements-dev.in` (plus the development tools).
- **The `.txt` files are generated from them** and pin every indirect dependency too, with hashes. pip
  refuses any package file that doesn't match, so a new or tampered release of a dependency's dependency
  can't slip into a run.
- **Dependabot** updates both files.
- **To change a dependency by hand**, edit the `.in` file and regenerate both `.txt` files:

```bash
.venv\Scripts\python -m pip install pip-tools
.venv\Scripts\pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url -o requirements.txt requirements.in
.venv\Scripts\pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url -o requirements-dev.txt requirements-dev.in
```

## Contributing

`main` is what's live. Work on a branch (`feat/...`, `fix/...`), open a pull request, and use
[Conventional Commits](https://www.conventionalcommits.org/) messages. Details in
[docs/PLAN.md](docs/PLAN.md#4-git-workflow).

## Working with Claude Code

Claude Code sessions start in the folder that holds both repositories (`Code`), so that's where Claude Code
looks for instructions, skills and hooks. The files themselves are versioned here, in `.claude/`:

| File | What it is |
|---|---|
| `.claude/WORKSPACE.md` | The instructions for every session: the two repositories, how changes are made, what never to touch |
| `.claude/skills/<name>/SKILL.md` | Skills: step-by-step procedures Claude follows. `sync-docs` updates the docs to match a branch before its pull request; `teaser` makes or changes a video with `media/` |
| `.claude/hooks/require-docs-sync.mjs` | Blocks opening a pull request (`gh pr create`) until `sync-docs` has run at the branch's latest commit, which it records in `.git/docs-synced` |

The `Code` folder points at them (set up once per computer):

- `Code\CLAUDE.md` contains `@pa-bailar/.claude/WORKSPACE.md`, which loads the instructions.
- `Code\.claude\skills` is a junction to this repository's `.claude\skills` (PowerShell, from `Code`):
  `New-Item -ItemType Junction -Path .claude\skills -Target pa-bailar\.claude\skills`
- `Code\.claude\settings.json` runs the hook before every Bash command:

  ```json
  {
    "hooks": {
      "PreToolUse": [
        { "matcher": "Bash", "hooks": [
          { "type": "command", "command": "node \"$CLAUDE_PROJECT_DIR/pa-bailar/.claude/hooks/require-docs-sync.mjs\"" }
        ] }
      ]
    }
  }
  ```

Skills and instructions load when a session starts: a new or changed skill shows up in the next session.
