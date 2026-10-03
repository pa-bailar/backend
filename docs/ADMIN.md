# Pa' Bailar admin tools

Tools for running Pa' Bailar day to day: see how the sweeps and quotas are doing, find out why an event isn't
on the site, add one by hand, fix a wrong detail. **Work in progress:** this page grows with each step.

| Step | What | State |
|---|---|---|
| Admin page hosting | A page with its own server functions, on Cloudflare Pages | Placeholder online |
| 1. Status | `admin status`: sweeps, Gemini and Instagram usage, token expiry, accounts | Next |
| 2. Events | `admin why`, `admin add-post`, `admin add-account`, and the issues inbox | Planned |
| 3. Admin page | Sign in with GitHub, dashboard, check or add a post from a link | Planned |
| 4. Corrections | `corrections.json` and `admin fix`, fed by the site's report form | Planned |

None of these tools is AI: they are fixed checks over what the sweep records. Only adding a post sends it
to Gemini (one request).

## The admin page

- **Where:** `https://pa-bailar-admin.pages.dev` (Cloudflare Pages, free), built from this repository's
  `admin-web/` folder on every push to `main`.
- **Files:** `admin-web/public/` is the page; `admin-web/functions/` are its server functions
  (`/api/...`), which run on Cloudflare and will hold the login.
- **Sign-in (step 3):** "Iniciar sesión con GitHub" through the pa-bailar-bot GitHub App. Only `jzamora5` gets
  in; the session lasts weeks and renews itself. Nothing to paste or renew.

### Cloudflare setup (done once)

1. Cloudflare dashboard → **Workers & Pages** → **Create** → the **Pages** tab → **Connect to Git**.
2. Connect GitHub: allow Cloudflare's app on the `pa-bailar` organization, **only the `backend` repository**.
3. Choose `pa-bailar/backend`, then:
   - **Project name:** `pa-bailar-admin` (the address becomes `pa-bailar-admin.pages.dev`)
   - **Production branch:** `main`
   - **Framework preset:** None
   - **Build command:** empty
   - **Build output directory:** `public`
   - **Root directory (advanced):** `admin-web`
4. **Save and Deploy.** The page says "Servidor: listo ✓" when the server functions work.
5. Project → **Settings** → **Builds** → **Branch deployments** (the wording varies): preview deployments
   **None**, so only `main` is published.
