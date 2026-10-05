"""Quality control of every sweep, by rules: no AI and no quota.

After each run, `check` compares it with the previous ones (config.RUN_HISTORY_FILE, kept on the
sweep-state branch with the rest of the state) and returns what needs a look:
  - warnings: something to fix or decide. A problem repeated over several runs (an account that can't be
    read, posts that keep failing, Instagram's rate limit or the time budget cutting every run short, a Gemini
    model this key can no longer use), a backlog that doesn't go down, a week of posts without a single event.
  - notices: worth knowing, nothing to do yet. This run's one-off problems, Flash's quota running out,
    accounts without posts for weeks, upcoming events worth a second look (Gemini wasn't confident, or
    doubted the date, or a congress or festival has a single day).

The sweep puts the report at the top of the run's summary on GitHub. The workflow keeps an open "Sweep
health" issue while there are warnings (commenting, so GitHub emails, only when they change) and sends
the report with the health-check ping.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from . import config, storage
from .models import StoredEvent
from .pipeline import RunStats
from .text import event_dates_label, fold

HISTORY_RUNS = 120  # runs kept: two a day, two months
REPEATED_RUNS = 3  # a problem in this many runs in a row is a pattern, not bad luck
STUCK_RUNS = 4  # pending posts not going down over this many runs: the backlog is stuck
QUIET_RUNS = 14  # a week of runs...
QUIET_MIN_POSTS = 10  # ...analyzing at least this many posts without finding a single event
INACTIVE_DAYS = 45  # an account without posts for this long may be abandoned
DATE_DOUBT = re.compile(r"\b(fecha|dias?)\b")  # doubts about the date (folded text): the costliest mistake
# "@name" in an issue mentions (and notifies) the GitHub user of that name. Instagram handles, and titles or
# doubts quoting them, get an invisible word joiner after the "@": they read the same but ping no one.
MENTION = re.compile(r"@(?=[\w-])")
WORD_JOINER = "⁠"


class RunRecord(BaseModel):
    """One record of state/run_history.json: what a sweep did, in short."""

    finished_at: str
    run_url: str | None = None
    accounts: int
    failed_accounts: list[str]  # couldn't be read
    # Every account the run tried to read (failed ones too). Each account is read about once a day, so a run
    # that didn't try one says nothing about it. Empty in records from before this was kept.
    read_accounts: list[str] = []
    skipped_accounts: list[str]  # its turn, but not reached (its share, or Instagram's limit): first next run
    posts_analyzed: int
    events_new: int
    events_merged: int
    pending: int
    post_errors: int  # posts that failed and are retried next run (accounts that couldn't be read not counted)
    provisional: int
    rate_limited: bool
    out_of_time: bool
    gemini_requests: dict[str, int]
    models_unavailable: list[str] = []  # Gemini models this key couldn't use (e.g. taken out of the free tier)
    instagram_usage: int | None = None  # share of Instagram's quota used when the run ended
    warnings: list[str] = []  # keys of the warnings found (Finding.key)


_history_adapter = TypeAdapter(list[RunRecord])


def load_history() -> list[RunRecord]:
    return _history_adapter.validate_python(storage.read_json(config.RUN_HISTORY_FILE, []))


def save_history(history: list[RunRecord]) -> None:
    storage.write_json(config.RUN_HISTORY_FILE, _history_adapter.dump_python(history[-HISTORY_RUNS:], mode="json"))


def record_of(stats: RunStats, followed: list[str], run_url: str | None = None) -> RunRecord:
    failed = [account for account, s in stats.by_account.items() if s.fetch_failed]
    return RunRecord(
        finished_at=config.now_bogota().isoformat(timespec="seconds"),
        run_url=run_url,
        accounts=stats.accounts,
        failed_accounts=failed,
        read_accounts=sorted(stats.by_account),
        skipped_accounts=[account for account in stats.due_accounts if account not in stats.by_account],
        posts_analyzed=stats.posts_analyzed,
        events_new=stats.events_new,
        events_merged=stats.events_merged,
        pending=stats.pending,
        post_errors=max(stats.errors - len(failed), 0),
        provisional=stats.provisional,
        rate_limited=stats.rate_limited,
        out_of_time=stats.out_of_time,
        gemini_requests=stats.gemini_requests,
        models_unavailable=stats.models_unavailable,
        instagram_usage=stats.instagram_usage,
    )


@dataclass(frozen=True)
class Finding:
    level: Literal["warning", "notice"]
    key: str  # what the problem is, without counts: the same problem isn't reported as new every run
    text: str  # Markdown


def _streak(
    runs: list[RunRecord], happened: Callable[[RunRecord], bool], applies: Callable[[RunRecord], bool] | None = None
) -> int:
    """How many of the latest runs, in a row, had it. Runs it doesn't apply to (`applies`) are skipped."""
    count = 0
    for run in reversed(runs):
        if applies is not None and not applies(run):
            continue
        if not happened(run):
            break
        count += 1
    return count


