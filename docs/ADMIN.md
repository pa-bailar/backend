# Pa' Bailar admin tools

Tools for running Pa' Bailar day to day: see how the sweeps and quotas are doing, find out why an event isn't
on the site, add one by hand, fix a wrong detail. **Work in progress:** this page grows with each step.

| Step | What | State |
|---|---|---|
| Admin page | Sign in with GitHub, the status dashboard | Done (needs the one-time setup below) |
| 1. Status | `admin status`: sweeps, Gemini and Instagram usage, accounts, events | Done |
| 2. Events | `admin why`, `admin add-post`, `admin add-account`, and the issues inbox | Planned |
| 3. Admin page tools | Check or add a post from a link, on the page | Planned |
| 4. Corrections | `corrections.json` and `admin fix`, fed by the site's report form | Planned |

None of these tools is AI: they are fixed checks over what the sweep records. Only adding a post sends it
to Gemini (one request).

## `admin status`: how it's doing

```bash
.venv\Scripts\python -m pa_bailar admin status
```

From the repository root, on your computer (it reads `.env` for the Instagram check). It shows, in Spanish:

- **Barridos:** the latest sweeps (✅ or ⚠️ with what went wrong: Instagram's limit, time, accounts that
  couldn't be read, errors), with a link to each run, and the next two.
- **Gemini hoy:** requests per model against its daily budget, and when the quota resets.
- **Instagram:** whether the token works, and how much of the app's hourly quota is used (one call;
  `--no-instagram` skips it).
- **Cuentas y eventos:** accounts swept, those still in their first (deeper) sweep, posts analyzed,
  provisional events waiting for Flash, upcoming events on the site, discovery progress.

`--json` gives the same as data. After every sweep, the workflow saves it as `status.json` on the
`sweep-state` branch: that's what the admin page shows. The sweeps' state comes from the
`sweep-state` branch, fetched each time, so it's current even if you haven't run anything locally.

## The admin page

- **Where:** https://pa-bailar-admin.jzamorac-9.workers.dev, the Cloudflare Worker `pa-bailar-admin` (free).
  Cloudflare deploys it from this repository's `admin-web/` folder on every push to `main`.
- **What it shows:** the latest sweeps (with links to their runs), Gemini usage per model, the Instagram
  token, accounts and events: the latest `status.json`, as of the last sweep.
- **Files:**
  - `admin-web/wrangler.jsonc`: the Worker's settings. Its `name` must match the Worker's name in Cloudflare.
  - `admin-web/public/`: the page, served as it is.
  - `admin-web/public/`: the page (`index.html`, `app.js`, `admin.css`), with no data in it.
  - `admin-web/src/index.js`: the server side: `/auth/login`, `/auth/callback`, `/auth/logout`,
    `/api/health`, `/api/me`, `/api/status`.
- **Sign-in:** "Iniciar sesión con GitHub", through the `pa-bailar-admin` GitHub App. Only `jzamora5`
  (`ALLOWED_USER` in `wrangler.jsonc`) gets in. The session is a cookie holding the GitHub token, encrypted
  with `SESSION_SECRET`; it lasts 30 days and renews the 8-hour GitHub token by itself. Nothing to paste or
  renew. The page reads the status with your own GitHub access, limited to what the App may do: read the
  backend repository, open issues, see runs.

### Cloudflare setup (done once)

1. Cloudflare dashboard → **Workers & Pages** → **Create** → import a repository from GitHub.
2. Connect GitHub: allow Cloudflare's app on the `pa-bailar` organization, **only the `backend` repository**.
3. Choose `pa-bailar/backend`, then:
   - **Project name:** `pa-bailar-admin` (the same as `name` in `wrangler.jsonc`)
   - **Build command:** empty
   - **Deploy command:** `npx wrangler deploy`
   - **Enable preview builds:** off, so only `main` is published
   - **Protect with Cloudflare Access:** off (the page will have its own sign-in with GitHub)
   - **Advanced settings → path:** `/admin-web`
   - **API token:** let Cloudflare create one (it's for Cloudflare's own build, kept inside Cloudflare)
4. **Deploy.** The page says "Servidor: listo ✓" when the server side works.

### Sign-in setup (done once)

1. **The GitHub App:** pa-bailar organization → **Settings** → **Developer settings** → **GitHub Apps** →
   **New GitHub App**:
   - **Name:** `pa-bailar-admin`; **Homepage URL:** the page's address
   - **Redirect URI** (under "Identifying and authorizing users"):
     `https://pa-bailar-admin.jzamorac-9.workers.dev/auth/callback`, without wildcard matching
   - **Expire user authorization tokens:** on. Request user authorization during installation and Device
     Flow: off. Setup URL: empty
   - **Webhook → Active:** off
   - **Repository permissions:** Contents: Read-only · Issues: Read and write · Actions: Read-only
   - **Where can it be installed:** only on this account
2. On the App's page: **Generate a new client secret** (no private key needed).
3. **Install App** → pa-bailar → only the **backend** repository.
4. Cloudflare → the `pa-bailar-admin` Worker → **Settings** → **Variables and Secrets**, each as a **Secret**:
   - `GITHUB_CLIENT_ID`: the App's Client ID (starts with `Iv`)
   - `GITHUB_CLIENT_SECRET`: the secret from step 2
   - `SESSION_SECRET`: a random value, e.g. from PowerShell:
     `[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))`.
     Changing it signs everyone out.

Until the three secrets exist, the page says that the sign-in isn't set up yet.
