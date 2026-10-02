"""The sweep: fetch recent posts, analyze new ones with Gemini, store one-time events and their flyers."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from google.genai import errors as genai_errors

from . import config, storage
from .extraction import EventExtractor, ExtractionError
from .instagram import InstagramClient, InstagramError, Post, download_image, image_urls, published_at
from .models import EventSource, ExtractedEvent, PostAnalysis, ProcessedPost, StoredEvent

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    accounts: int = 0
    posts_analyzed: int = 0
    events_saved: int = 0
    events_discarded: int = 0  # recurring or without a date
    errors: int = 0
    flyers_removed: int = 0


def _is_publishable(event: ExtractedEvent) -> bool:
    """Only one-time events with a date make it to the website."""
    return not event.is_recurring and bool(event.date)


def _to_stored_events(account: str, post: Post, events: list[ExtractedEvent], images: list[bytes]) -> list[StoredEvent]:
    source = EventSource(
        account=account,
        post_id=post["id"],
        permalink=post["permalink"],
        published=post["timestamp"],
        caption=post.get("caption"),
    )
    stored = []
    for index, event in enumerate(events):
        # Each event gets the image that shows it; fall back to the first image.
        image_index = event.image_index if event.image_index is not None and event.image_index < len(images) else 0
        flyer = storage.save_flyer(images[image_index], f"{post['id']}-{image_index}") if images else None
        stored.append(
            StoredEvent(
                **event.model_dump(exclude={"image_index"}),
                id=f"{post['id']}-{index}",
                flyer=flyer,
                source=source,
            )
        )
    return stored


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

        for post in posts:
            published = published_at(post)
            if post["id"] in self.processed or published < self.cutoff:
                continue
            log.info("   %s %-14s %s", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
            self._process_post(account, post, published)

    def _process_post(self, account: str, post: Post, published: datetime) -> None:
        try:
            images = [download_image(url) for url in image_urls(post)]
            analysis, model = self.extractor.analyze(account, post, published, images)
            publishable = [event for event in analysis.events if _is_publishable(event)]
            new_events = _to_stored_events(account, post, publishable, images) if analysis.is_event_post else []
        except (ExtractionError, genai_errors.APIError, OSError) as error:
            # OSError covers network and image errors. The post is not marked as processed,
            # so it's retried on the next run.
            log.error("     failed, will retry next run: %s", error)
            self.stats.errors += 1
            return

        self.stats.posts_analyzed += 1
        self.stats.events_discarded += len(analysis.events) - len(publishable)
        self._record_processed(account, post, analysis, model)
        # Replace any events previously stored for this post.
        self.events = [event for event in self.events if event.source.post_id != post["id"]]

        if new_events:
            self.events += new_events
            self.stats.events_saved += len(new_events)
            for event in new_events:
                log.info(
                    "     event: %s %s | %s [%s]", event.date, event.start_time or "", event.title, event.event_type
                )
        else:
            log.info("     skipped: %s", analysis.reason)

        # Save after every post so progress survives an interrupted run.
        storage.save_events(self.events)
        storage.save_processed_posts(self.processed)

    def _record_processed(self, account: str, post: Post, analysis: PostAnalysis, model: str) -> None:
        self.processed[post["id"]] = ProcessedPost(
            account=account,
            permalink=post["permalink"],
            processed_at=datetime.now(config.BOGOTA_TZ).isoformat(timespec="seconds"),
            is_event_post=analysis.is_event_post,
            reason=analysis.reason,
            model=model,
        )
