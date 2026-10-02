"""Run the daily sweep: collect one-time dance events from the accounts in accounts.txt.

Usage (from the backend folder):
    .venv\\Scripts\\python run_pipeline.py             # posts from the last 7 days
    .venv\\Scripts\\python run_pipeline.py --days 14   # look further back
"""

import argparse
import logging
import os
from pathlib import Path

from pabailar import config
from pabailar.pipeline import RunStats, Sweep


def summary_markdown(stats: RunStats) -> str:
    """Markdown table shown on the GitHub Actions run page."""
    rows = [
        f"| @{account} | {'❌ fetch failed' if s.fetch_failed else s.posts_analyzed} "
        f"| {s.events_new} | {s.events_merged} | {s.errors} |"
        for account, s in stats.by_account.items()
    ]
    return "\n".join(
        [
            "## Daily sweep",
            "",
            f"{stats.posts_analyzed} posts analyzed · {stats.events_new} new events · "
            f"{stats.events_merged} merged into existing events · {stats.events_discarded} discarded "
            f"(recurring/undated) · {stats.flyers_removed} flyers removed · {stats.errors} errors",
            "",
            "| Account | Posts analyzed | New events | Merged | Errors |",
            "|---|---|---|---|---|",
            *rows,
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days",
        type=int,
        default=config.DEFAULT_LOOKBACK_DAYS,
        help=f"only analyze posts published in the last N days (default {config.DEFAULT_LOOKBACK_DAYS})",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Third-party libraries log every HTTP request at INFO; keep only their warnings.
    for noisy in ("httpx", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    stats = Sweep(lookback_days=args.days).run()

    logging.info(
        "\nDone: %s accounts, %s posts analyzed, %s new events, %s posts merged into existing events, "
        "%s recurring/undated discarded, %s flyers removed, %s errors.",
        stats.accounts,
        stats.posts_analyzed,
        stats.events_new,
        stats.events_merged,
        stats.events_discarded,
        stats.flyers_removed,
        stats.errors,
    )
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_file).open("a", encoding="utf-8") as file:
            file.write(summary_markdown(stats))

    # Individual posts that fail are retried next run; only a sweep where no account could be read is broken.
    if stats.accounts and stats.failed_accounts == stats.accounts:
        raise SystemExit("Every account failed. Check the logs above.")


if __name__ == "__main__":
    main()
