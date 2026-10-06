---
name: handoff
description: Leave Pa' Bailar ready for a new session with no memory of this one. Update the handoff (Code/handoff/HANDOFF.md, the current state) and, when a durable fact changed, the context doc (pa-bailar/.claude/CONTEXT.md) and memory. Use it when the owner says they'll start a new chat, wraps up for the day, or when this conversation is getting long; also after shipping something that changes how the project works, and at the end of a review pass.
---

# Hand off

The test: **if this conversation ended now, could a new session pick up the work correctly from what's written?**
Three places, each with one job. Nothing is written twice; each points to the others.

| Where | What | Changes |
|---|---|---|
| `Code/handoff/HANDOFF.md` (not versioned) | The **current state**: in flight, next steps, waiting on the owner, the last review passes | Every handoff |
| `pa-bailar/.claude/CONTEXT.md` (versioned, loaded every session) | **Durable** context: where each truth lives, how the pieces connect, what bites, lessons | Only when a durable fact changed |
| Memory (`MEMORY.md` + one file per fact) | The owner's **preferences and decisions**, and feedback on how to work | When the owner decided or asked something new |

The project's docs (READMEs, `docs/`) stay the source for how things work: `sync-docs` keeps them, not this skill.

## 1. Gather the real state (don't write from memory)

- `gh pr list` in both repositories (`-R pa-bailar/backend`, `-R pa-bailar/pa-bailar.github.io`), and what merged
  since the last handoff (`gh pr list --state merged -L 15` in each).
- `git worktree list` and `git status --short` in both checkouts; folders left in `Code` (a worktree no longer
  registered, an empty folder).
- Background tasks still running in this session, and what each is waiting for.
- The last sweeps: `gh run list -R pa-bailar/backend --workflow daily-sweep.yml -L 3`, and anything they flagged.
- What the owner asked for and hasn't got yet, and what they were asked and haven't answered: read back through
  this conversation for both.

## 2. Rewrite the handoff as a snapshot

`HANDOFF.md` is a snapshot, not a diary: rewrite it, don't append. First move the current file to
`Code/handoff/archive/HANDOFF-<date>.md` when it holds a day's log worth keeping. Then:

1. **Header:** the date and time (Bogotá, from `node`), and "where this disagrees with CONTEXT.md on the state,
   this wins".
2. **In flight:** each open PR, branch, worktree and background job: what it is, its state, the exact next action
   ("merge when `ci` passes; it touches workflows: outside the sweep windows").
3. **Next steps, in order:** concrete and checkable, with the command or the doc section to start from.
4. **Waiting on the owner:** each question asked and not answered, and each test only they can do.
5. **Passes:** the last `bug-squash`, `code-quality` and docs drift check (date, scope, PR) and how many feature PRs
   merged since each (`WORKSPACE.md`, "Review process").
6. **Recent changes worth knowing** (a few lines, the last day or two, with PR numbers): what a new session would
   otherwise trip over (a renamed module, a new rule, a fixed bug's cause).
7. **Backlog:** short; the parked ideas and what each waits for.

Keep it under ~1,500 words. Link to docs and PRs instead of explaining them.

## 3. Update CONTEXT.md only for durable facts

Read it, then ask of each thing learned in this session: will it still be true next month, and would a new session
get it wrong without it? Only then add it, in the section where it belongs (a new gotcha in §6, a new connection in
§4, a lesson in §7, a new doc or module in §2). Remove what stopped being true. Keep it near 1,500–2,000 words: it's
loaded into every session. It points to the docs; it never copies them (no tables of modules, no step-by-step).
Check every doc, section and file it names still exists.

It's versioned: change it on a branch in the backend repository and ship it the usual way (`sync-docs`, PR in its
own command, merge when green). The handoff and memory are not in git.

## 4. Memory

New preferences, decisions or corrections from the owner go to memory: one file each, following the memory
instructions (check for an existing file first; update rather than duplicate), plus its line in `MEMORY.md`. A
decision already written into the docs doesn't need a memory file beyond a pointer. Fix or delete memories that
turned out wrong.

## 5. Check, then report

- Open `HANDOFF.md` as a stranger would: could you start the first next step from it alone?
- Report to the owner in a few lines: what the handoff says is next, and anything waiting on them.
