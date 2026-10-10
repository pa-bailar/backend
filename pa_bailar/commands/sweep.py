"""sweep: collect one-time dance events from the accounts in accounts.txt.

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar sweep             # posts from the last 7 days
    .venv\\Scripts\\python -m pa_bailar sweep --days 14   # look further back (at most 30)
    .venv\\Scripts\\python -m pa_bailar sweep --all       # every account now, not only those whose turn it is
Adding one post by hand (the admin tools' Agregar, docs/ADMIN.md) is `sweep --post <link> [--account @x] [--again]`.
A story from its screenshots ("Agregar historia") is `sweep --story <id> [<id>…] [--story-dir stories]
[--account @x] [--notes "…"]`: the sweep workflow downloads them from the admin page first, as <id>.jpg and
<id>.json in --story-dir. `sweep --hide-story story-<hash>` takes one off the site again ("Ocultar historia"), and
`sweep --hide-event <event id>` any event, whatever it came from ("Ocultar", e.g. a new workshop series). Their
answers are written by answers.py.
"""

import argparse
import json
import logging
import os
from pathlib import Path

from pa_bailar import changes, config, health, links, storage, stories
from pa_bailar.commands.answers import (
    added_post_markdown,
    added_story_markdown,
    hidden_event_markdown,
    hidden_story_markdown,
)
from pa_bailar.logs import setup_logging
from pa_bailar.pipeline import AddPostError, RunStats, Sweep

log = logging.getLogger(__name__)


def summary_markdown(stats: RunStats) -> str:
    """Markdown tables shown on the GitHub Actions run page."""
    account_rows = [
        f"| @{account}{' (new)' if s.backfill else ''} | {'❌ fetch failed' if s.fetch_failed else s.posts_analyzed} "
        f"| {s.events_new} | {s.events_merged} | {s.pending} | {s.errors} |"
        for account, s in stats.by_account.items()
    ]
    model_rows = [
        f"| {model} | {stats.gemini_requests.get(model, 0)} | {limit.requests_per_day} |"
        for model, limit in config.MODEL_LIMITS.items()
    ]
    model_rows += [  # the last resort, when Gemini ran out
        f"| {provider.name} (last resort) | {requests} | {provider.daily_requests} (budget) |"
        for provider in config.EXTERNAL_PROVIDERS
        if (requests := stats.gemini_requests.get(provider.name))
    ]
    batched = (  # batched extraction (config.EXTRACTION_BATCH_POSTS), when it read anything
        f"{stats.batched_posts} read in {stats.batch_requests} shared requests, "
        f"{stats.batch_rereads} read again alone · "
        if stats.batch_requests or stats.batch_rereads
        else ""
    )
    return "\n".join(
        [
            "## Daily sweep",
            "",
            f"{stats.posts_analyzed} posts analyzed ({stats.posts_triaged_out} ruled out by triage) · "
            f"{stats.events_new} new events · {stats.events_merged} merged into existing events · "
            f"{stats.events_discarded} discarded (recurring, undated, past or outside Bogotá) · "
            f"{stats.provisional} provisional · {batched}"
            f"{stats.upgraded} upgraded · {stats.reanalyzed} re-analyzed (edited captions) · "
            f"{stats.pending} pending for next run · {stats.errors} errors · "
            f"{stats.events_expired} past events and {stats.flyers_removed} flyers cleaned up",
            "",
            "| Account | Posts analyzed | New events | Merged | Pending | Errors |",
            "|---|---|---|---|---|---|",
            *account_rows,
            "",
            "### Gemini requests",
            "",
            "| Model | This run | Daily limit |",
            "|---|---|---|",
            *model_rows,
            "",
        ]
    )


