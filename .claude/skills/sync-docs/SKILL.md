---
name: sync-docs
description: Bring a branch's documentation up to date with its code changes, in pa-bailar (backend) or pa-bailar-web (site), before opening a pull request. Use it every time, right before `gh pr create`; a hook blocks the PR until it has run at the branch's latest commit. Also checks the whole repository for drift when the owner asks whether the docs are up to date, in a code-quality pass, and before a launch.
---

# Sync the docs with this branch's changes

Run this after committing the change and before opening its pull request. Docs that describe the code
(how it works, its files, commands, workflows, tokens, decisions) must say what the branch makes true.

**The docs are architecture and decisions, not a description of every pixel.** What belongs in them, and what
doesn't:

| Documented | Not documented |
|---|---|
| How it works: modules, the flow of data, history and overlays, the sweep's steps | Pixel sizes, opacities, exact spacing |
| Rules and behavior a reader needs ("Guardados has no filters", "back returns to the list") | Which token a component uses, a color within the palette |
| Decisions, with who and when ("the owner, 5 Oct 2026"), and why | A button's position or order inside a row |
| The data contract, workflows, commands, settings, tokens (the token table itself) | Copy tweaks, icon choices, small visual adjustments |
| Files and modules (the code maps), tests' scope | What the code and a screenshot already show |

So a visual tweak usually needs **no doc change**, and that's a valid result. When it makes an existing statement
false (the doc said "40% opacity" and now it's 50%), fix it by making the statement less detailed ("faded"), not by
updating the number: the doc then survives the next tweak. Never add new pixel-level detail.

## 1. See what changed

In the repository of the branch:

```bash
git fetch -q origin main
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
```

Note every name, value, file, command, time, limit, color, copy text or behavior that was added, removed or
renamed.

## 2. Find the docs that describe it

| Repository | Doc | Covers |
|---|---|---|
| backend (`pa-bailar`) | `README.md` | Commands, workflows, schedule, monitoring, setup, dependencies |
| backend | `docs/ARCHITECTURE.md` | Modules, pipeline, Gemini models and quotas, Instagram, state files, health checks, diagrams |
| backend | `docs/ADMIN.md` | The admin tools: the issues inbox, the admin page, commands, examples |
| site (`pa-bailar-web`) | `README.md` | Develop, workflows, versions, statistics, contributing |
| site | `docs/ARCHITECTURE.md` | Pages and endpoints, build, workflows, browser modules, third-party services, code map, diagrams |
| site | `docs/DESIGN.md` | Tokens, themes, components, copy, interaction decisions |
| site | `docs/DATA.md` | The data contract (`events.json`, `meta.json`), shared with the backend |

Leave `docs/PLAN.md` (backend) alone: it's the original plan, kept as a record.

Search the docs for each changed name or value, old and new (`grep -rn "<old value>" docs README.md`), and read
the sections around them. A change to the data's shape touches both repositories: backend `models.py`, site
`docs/DATA.md`, `types.ts` and `scripts/check-data.mjs`.

## 3. Update them

- Fix every statement the branch made wrong: tables, lists, code maps, Mermaid diagrams, numbers, times, names.
- Add what's new where a reader would look for it (a new command in the commands table, a new page in the
  pages table, a new token in the token table), in the doc's existing style: plain English, short sentences,
  bullets for lists, `code` for names, no marketing words. Only what the table above says is documented.
- Remove what no longer exists. Don't rewrite sections the branch didn't touch.
- If nothing needs to change, that's a valid result: say why (e.g. "internal refactor, no documented names
  changed").

## 4. Commit and record the sync

```bash
git add README.md docs
git diff --cached --quiet || git commit -q -m "docs: <what the docs now cover>"
git rev-parse HEAD > "$(git rev-parse --git-dir)/docs-synced"
```

The last line is what lets `gh pr create` through (`.claude/hooks/require-docs-sync.mjs`). Any later commit
needs the sync again. Then push and open the PR in a separate command.

## 5. Report

One or two lines in the reply: which docs changed and how, or why none needed to.

## A whole-repository check (drift)

A branch's sync only sees that branch. Across many PRs the docs can still drift: a phrase that was true for two
views and not for three, a module renamed in one table but not in another, a test file never listed. Check the
whole repository when the owner asks "are the docs up to date?", during a `code-quality` pass, and before a launch:

- Names: every module, file, command, workflow, CSS token and setting the docs name still exists
  (list the names the docs write as `code` and look for each in the code), and the code's main ones are named
  where a reader would look (the code maps, the pages table, the tests row, the workflows table).
- Numbers and lists: counts (accounts, views, tests' scope), times (the sweeps, the windows), limits and quotas
  against `config.py`, `accounts.txt`, the workflows.
- Phrases left by a change: grep for words the last features made false ("both views", old names, removed
  controls).
- Fix it on a branch (`docs/<what>`), then the steps above from 4.
