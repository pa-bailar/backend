"""The sweep: fetch recent posts, analyze new ones with Gemini, store one-time events and their flyers."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from google.genai import errors as genai_errors

from . import config, storage
from .extraction import EventExtractor, ExtractionError
from .instagram import InstagramClient, InstagramError, Post, download_image, image_urls, published_at
from .merging import detach_post, find_existing, merge_into
from .models import EventDetails, EventMedia, ExtractedEvent, PostAnalysis, ProcessedPost, StoredEvent

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    accounts: int = 0
    posts_analyzed: int = 0
    events_new: int = 0
    events_merged: int = 0  # a post added to an event already announced by another post
    events_discarded: int = 0  # recurring or without a date
    errors: int = 0
    flyers_removed: int = 0


def _is_publishable(event: ExtractedEvent) -> bool:
    """Only one-time events with a date make it to the website."""
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
    def __init__(self, lookback_days: int):
        self.cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        self.instagram = InstagramClient(config.require_env("META_ACCESS_TOKEN"), config.require_env("IG_USER_ID"))
        self.extractor = EventExtractor(config.require_env("GEMINI_API_KEY"))
        self.events = storage.load_events()
        self.processed = storage.load_processed_posts()
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

        for account in storage.read_accounts():
            self.stats.accounts += 1
            self._process_account(account)

        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        return self.stats

    def _process_account(self, account: str) -> None:
        log.info("== @%s", account)
        try:
            posts = self.instagram.fetch_recent_posts(account)
        except InstagramError as error:
            log.error("   could not fetch posts: %s", error)
            self.stats.errors += 1
            return

        # Oldest first, so a flyer is usually stored before the video or reminder that follows it.
        for post in sorted(posts, key=lambda p: p["timestamp"]):
            published = published_at(post)
            if post["id"] in self.processed or published < self.cutoff:
                continue
            log.info("   %s %-14s %s", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
            self._process_post(account, post, published)

    def _known_events(self, account: str, published: datetime) -> list[StoredEvent]:
        """Events of this account that a new post could be announcing again (not already over)."""
        since = (published - timedelta(days=1)).date().isoformat()
        return [event for event in self.events if event.account == account and (event.date or "") >= since]

    def _process_post(self, account: str, post: Post, published: datetime) -> None:
        try:
            images = [download_image(url) for url in image_urls(post)]
            known = self._known_events(account, published)
            analysis, model = self.extractor.analyze(account, post, published, images, known)
            publishable = (
                [event for event in analysis.events if _is_publishable(event)] if analysis.is_event_post else []
            )
            flyers = _save_flyers(post["id"], publishable, images)
        except (ExtractionError, genai_errors.APIError, OSError) as error:
            # OSError covers network and image errors. The post is not marked as processed,
            # so it's retried on the next run.
            log.error("     failed, will retry next run: %s", error)
            self.stats.errors += 1
            return

        self.stats.posts_analyzed += 1
        self.stats.events_discarded += len(analysis.events) - len(publishable)
        self._record_processed(account, post, analysis, model)
        # If this post was analyzed before, forget what it contributed and add it again below.
        self.events = detach_post(self.events, post["id"])

        if not publishable:
            log.info("     skipped: %s", analysis.reason)
        for position, (candidate, flyer) in enumerate(zip(publishable, flyers, strict=True)):
            self._add_event(account, post, position, candidate, _media_for(post, flyer))

        # Save after every post so progress survives an interrupted run.
        storage.save_events(self.events)
        storage.save_processed_posts(self.processed)

    def _add_event(self, account: str, post: Post, position: int, candidate: ExtractedEvent, media: EventMedia) -> None:
        """Merge into the same event from another post, or store it as a new event."""
        existing = find_existing(self.events, account, candidate)
        if existing:
            self.events[self.events.index(existing)] = merge_into(existing, candidate, media)
            self.stats.events_merged += 1
            log.info("     same event as an earlier post, merged: %s %s", existing.date, existing.title)
            return
        event = StoredEvent(**_details(candidate), id=f"{post['id']}-{position}", account=account, media=[media])
        self.events.append(event)
        self.stats.events_new += 1
        log.info("     event: %s %s | %s [%s]", event.date, event.start_time or "", event.title, event.event_type)

    def _record_processed(self, account: str, post: Post, analysis: PostAnalysis, model: str) -> None:
        self.processed[post["id"]] = ProcessedPost(
            account=account,
            permalink=post["permalink"],
            processed_at=datetime.now(config.BOGOTA_TZ).isoformat(timespec="seconds"),
            is_event_post=analysis.is_event_post,
            reason=analysis.reason,
            model=model,
        )