def _repeated(
    runs: list[RunRecord],
    happened: Callable[[RunRecord], bool],
    key: str,
    warning: str,
    notice: str,
    applies: Callable[[RunRecord], bool] | None = None,
) -> list[Finding]:
    """A warning when it happened in REPEATED_RUNS runs in a row (among those it applies to), a notice when
    only in this one."""
    streak = _streak(runs, happened, applies)
    if streak >= REPEATED_RUNS:
        return [Finding("warning", key, warning.format(runs=streak))]
    return [Finding("notice", key, notice)] if streak else []


def check(run: RunRecord, history: list[RunRecord], stats: RunStats, today: date) -> list[Finding]:
    """What this run (with the ones before it) says needs a look. Warnings first."""
    runs = [*history, run]
    findings: list[Finding] = []

    for account in run.failed_accounts:

        def failed(r: RunRecord, account: str = account) -> bool:
            return account in r.failed_accounts

        def tried(r: RunRecord, account: str = account) -> bool:
            # Older records don't list what was read: they count, as before.
            return not r.read_accounts or account in r.read_accounts or account in r.failed_accounts

        findings += _repeated(
            runs,
            failed,
            f"fetch:{account}",
            f"@{account} couldn't be read in the last {{runs}} tries: renamed, private or no longer a "
            "business or creator account? Check it on Instagram and update accounts.txt.",
            f"@{account} couldn't be read this run (it's tried again on its next turn).",
            applies=tried,
        )
    findings += _repeated(
        runs,
        lambda r: r.rate_limited,
        "rate-limit",
        "Instagram's rate limit stopped the last {runs} runs early: the accounts after it waited each time. "
        "Too many accounts for the app's hourly quota?",
        f"Instagram's rate limit stopped this run early: {len(run.skipped_accounts)} accounts wait for the next one.",
    )
    findings += _repeated(
        runs,
        lambda r: r.out_of_time,
        "time-budget",
        f"The last {{runs}} runs used their whole time budget ({config.MAX_RUN_MINUTES} min): "
        "posts keep waiting. Is the backlog of new accounts too big?",
        f"This run used its whole time budget ({config.MAX_RUN_MINUTES} min): the rest waits for the next one.",
    )
    findings += _repeated(
        runs,
        lambda r: r.post_errors > 0,
        "post-errors",
        f"Posts failed in each of the last {{runs}} runs ({run.post_errors} this run): Gemini rejections, "
        "image downloads or unexpected errors. See the run's log.",
        f"{run.post_errors} posts failed this run (tried again next run). See the run's log.",
    )

    unavailable = ", ".join(run.models_unavailable)
    findings += _repeated(
        runs,
        lambda r: bool(r.models_unavailable),
        "models-unavailable",
        f"Gemini said this key can't use {unavailable} in the last {{runs}} runs: did Google change the free "
        "tier? Extraction falls back to Flash-Lite meanwhile. To make that the plan, set the repository "
        "variable GEMINI_LITE_ONLY to 1 (docs/ARCHITECTURE.md, Gemini).",
        f"Gemini said this key can't use {unavailable} this run (it's tried again next run).",
    )

    backlog = runs[-STUCK_RUNS:]
    if len(backlog) == STUCK_RUNS and all(r.pending for r in backlog) and run.pending >= backlog[0].pending:
        findings.append(
            Finding(
                "warning",
                "backlog-stuck",
                f"{run.pending} posts are waiting and the backlog hasn't gone down in {STUCK_RUNS} runs: "
                "the daily Gemini quota or the time budget is too small for the accounts followed.",
            )
        )
    elif run.pending:
        findings.append(Finding("notice", "pending", f"{run.pending} posts wait for the next run (quota or time)."))

    quiet = runs[-QUIET_RUNS:]
    quiet_posts = sum(r.posts_analyzed for r in quiet)
    found_nothing = not any(r.events_new or r.events_merged for r in quiet)
    if len(quiet) == QUIET_RUNS and found_nothing and quiet_posts >= QUIET_MIN_POSTS:
        findings.append(
            Finding(
                "warning",
                "no-events",
                f"No events found in the last {QUIET_RUNS} runs (a week) although {quiet_posts} posts were "
                "analyzed: are triage or extraction rejecting everything? Check the prompts.",
            )
        )

    if run.provisional:
        findings.append(
            Finding(
                "notice",
                "provisional",
                f"Flash's daily quota ran out: {run.provisional} posts were extracted with the light model "
                "(upgraded on later runs).",
            )
        )

    for account, s in stats.by_account.items():
        if s.fetch_failed:
            continue
        if s.latest_post is None:
            findings.append(Finding("notice", f"inactive:{account}", f"@{account} has no posts at all."))
        elif (days := (today - date.fromisoformat(s.latest_post)).days) >= INACTIVE_DAYS:
            findings.append(
                Finding(
                    "notice",
                    f"inactive:{account}",
                    f"@{account} hasn't posted in {days} days: still active? Remove it from accounts.txt if not.",
                )
            )

    return sorted(findings, key=lambda finding: finding.level != "warning")


