"""The sweep: fetch recent posts, analyze new ones with Gemini, store one-time events and their flyers.

Per account:
  - A new account gets a deeper first sweep (its last BACKFILL_POSTS posts from the last BACKFILL_DAYS
    days); once all of them are analyzed it joins the regular sweep (last DEFAULT_LOOKBACK_DAYS days).
  - Each new post is triaged by the light model; only posts that announce events are extracted by Flash.
  - Posts extracted provisionally (Flash was out of quota) are re-extracted with Flash when there's budget.
  - Posts that couldn't be analyzed (no quota left today, network errors) stay pending for the next run.

After all accounts: events older than EVENT_RETENTION_DAYS are deleted, then every flyer no event uses.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from google.genai import errors as genai_errors

from . import config, storage
from .extraction import EventExtractor, ExtractionError
from .instagram import InstagramClient, InstagramError, Post, download_image, image_urls, published_at
from .merging import detach_post, find_existing, merge_into
from .models import (
    AccountState,
    EventDetails,
    EventMedia,
    ExtractedEvent,
    PostAnalysis,
    ProcessedPost,
    StoredEvent,
)
from .normalize import normalize_event

log = logging.getLogger(__name__)

# Errors that leave a post pending (retried next run) instead of stopping the sweep.
# OSError covers network and image errors.
RETRYABLE_ERRORS = (ExtractionError, genai_errors.APIError, OSError)


@dataclass
class AccountStats:
    posts_analyzed: int = 0
    events_new: int = 0
    events_merged: int = 0
    pending: int = 0  # posts left for the next run (no quota, errors)
    errors: int = 0
    backfill: bool = False  # this run was (part of) the account's first, deeper sweep
    fetch_failed: bool = False


@dataclass
class RunStats:
    accounts: int = 0
    posts_analyzed: int = 0
    posts_triaged_out: int = 0  # not events, decided by the light model alone
    events_new: int = 0
    events_merged: int = 0  # a post added to an event already announced by another post
    events_discarded: int = 0  # recurring or without a date
    provisional: int = 0  # posts extracted by the light model this run
    upgraded: int = 0  # provisional posts re-extracted with Flash this run
    pending: int = 0
    errors: int = 0
    events_expired: int = 0  # dated more than EVENT_RETENTION_DAYS ago
    processed_forgotten: int = 0  # analyzed-post records older than PROCESSED_RETENTION_DAYS
    flyers_removed: int = 0
    gemini_requests: dict[str, int] = field(default_factory=dict)
    by_account: dict[str, AccountStats] = field(default_factory=dict)

    def account(self, name: str) -> AccountStats:
        return self.by_account.setdefault(name, AccountStats())

    @property
    def failed_accounts(self) -> int:
        return sum(1 for stats in self.by_account.values() if stats.fetch_failed)


def _is_publishable(event: ExtractedEvent) -> bool:
    """Only one-time events with a valid date make it to the website (run normalize_event first)."""
    return not event.is_recurring and bool(event.date)


def _image_index(event: ExtractedEvent, image_count: int) -> int:
    """The image Gemini says shows the event; the first image if it gave none or an invalid one."""
    if event.image_index is not None and 0 <= event.image_index < image_count:
        return event.image_index
    return 0


def _save_flyers(post_id: str, events: list[ExtractedEvent], images: list[bytes]) -> list[str | None]:
    """The flyer of each event: the image Gemini says shows it. Each image is saved once, so events
    announced together on one image (e.g. a monthly schedule) share that file."""
    if not images:
        return [None] * len(events)
    saved: dict[int, str] = {}
    flyers: list[str | None] = []
    for event in events:
        image_index = _image_index(event, len(images))
        if image_index not in saved:
            saved[image_index] = storage.save_flyer(images[image_index], f"{post_id}-{image_index}")
        flyers.append(saved[image_index])
    return flyers


def _media_for(post: Post, flyer: str | None) -> EventMedia:
    return EventMedia(
        post_id=post["id"],
        permalink=post["permalink"],
        media_type=post["media_type"],
        published=post["timestamp"],
        flyer=flyer,
        caption=post.get("caption"),
    )


def _details(event: ExtractedEvent) -> dict:
    return event.model_dump(include=set(EventDetails.model_fields))


class Sweep:
    def __init__(
        self,
        lookback_days: int,
        instagram: InstagramClient | None = None,
        extractor: EventExtractor | None = None,
    ):
        """Clients are built from the environment unless given (tests pass fakes)."""
        self.lookback = timedelta(days=lookback_days)
        self.instagram = instagram or InstagramClient(
            config.require_env("META_ACCESS_TOKEN"), config.require_env("IG_USER_ID")
        )
        self.extractor = extractor or EventExtractor(config.require_env("GEMINI_API_KEY"))
        self.events = storage.load_events()
        self.processed = storage.load_processed_posts()
        self.accounts = storage.load_account_state()
        self.stats = RunStats()

    def run(self) -> RunStats:
        try:
            username = self.instagram.check_token()
        except InstagramError as error:
            raise SystemExit(
                f"Instagram token invalid ({error}). Generate a new one, run refresh_token.py "
                "and update META_ACCESS_TOKEN (backend/.env and the GitHub secret)."
            ) from error
        log.info("Instagram token OK (@%s)", username)

        for account in self._accounts_in_order():
            self.stats.accounts += 1
            self._process_account(account)

        self._apply_retention()
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))
        return self.stats

    def _accounts_in_order(self) -> list[str]:
        """Accounts in their regular sweep first, so a backlog of new accounts (which can take several
        days of quota) never uses up the quota for today's posts of the accounts already followed."""

        def is_new(account: str) -> bool:
            state = self.accounts.get(account)
            return state is None or not state.backfill_done

        return sorted(storage.read_accounts(), key=is_new)  # stable: keeps accounts.txt order within each group

    def _apply_retention(self) -> None:
        """Delete long-past events and forget old analyzed posts, so data and flyers don't grow forever."""
        now = datetime.now(config.BOGOTA_TZ)
        oldest_date = (now - timedelta(days=config.EVENT_RETENTION_DAYS)).date().isoformat()
        kept = [event for event in self.events if not event.date or event.date >= oldest_date]
        self.stats.events_expired = len(self.events) - len(kept)
        self.events = kept

        # Never forget a post the lookback could still fetch (e.g. a manual run with --days 60).
        keep_days = max(config.PROCESSED_RETENTION_DAYS, self.lookback.days + 1)
        oldest_record = now - timedelta(days=keep_days)
        old = [pid for pid, rec in self.processed.items() if datetime.fromisoformat(rec.processed_at) < oldest_record]
        for post_id in old:
            del self.processed[post_id]
        self.stats.processed_forgotten = len(old)

        if self.stats.events_expired or old:
            log.info(
                "Retention: %s past events deleted, %s old post records forgotten", self.stats.events_expired, len(old)
            )
            self._save()

    # ---------- per account ----------

    def _process_account(self, account: str) -> None:
        state = self.accounts.setdefault(
            account, AccountState(first_seen=datetime.now(config.BOGOTA_TZ).date().isoformat())
        )
        backfill = not state.backfill_done
        account_stats = self.stats.account(account)
        account_stats.backfill = backfill
        log.info("== @%s%s", account, " (new account: deeper first sweep)" if backfill else "")

        try:
            limit = config.BACKFILL_POSTS if backfill else config.POSTS_PER_ACCOUNT
            posts = self.instagram.fetch_recent_posts(account, limit=limit)
        except InstagramError as error:
            log.error("   could not fetch posts: %s", error)
            self.stats.errors += 1
            account_stats.errors += 1
            account_stats.fetch_failed = True
            return

        window = timedelta(days=config.BACKFILL_DAYS) if backfill else self.lookback
        cutoff = datetime.now(UTC) - window
        # Oldest first, so a flyer is usually stored before the video or reminder that follows it.
        for post in sorted(posts, key=lambda p: p["timestamp"]):
            published = published_at(post)
            if published < cutoff:
                continue
            record = self.processed.get(post["id"])
            if record is None:
                log.info("   %s %-14s %s", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
                if not self._analyze_new_post(account, post, published):
                    account_stats.pending += 1
                    self.stats.pending += 1
            elif record.provisional and self.extractor.can_extract_with_flash():
                log.info("   %s upgrading provisional analysis %s", f"{published:%Y-%m-%d}", post["permalink"])
                self._upgrade_post(account, post, published)

        if backfill and account_stats.pending == 0:
            state.backfill_done = True
            log.info("   first sweep complete: from now on, regular sweep")
        storage.save_account_state(self.accounts)

    # ---------- per post ----------

    def _analyze_new_post(self, account: str, post: Post, published: datetime) -> bool:
        """Triage, then extract if it's an event. False when the post must be retried next run."""
        try:
            images = [download_image(url) for url in image_urls(post)]
        except OSError as error:
            return self._retry_later(account, f"could not download images: {error}")

        try:
            triage, triage_model = self.extractor.triage(account, post, published, images)
        except RETRYABLE_ERRORS as error:
            # Triage unavailable: let the extraction decide on its own.
            log.info("     triage unavailable (%s), extracting directly", error)
            triage, triage_model = None, None

        if triage is not None and not triage.is_event_post:
            self.stats.posts_analyzed += 1
            self.stats.posts_triaged_out += 1
            self.stats.account(account).posts_analyzed += 1
            self._record_processed(account, post, False, triage.reason, triage_model, provisional=False)
            self._save()
            log.info("     not an event: %s", triage.reason)
            return True

        try:
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(account, post, published, images, known)
        except RETRYABLE_ERRORS as error:
            return self._retry_later(account, str(error))

        self._store_analysis(account, post, images, analysis, model, provisional)
        return True

    def _upgrade_post(self, account: str, post: Post, published: datetime) -> None:
        """Re-extract a provisional post with Flash; keep the provisional result if that fails."""
        try:
            images = [download_image(url) for url in image_urls(post)]
            known = self._known_events(account, published)
            analysis, model, _ = self.extractor.extract(
                account, post, published, images, known, allow_provisional=False
            )
        except RETRYABLE_ERRORS as error:
            log.info("     upgrade postponed: %s", error)
            return
        self.stats.upgraded += 1
        self._store_analysis(account, post, images, analysis, model, provisional=False, count_as_new=False)

    def _store_analysis(
        self,
        account: str,
        post: Post,
        images: list[bytes],
        analysis: PostAnalysis,
        model: str,
        provisional: bool,
        count_as_new: bool = True,
    ) -> None:
        cleaned = [normalize_event(event) for event in analysis.events]
        publishable = [event for event in cleaned if _is_publishable(event)] if analysis.is_event_post else []
        try:
            flyers = _save_flyers(post["id"], publishable, images)
        except OSError as error:
            self._retry_later(account, f"could not save flyer: {error}")
            return

        if count_as_new:
            self.stats.posts_analyzed += 1
            self.stats.account(account).posts_analyzed += 1
        self.stats.events_discarded += len(analysis.events) - len(publishable)
        if provisional:
            self.stats.provisional += 1
            log.info("     extracted by %s (provisional: Flash out of quota, upgraded on a later run)", model)
        self._record_processed(account, post, analysis.is_event_post, analysis.reason, model, provisional)
        # If this post was analyzed before, forget what it contributed and add it again below.
        self.events = detach_post(self.events, post["id"])

        if not publishable:
            log.info("     skipped: %s", analysis.reason)
        for position, (candidate, flyer) in enumerate(zip(publishable, flyers, strict=True)):
            self._add_event(account, post, position, candidate, _media_for(post, flyer), count=count_as_new)
        self._save()

    def _retry_later(self, account: str, reason: str) -> bool:
        log.warning("     left for the next run: %s", reason)
        self.stats.errors += 1
        self.stats.account(account).errors += 1
        return False

    def _known_events(self, account: str, published: datetime) -> list[StoredEvent]:
        """Events of this account that a new post could be announcing again (not already over)."""
        since = (published - timedelta(days=1)).date().isoformat()
        return [event for event in self.events if event.account == account and (event.date or "") >= since]

    def _add_event(
        self,
        account: str,
        post: Post,
        position: int,
        candidate: ExtractedEvent,
        media: EventMedia,
        count: bool = True,
    ) -> None:
        """Merge into the same event from another post, or store it as a new event.

        `count=False` for re-extractions (upgrades), which replace events instead of adding new ones.
        """
        existing = find_existing(self.events, account, candidate, post["id"])
        if existing:
            self.events[self.events.index(existing)] = merge_into(existing, candidate, media)
            if count:
                self.stats.events_merged += 1
                self.stats.account(account).events_merged += 1
            log.info("     same event as an earlier post, merged: %s %s", existing.date, existing.title)
            return
        event = StoredEvent(**_details(candidate), id=f"{post['id']}-{position}", account=account, media=[media])
        self.events.append(event)
        if count:
            self.stats.events_new += 1
            self.stats.account(account).events_new += 1
        log.info("     event: %s %s | %s [%s]", event.date, event.start_time or "", event.title, event.event_type)

    def _record_processed(
        self, account: str, post: Post, is_event_post: bool, reason: str, model: str, provisional: bool
    ) -> None:
        self.processed[post["id"]] = ProcessedPost(
            account=account,
            permalink=post["permalink"],
            processed_at=datetime.now(config.BOGOTA_TZ).isoformat(timespec="seconds"),
            is_event_post=is_event_post,
            reason=reason,
            model=model,
            provisional=provisional,
        )

    def _save(self) -> None:
        """Save after every post so progress survives an interrupted run."""
        storage.save_events(self.events)
        storage.save_processed_posts(self.processed)
