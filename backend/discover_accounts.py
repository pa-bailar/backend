"""Find dance academies in Bogotá among the accounts you follow, from your Instagram data export.

Usage (from the backend folder):
    .venv\\Scripts\\python discover_accounts.py private\\following.html
    .venv\\Scripts\\python discover_accounts.py private\\following.html --max-instagram 300

Resumable: results are cached in private/discovery.json; run it again to continue.
Writes private/discovery_report.md. Everything stays in backend/private/ (git-ignored).
"""

import argparse
import logging
import time
from pathlib import Path

from google.genai import errors as genai_errors

from pabailar import config, discovery, storage
from pabailar.extraction import ExtractionError, ModelPool
from pabailar.instagram import InstagramClient, InstagramError, is_network_error
from pabailar.models import AccountClassification

PRIVATE_DIR = config.BACKEND_DIR / "private"
CACHE_FILE = PRIVATE_DIR / "discovery.json"
REPORT_FILE = PRIVATE_DIR / "discovery_report.md"
# Instagram allows ~200 calls/hour for the app; keep room for the daily sweep.
SECONDS_BETWEEN_INSTAGRAM_CALLS = 20

log = logging.getLogger("discover")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="following.html or following.json from your Instagram export")
    parser.add_argument("--max-instagram", type=int, default=220, help="Instagram profile checks this run")
    parser.add_argument(
        "--max-gemini", type=int, default=250, help="Gemini classifications this run (shares the daily quota)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    following = discovery.parse_following(args.export)
    already = set(storage.read_accounts())
    cache = discovery.load_cache(CACHE_FILE)
    log.info(
        "%s followed accounts · %s already checked · %s already in accounts.txt",
        len(following),
        len(cache),
        len(already),
    )

    instagram = InstagramClient(config.require_env("META_ACCESS_TOKEN"), config.require_env("IG_USER_ID"))
    pool = ModelPool(config.require_env("GEMINI_API_KEY"))

    # 1. Instagram: business or personal? (dance-looking usernames first)
    todo = [u for u in discovery.by_likelihood(following) if u not in cache and u not in already]
    for count, username in enumerate(todo[: args.max_instagram], start=1):
        time.sleep(SECONDS_BETWEEN_INSTAGRAM_CALLS if count > 1 else 0)
        try:
            profile = instagram.fetch_profile(username)
        except InstagramError as error:
            if is_network_error(error):
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
        try:
            classification, model = pool.generate(
                config.TRIAGE_MODELS, [discovery.classify_prompt(account.profile)], AccountClassification
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
