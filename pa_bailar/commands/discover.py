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

from pa_bailar import config, discovery, storage, sweep_state
from pa_bailar.gemini import ExtractionError, ModelPool, daily_budget, quota_day
from pa_bailar.instagram import InstagramClient, InstagramError, is_not_visible, is_rate_limited
from pa_bailar.logs import setup_logging
from pa_bailar.models import AccountClassification

CACHE_FILE = config.PRIVATE_DIR / "discovery.json"
REPORT_FILE = config.PRIVATE_DIR / "discovery_report.md"
# The Instagram app's quota is about 200 calls an hour, shared with the daily sweep: ~100 an hour here,
# a pause whenever Meta reports the app past USAGE_PAUSE_PERCENT of it, and none around the sweep's times.
SECONDS_BETWEEN_INSTAGRAM_CALLS = 36
USAGE_PAUSE_PERCENT = 60
USAGE_PAUSE_SECONDS = 10 * 60
QUIET_PAUSE_SECONDS = 5 * 60  # rechecks while the daily sweep has the quota (discovery.near_sweep)

log = logging.getLogger("discover")


def gemini_allowance(pool: ModelPool) -> int:
    """Flash-Lite requests discovery may still use today. The key's quota is shared with the sweeps, whose
    usage is on the sweep-state branch, not in this computer's state/: the daily budget, minus what the
    sweeps used, what discovery used, and config.DISCOVERY_LEAVES_FOR_SWEEPS for today's later sweeps."""
    model = config.TRIAGE_MODELS[0]
    sweep_state.refresh()
    usage = sweep_state.read(config.GEMINI_USAGE_FILE.name, {})
    by_sweeps = usage.get("requests", {}).get(model, 0) if usage.get("day") == quota_day() else 0
    return max(0, daily_budget(model) - by_sweeps - pool.used(model) - config.DISCOVERY_LEAVES_FOR_SWEEPS)


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
        while discovery.near_sweep(config.now_bogota()):
            log.info("  The daily sweep is about to run or running: pausing Instagram checks 5 min")
            time.sleep(QUIET_PAUSE_SECONDS)
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

    # 2. Gemini: classify business accounts with a dance hint, within what the sweeps leave
    to_classify = [a for a in cache.values() if a.status == "business" and a.dance_hint and not a.classification]
    to_classify.sort(key=lambda a: -a.dance_hint)
    allowance = gemini_allowance(pool)
    if to_classify and allowance < args.max_gemini:
        log.info(
            "Gemini: %s classifications today at most, leaving the daily sweeps %s Flash-Lite requests",
            allowance,
            config.DISCOVERY_LEAVES_FOR_SWEEPS,
        )
    for account in to_classify[: min(args.max_gemini, allowance)]:
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