def run_url() -> str | None:
    """This run's page on GitHub Actions (None for local runs)."""
    parts = [os.environ.get(name) for name in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")]
    return "{}/{}/actions/runs/{}".format(*parts) if all(parts) else None


def check_health(stats: RunStats) -> tuple[list[health.Finding], str]:
    """Compare the run with the previous ones (health.py), add it to the history, and build the report."""
    url = run_url()
    history = health.load_history()
    run = health.record_of(stats, storage.read_accounts(), url)
    today = config.now_bogota().date()
    findings = health.check(run, history, stats, today)
    run.warnings = [finding.key for finding in findings if finding.level == "warning"]
    health.save_history([*history, run])
    review = health.events_to_review(storage.load_events(), today)
    return findings, health.report_markdown(findings, review, url)


def publish_health(findings: list[health.Finding], report: str) -> None:
    """The report in the log, and for the workflow: annotations on the run page, the warning count and
    fingerprint as step outputs, the report file for the health issue and the health-check ping."""
    warnings = [finding for finding in findings if finding.level == "warning"]
    for finding in findings:
        log.log(logging.WARNING if finding.level == "warning" else logging.INFO, "Health: %s", finding.text)
    if os.environ.get("GITHUB_ACTIONS"):
        for finding in warnings:
            print(f"::warning title=Sweep health::{finding.text}", flush=True)
    if output_file := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_file).open("a", encoding="utf-8") as file:
            file.write(f"warnings={len(warnings)}\nfingerprint={health.fingerprint(findings)}\n")
    if report_file := os.environ.get("HEALTH_REPORT_FILE"):
        Path(report_file).write_text(report, encoding="utf-8")


def lookback_days(value: str) -> int:
    """--days: a whole number from 1 to MAX_LOOKBACK_DAYS."""
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {value!r}") from None
    if not 1 <= days <= config.MAX_LOOKBACK_DAYS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {config.MAX_LOOKBACK_DAYS}, got {days}")
    return days


def record_request(
    action: changes.AdminAction, target: str | None, sweep: Sweep | None, error: AddPostError | None = None
) -> None:
    """An admin request's run for the admin page's history (changes.py): what it did to which event, or why it
    couldn't. After the request saved its state, like the sweep's run record."""
    done = sweep.stats.changes.values() if sweep else []
    changes.record_admin_run(action, target, done, run_url(), str(error) if error else None)


def add_post(link: str, account: str | None, again: bool = False) -> None:
    """`sweep --post`: publish one post by hand (`--again`: read it again even if it hasn't changed). The answer
    goes to ADMIN_REPORT_FILE (the workflow comments it on the admin issue) and the log; a failure to add it
    isn't a failed run (the answer says why)."""
    sweep, failure = None, None
    try:
        sweep = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS)
        report = added_post_markdown(sweep.add_post(link, account, again=again))
    except AddPostError as error:
        report, failure = f"❌ {error}\n", error
    record_request("post_again" if again else "post", link, sweep, failure)
    _write_report(report)


def hide_event(event_id: str) -> None:
    """`sweep --hide-event`: take an event off the site by hand ("Ocultar")."""
    sweep, failure = None, None
    try:
        sweep = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS)
        report = hidden_event_markdown(sweep.hide_event(event_id))
    except AddPostError as error:
        report, failure = f"❌ {error}\n", error
    record_request("hide_event", event_id, sweep, failure)
    _write_report(report)


def _write_report(report: str) -> None:
    logging.info("\n%s", report)
    if report_file := os.environ.get("ADMIN_REPORT_FILE"):
        Path(report_file).write_text(report, encoding="utf-8")


def load_screenshots(ids: list[str], folder: Path) -> list[stories.Screenshot]:
    """The screenshots the workflow downloaded: <id>.jpg, and <id>.json with the file's name and dates."""
    shots = []
    for upload in ids:
        meta_file = folder / f"{upload}.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        name, modified, uploaded = meta.get("name"), meta.get("modified"), meta.get("uploaded")
        shots.append(
            stories.Screenshot(
                (folder / f"{upload}.jpg").read_bytes(),
                name if isinstance(name, str) else "",
                modified if isinstance(modified, int) else None,
                uploaded if isinstance(uploaded, int) else None,
            )
        )
    return shots


