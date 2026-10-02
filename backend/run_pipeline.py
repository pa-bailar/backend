"""Run the daily sweep: collect one-time dance events from the accounts in accounts.txt.

Usage (from the backend folder):
    .venv\\Scripts\\python run_pipeline.py             # posts from the last 7 days
    .venv\\Scripts\\python run_pipeline.py --days 14   # look further back
"""

import argparse
import logging

from pabailar import config
from pabailar.pipeline import Sweep


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

    stats = Sweep(lookback_days=args.days).run()

    logging.info(
        "\nDone: %s accounts, %s posts analyzed, %s events saved, %s recurring/undated discarded, "
        "%s flyers removed, %s errors.",
        stats.accounts,
        stats.posts_analyzed,
        stats.events_saved,
        stats.events_discarded,
        stats.flyers_removed,
        stats.errors,
    )
    if stats.accounts and stats.errors >= stats.accounts:
        raise SystemExit("Every account failed. Check the logs above.")


if __name__ == "__main__":
    main()
