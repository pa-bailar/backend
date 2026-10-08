# Pa' Bailar workspace

Two repositories under this folder:
- `pa-bailar/`: the backend (`pa-bailar/backend`, public since 6 Oct 2026): the sweep (Instagram → Gemini → events),
  discovery, health checks, admin tools (the admin page in `admin-web/`), and the video toolkit in `media/` (its own
  `README.md`). Python 3.12.
- `pa-bailar-web/`: the public site (`pa-bailar/pa-bailar.github.io`): Astro in `frontend/`, the data in `data/`.

Each has `README.md` and `docs/ARCHITECTURE.md`. The backend also has `docs/ADMIN.md` (the admin tools) and
`docs/PLAN.md` (the original plan, kept as a record); the site also has `docs/DESIGN.md` and `docs/DATA.md`.

## Starting a session

`.claude/CONTEXT.md` (loaded with this file) says how the project fits together, where each truth lives and what
bites. Then read the current state in **`Code/handoff/HANDOFF.md`** before the first task, and verify it (open PRs,
worktrees, the last sweeps). Before this conversation ends or gets long, run the `handoff` skill.

## Changing code

- Work on a branch, never on `main`. Pull request titles follow Conventional Commits: in the site they set
  the next version (`frontend/scripts/release.mjs`), and `ci` rejects other titles.
- Commits use the author's noreply address: `15051424+jzamora5@users.noreply.github.com` (name `jzamora5`).
- **Before every `gh pr create`: commit, then run the `sync-docs` skill**, then push and open the PR in a separate
  command. A hook (`pa-bailar/.claude/hooks/require-docs-sync.mjs`) blocks the PR until the docs were synced at
  the branch's latest commit. The docs hold architecture, behavior and decisions, never pixel-level detail.
- Merge only when every check reports pass. Changes to the sweep path or the workflows, and discovery runs, only
  outside the sweep windows (6:00–7:15 and 20:30–21:45 Bogotá; the time from `node`, not `TZ=… date`).
- Test what the user will see, in real conditions: the preview at phone size (375 px), scrolled-down states,
  a first visit, both themes. Check the live site after a deploy.
- Multi-line edits: use the Edit/Write tools or a script file in the scratchpad, not heredocs with regexes or
  backslashes (they get mangled).

## Review process

Three tiers, by cost. Each pass is recorded in the handoff's "Passes" (date, scope, PR), which is how the next
session knows one is due.

1. **Every PR:** `sync-docs` (the hook enforces it). **When the PR is risky**, also `bug-squash` on the feature it
   belongs to, whole: risky means the site's interaction code (`main.ts`, history, the views, scroll, storage), the
   sweep pipeline, or the workflows. Copy, `accounts.txt`, docs and CSS-only tweaks skip it.
2. **Full passes at set moments:** `bug-squash`, then `code-quality`, then `sync-docs`' whole-repository drift
   check, on what changed since the last pass:
   - before anything public (a launch, sharing the site in groups, a Story pointing to it);
   - after about 10 feature PRs since the last pass;
   - on one area, when a fix lands where bugs were found before.
3. **On request:** any of them, scoped to what the owner names.

## Skills

`sync-docs` (docs before every PR; the whole repository for drift), `bug-squash` (find, prove and fix bugs, with
guards), `code-quality` (code up to standard: tokens, shared utilities and components, types, tests), `handoff` (the
state for the next session: the handoff, CONTEXT.md, memory), `teaser` (videos with `media/`), `media-clean` (videos' old versions and unused takes and tracks to the Recycle Bin, at the end of every video session).

## Never

- Commit or read `pa-bailar/private/` (the Instagram export, discovery results, the App's `.pem` key) or `.env`.
- Put keys or tokens in chat, code or URLs; the user creates tokens and pastes them into GitHub secrets themselves.
- Approve workflow runs or change organization or security settings without the user.
