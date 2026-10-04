# Pa' Bailar workspace

Two repositories under this folder:
- `pa-bailar/`: the private backend (`pa-bailar/backend`): the sweep (Instagram → Gemini → events), discovery,
  health checks, admin tools. Python 3.12.
- `pa-bailar-web/`: the public site (`pa-bailar/pa-bailar.github.io`): Astro in `frontend/`, the data in `data/`.

Each has `README.md` and `docs/ARCHITECTURE.md`. The backend also has `docs/ADMIN.md` (the admin tools) and
`docs/PLAN.md` (the original plan, kept as a record); the site also has `docs/DESIGN.md` and `docs/DATA.md`.

## Changing code

- Work on a branch, never on `main`. Pull request titles follow Conventional Commits: in the site they set
  the next version (`frontend/scripts/release.mjs`), and `ci` rejects other titles.
- Commits use the author's noreply address: `15051424+jzamora5@users.noreply.github.com` (name `jzamora5`).
- **Before every `gh pr create`: commit, then run the `sync-docs` skill**, then push and open the PR in a separate
  command. A hook (`pa-bailar/.claude/hooks/require-docs-sync.mjs`) blocks the PR until the docs were synced at
  the branch's latest commit.
- Test what the user will see, in real conditions: the preview at phone size (375 px), scrolled-down states,
  a first visit, both themes. Check the live site after a deploy.
- Multi-line edits: use the Edit/Write tools or a script file in the scratchpad, not heredocs with regexes or
  backslashes (they get mangled).

## Never

- Commit or read `pa-bailar/private/` (the Instagram export, discovery results, the App's `.pem` key) or `.env`.
- Put keys or tokens in chat, code or URLs; the user creates tokens and pastes them into GitHub secrets themselves.
- Approve workflow runs or change organization or security settings without the user.
