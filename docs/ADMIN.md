# Pa' Bailar admin tools

Tools for running Pa' Bailar day to day: see how the sweeps and quotas are doing, find out why an event isn't
on the site, add one by hand, fix a wrong detail. **Work in progress:** this page grows with each step.

| Step | What | State |
|---|---|---|
| Admin page hosting | A page with its own server side, a Cloudflare Worker | Placeholder |
| 1. Status | `admin status`: sweeps, Gemini and Instagram usage, token expiry, accounts | Next |
| 2. Events | `admin why`, `admin add-post`, `admin add-account`, and the issues inbox | Planned |
| 3. Admin page | Sign in with GitHub, dashboard, check or add a post from a link | Planned |
| 4. Corrections | `corrections.json` and `admin fix`, fed by the site's report form | Planned |

None of these tools is AI: they are fixed checks over what the sweep records. Only adding a post sends it
to Gemini (one request).

## The admin page

- **Where:** the Cloudflare Worker `pa-bailar-admin` (free), at its `workers.dev` address
  (`https://pa-bailar-admin.<account>.workers.dev`). Cloudflare deploys it from this repository's
  `admin-web/` folder on every push to `main`.
- **Files:**
  - `admin-web/wrangler.jsonc`: the Worker's settings. Its `name` must match the Worker's name in Cloudflare.
  - `admin-web/public/`: the page, served as it is.
  - `admin-web/src/index.js`: the server side, for what `public/` doesn't cover (`/api/...`). It will hold
    the login.
- **Sign-in (step 3):** "Iniciar sesión con GitHub" through the pa-bailar-bot GitHub App. Only `jzamora5` gets
  in; the session lasts weeks and renews itself. Nothing to paste or renew.

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
