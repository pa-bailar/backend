// Claude Code hook (PreToolUse, Bash): no pull request is opened before the docs were synced.
//
// When a Bash command runs `gh pr create`, the repository it's for must have been through the sync-docs skill
// at its current commit: the skill updates the docs and then records HEAD in .git/docs-synced. A new commit
// after that (or no sync at all) blocks the command (exit 2), and the message tells Claude what to do.
// Wired in the workspace's .claude/settings.json (README, "Working with Claude Code").
//
// Which repository: the folder of the last `cd` in the command before `gh pr create`, else the hook's cwd.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const input = JSON.parse(readFileSync(0, "utf8"));
const command = input.tool_input?.command ?? "";
// Only when it runs as a command (at the start, or after ; && || | ( or a new line), not when it's mentioned
// in text, e.g. a doc being written by a heredoc.
const match = /(?:^|&&|\|\||[;|(\n])\s*gh\s+pr\s+create\b/.exec(command);
if (!match) process.exit(0);
const prCreate = match.index;

// "/c/Users/…" (Git Bash) → "C:/Users/…", so Node on Windows can use it.
const nativePath = (dir) => dir.replace(/^\/([a-zA-Z])\//, (_, drive) => `${drive.toUpperCase()}:/`);

const cds = [...command.slice(0, prCreate).matchAll(/\bcd\s+("[^"]+"|'[^']+'|[^\s;&|]+)/g)];
const lastCd = cds.at(-1)?.[1]?.replace(/^["']|["']$/g, "");
const dir = lastCd ? path.resolve(input.cwd ?? process.cwd(), nativePath(lastCd)) : (input.cwd ?? process.cwd());

const git = (...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();

let head, gitDir, repo;
try {
  head = git("rev-parse", "HEAD");
  gitDir = path.resolve(dir, git("rev-parse", "--git-dir"));
  repo = path.basename(git("rev-parse", "--show-toplevel"));
} catch {
  process.exit(0); // not a git repository: nothing to check
}

const marker = path.join(gitDir, "docs-synced");
const synced = existsSync(marker) ? readFileSync(marker, "utf8").trim() : "";
if (synced === head) process.exit(0);

console.error(
  `Docs not synced for ${repo} at ${head.slice(0, 7)}. Before opening the pull request: commit the change, ` +
    `run the sync-docs skill (it updates the docs, commits them and records the sync), then run ` +
    `\`gh pr create\` in its own command (not chained after a commit, which would change the commit again).`,
);
process.exit(2);
