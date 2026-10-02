"""discover: find dance academies in Bogotá among the accounts you follow, from your Instagram export.

Usage (from the repository root):
    .venv\\Scripts\\python -m pa_bailar discover private\\following.html
    .venv\\Scripts\\python -m pa_bailar discover private\\following.html --max-instagram 100

Resumable: results are cached in private/discovery.json; run it again to continue.
Writes private/discovery_report.md. Everything stays in private/ (git-ignored).
"""

import argparse
import logging
import time
from pathlib import Path

from google.genai import errors as genai_errors

from pa_bailar import config, discovery, storage
from pa_bailar.gemini import ExtractionError, ModelPool
from pa_bailar.instagram import InstagramClient, InstagramError, is_not_visible, is_rate_limited
from pa_bailar.logs import setup_logging
from pa_bailar.models import AccountClassification

CACHE_FILE = config.PRIVATE_DIR / "discovery.json"
REPORT_FILE = config.PRIVATE_DIR / "discovery_report.md"
# The Instagram app's quota is about 200 calls an hour, shared with the daily sweep: ~100 an hour here,
# and a pause whenever Meta reports the app past USAGE_PAUSE_PERCENT of it.
SECONDS_BETWEEN_INSTAGRAM_CALLS = 36
USAGE_PAUSE_PERCENT = 60
USAGE_PAUSE_SECONDS = 10 * 60

log = logging.getLogger("discover")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar discover", description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="following.html or following.json from your Instagram export")
    parser.add_argument("--max-instagram", type=int, default=220, help="Instagram profile checks this run")
    parser.add_argument(
        "--max-gemini", type=int, default=250, help="Gemini classifications this run (shares the daily quota)"
    )
    args = parser.parse_args(argv)
    setup_logging()

    following = discovery.parse_following(args.export)
    already = set(storage.read_accounts())
    cache = discovery.load_cache(CACHE_FILE)
    log.info(
        "%s followed accounts · %s already checked · %s already in accounts.txt",
        len(following),
        len(cache),
        len(already),
    )

    instagram = InstagramClient.from_env()
    pool = ModelPool(config.require_env("GEMINI_API_KEY"))

    # 1. Instagram: business or personal? (dance-looking usernames first)
    todo = [u for u in discovery.by_likelihood(following) if u not in cache and u not in already]
    for count, username in enumerate(todo[: args.max_instagram], start=1):
        time.sleep(SECONDS_BETWEEN_INSTAGRAM_CALLS if count > 1 else 0)
        while instagram.app_usage_percent >= USAGE_PAUSE_PERCENT:
            log.info("  Instagram app at %s%% of its hourly quota: pausing 10 min", instagram.app_usage_percent)
            time.sleep(USAGE_PAUSE_SECONDS)
            instagram.app_usage_percent = 0  # the next call reports the real value again
        try:
            profile = instagram.fetch_profile(username)
        except InstagramError as error:
            if is_rate_limited(error):
                log.warning("Instagram rate limit reached (%s): stopping. Run again in an hour to continue.", error)
                break
            if not is_not_visible(error):
                log.warning("  @%s: %s (will retry next run)", username, error)
                continue
            cache[username] = discovery.DiscoveredAccount(username=username, status="personal")
        else:
            hint = discovery.profile_hint(profile)
            cache[username] = discovery.DiscoveredAccount(
                username=username, status="business", profile=profile, dance_hint=hint
            )
            log.info("  [%s/%s] @%s business%s", count, min(len(todo), args.max_instagram), username,
                     f", dance hint {hint}" if hint else "")  # fmt: skip
        discovery.save_cache(CACHE_FILE, cache)

    # 2. Gemini: classify business accounts with a dance hint
    to_classify = [a for a in cache.values() if a.status == "business" and a.dance_hint and not a.classification]
    to_classify.sort(key=lambda a: -a.dance_hint)
    for account in to_classify[: args.max_gemini]:
        if account.profile is None:  # business accounts always have one; nothing to classify otherwise
            continue
        try:
            classification, model = pool.generate(
                config.TRIAGE_MODELS, discovery.classify_prompt(account.profile), AccountClassification
            )
        except (ExtractionError, genai_errors.APIError) as error:
            log.warning("  classification stopped: %s (run again tomorrow to continue)", error)
            break
        account.classification, account.classified_by = classification, model
        log.info("  @%s → %s, Bogotá: %s", account.username, classification.kind, classification.in_bogota)
        discovery.save_cache(CACHE_FILE, cache)

    REPORT_FILE.write_text(discovery.report_markdown(cache, already, len(following)), encoding="utf-8")
    remaining = len([u for u in following if u not in cache and u not in already])
    log.info("\nReport: %s · %s accounts still to check on Instagram", REPORT_FILE, remaining)


if __name__ == "__main__":
    main()