def add_story(ids: list[str], folder: Path, account: str | None, notes: str | None) -> None:
    """`sweep --story`: publish a story's events from its screenshots. The answer goes to ADMIN_REPORT_FILE, and
    `story_done=true` to the workflow when the screenshots aren't needed any more (it then deletes them)."""
    done, story_id = False, None
    sweep, failure = None, None
    try:
        sweep = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS)
        added = sweep.add_story(load_screenshots(ids, folder), account, notes)
        report, done, story_id = added_story_markdown(added), added.done, added.story_id
    except AddPostError as error:
        report, failure = f"❌ {error}\n", error
    record_request("story", story_id, sweep, failure)
    _write_report(report)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as file:
            file.write(f"story_done={str(done).lower()}\n")


def hide_story(story_id: str) -> None:
    """`sweep --hide-story`: take a story added by hand off the site."""
    sweep, failure = None, None
    try:
        sweep = Sweep(lookback_days=config.DEFAULT_LOOKBACK_DAYS)
        report = hidden_story_markdown(sweep.hide_story(story_id))
    except AddPostError as error:
        report, failure = f"❌ {error}\n", error
    record_request("hide_story", story_id, sweep, failure)
    _write_report(report)


def is_broken(stats: RunStats) -> bool:
    """A run that must show as failed (and alert): no account could be read, and not because Instagram's rate
    limit stopped it. Failed posts are retried next run, and a rate-limited run just waits for the next one;
    the health checks warn when either keeps happening."""
    return bool(stats.accounts) and stats.failed_accounts == stats.accounts and not stats.rate_limited


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar sweep", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days",
        type=lookback_days,
        default=config.DEFAULT_LOOKBACK_DAYS,
        help=f"only analyze posts published in the last N days (default {config.DEFAULT_LOOKBACK_DAYS}, "
        f"at most {config.MAX_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--all", action="store_true", help="read every account now, not only those whose turn it is (once a day)"
    )
    parser.add_argument("--post", help="add one post by hand instead (its Instagram link): the admin tools' Agregar")
    parser.add_argument("--account", help="with --post: the @account, if the link doesn't say it")
    parser.add_argument(
        "--again",
        action="store_true",
        help="with --post: read it again even if it was read before and hasn't changed (one Gemini request)",
    )
    parser.add_argument(
        "--story",
        nargs="+",
        metavar="ID",
        help="add a story by hand instead, from its screenshots (the admin page's upload ids, at most 4)",
    )
    parser.add_argument(
        "--story-dir", type=Path, default=Path("stories"), help="with --story: where <id>.jpg and <id>.json are"
    )
    parser.add_argument("--notes", help="with --story: the admin's notes (hints for Gemini, never published)")
    parser.add_argument("--hide-story", metavar="STORY", help="take a story added by hand off the site (story-…)")
    parser.add_argument(
        "--hide-event", metavar="ID", help="take an event off the site by hand, whatever it came from (its id)"
    )
    args = parser.parse_args(argv)
    setup_logging()

    if args.story:
        account = links.account_name(args.account) if args.account else None
        add_story(args.story[: stories.MAX_SCREENSHOTS], args.story_dir, account, args.notes)
        return
    if args.hide_story:
        hide_story(args.hide_story)
        return
    if args.hide_event:
        hide_event(args.hide_event)
        return
    if args.post:
        add_post(args.post, links.account_name(args.account) if args.account else None, again=args.again)
        return

    stats = Sweep(lookback_days=args.days, all_accounts=args.all).run()

    logging.info(
        "\nDone: %s accounts, %s posts analyzed (%s ruled out by triage), %s new events, %s merged, "
        "%s discarded, %s provisional, %s upgraded, %s pending, %s errors. Gemini requests: %s",
        stats.accounts,
        stats.posts_analyzed,
        stats.posts_triaged_out,
        stats.events_new,
        stats.events_merged,
        stats.events_discarded,
        stats.provisional,
        stats.upgraded,
        stats.pending,
        stats.errors,
        stats.gemini_requests or "none",
    )
    findings, report = check_health(stats)
    publish_health(findings, report)
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_file).open("a", encoding="utf-8") as file:
            file.write(report + "\n" + summary_markdown(stats))  # health first: what needs a look

    if is_broken(stats):
        raise SystemExit("Every account failed. Check the logs above.")


if __name__ == "__main__":
    main()