SINGLE_DAY_DOUBT = "un solo día: ¿faltan fechas?"  # a congress or festival usually lasts several days


def review_reasons(event: StoredEvent) -> list[str]:
    """Why an event is worth a second look (empty: it isn't): its doubts when Gemini wasn't confident or doubted
    the date, and a congress or festival dated on one day only (its other days may be missing)."""
    reasons = []
    if event.confidence != "high" or any(DATE_DOUBT.search(fold(doubt)) for doubt in event.doubts):
        reasons += event.doubts or ["no details"]
    if event.event_type in ("congress", "festival") and not event.end_date:
        reasons.append(SINGLE_DAY_DOUBT)
    return reasons


def events_to_review(events: list[StoredEvent], today: date) -> list[StoredEvent]:
    """Upcoming events (until their last day) worth a second look (review_reasons)."""
    upcoming = [event for event in events if (event.last_day or "") >= today.isoformat()]
    return [event for event in upcoming if review_reasons(event)]


def fingerprint(findings: list[Finding]) -> str:
    """Identifies the set of warnings: it changes only when a warning appears or goes away."""
    keys = sorted(finding.key for finding in findings if finding.level == "warning")
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:12]


def report_markdown(findings: list[Finding], review: list[StoredEvent], run_url: str | None = None) -> str:
    """The health section: on the run's summary page, in the health issue and with the health-check ping."""
    warnings = [finding for finding in findings if finding.level == "warning"]
    notices = [finding for finding in findings if finding.level == "notice"]
    lines = ["## Health", ""]
    if not findings and not review:
        lines.append("✅ Nothing to look at.")
    if warnings:
        lines += ["### ⚠️ Warnings", "", *(f"- {finding.text}" for finding in warnings), ""]
    if notices:
        lines += ["### Notices", "", *(f"- {finding.text}" for finding in notices), ""]
    if review:
        lines += [
            "### Events to review",
            "",
            "Gemini wasn't confident about them or doubted the date, or a congress or festival has a single day:",
            "",
        ]
        for event in review:
            reasons = "; ".join(review_reasons(event))
            link = f"[{event.title}]({event.media[0].permalink})" if event.media else event.title
            when = event_dates_label(event.date, event.end_date, event.session_dates)
            lines.append(f"- {when} · {link} (@{event.account}, {event.confidence} confidence): {reasons}")
        lines.append("")
    if run_url:
        lines += [f"[Run log]({run_url})", ""]
    text = MENTION.sub("@" + WORD_JOINER, "\n".join(lines))
    return f"{text}\n<!-- health-fingerprint: {fingerprint(findings)} -->\n"
