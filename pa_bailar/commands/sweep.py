"""sweep: collect one-time dance events from the accounts in accounts.txt.

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar sweep             # posts from the last 7 days
    .venv\\Scripts\\python -m pa_bailar sweep --days 14   # look further back
"""

import argparse
import logging
import os
from pathlib import Path

from pa_bailar import config
from pa_bailar.logs import setup_logging
from pa_bailar.pipeline import RunStats, Sweep


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
    return "\n".join(
        [
            "## Daily sweep",
            "",
            f"{stats.posts_analyzed} posts analyzed ({stats.posts_triaged_out} ruled out by triage) · "
            f"{stats.events_new} new events · {stats.events_merged} merged into existing events · "
            f"{stats.events_discarded} discarded (recurring/undated) · {stats.provisional} provisional · "
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar sweep", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days",
        type=int,
        default=config.DEFAULT_LOOKBACK_DAYS,
        help=f"only analyze posts published in the last N days (default {config.DEFAULT_LOOKBACK_DAYS})",
    )
    args = parser.parse_args(argv)
    setup_logging()

    stats = Sweep(lookback_days=args.days).run()

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
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_file).open("a", encoding="utf-8") as file:
            file.write(summary_markdown(stats))

    # Individual posts that fail are retried next run; only a sweep where no account could be read is broken.
    if stats.accounts and stats.failed_accounts == stats.accounts:
        raise SystemExit("Every account failed. Check the logs above.")


if __name__ == "__main__":
    main()
