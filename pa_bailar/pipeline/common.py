"""What every part of the pipeline shares: run statistics, the clients it talks to, its errors, and turning a post's
images into flyers and media records."""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import httpx
from google.genai import errors as genai_errors

from .. import clips, config, storage
from ..changes import ChangeKind, EventChange, change, noted
from ..external import ExternalReport
from ..gemini import ExtractionError, quota_reset
from ..instagram import CallReading, Post, download_image, image_urls, slide_count, video_url
from ..instagram_usage import ReadsSummary, StopReason
from ..models import EventDetails, EventMedia, ExtractedEvent, PostAnalysis, StoredEvent, StoryAnalysis, Triage
from ..text import clock

# Errors that leave a post pending (retried next run) instead of stopping the sweep.
# OSError covers network and image errors; httpx.TransportError, Gemini's timeouts and dropped connections.
RETRYABLE_ERRORS = (ExtractionError, genai_errors.APIError, OSError, httpx.TransportError)


class PostSource(Protocol):
    """Where posts come from: InstagramClient (tests pass a fake). Its readings of Instagram's quota (0-100, Meta's
    usage headers: InstagramClient._read_usage): the share used now, where the sweep stops, and the run's peak with
    each of Meta's measures, which the run records; and its latest call (Meta's time, the usage per header), which
    the sweep records per read (instagram_usage.ReadCosts)."""

    app_usage_percent: int
    peak_usage_percent: int
    peak_usage_detail: dict[str, int]
    last_call: CallReading | None

    def check_token(self) -> str: ...
    def fetch_recent_posts(self, account: str, limit: int = ...) -> list[Post]: ...


class Extractor(Protocol):
    """What reads posts: EventExtractor (tests pass a fake)."""

    def can_extract_with_flash(self) -> bool: ...
    def can_upgrade(self) -> bool: ...
    def flash_ready_at(self) -> float | None: ...
    def reserve_flash(self, share: float) -> None: ...
    def can_analyze(self) -> bool: ...
    def models_unavailable(self) -> list[str]: ...
    def requests_this_run(self) -> dict[str, int]: ...
    def external_report(self) -> ExternalReport: ...
    def triage(
        self, account: str, post: Post, published: datetime, images: list[bytes], rules: str = ...
    ) -> tuple[Triage, str]: ...
    def extract(
        self,
        account: str,
        post: Post,
        published: datetime,
        images: list[bytes],
        known_events: list[StoredEvent],
        allow_provisional: bool = ...,
        rules: str = ...,
    ) -> tuple[PostAnalysis, str, bool]: ...
    def extract_story(
        self,
        images: list[bytes],
        taken: datetime,
        account: str | None,
        notes: str | None,
        known_events: list[StoredEvent],
    ) -> tuple[StoryAnalysis, str, bool]: ...


@dataclass
class AccountStats:
    posts_analyzed: int = 0
    events_new: int = 0
    events_merged: int = 0
    pending: int = 0  # posts left for the next run (no quota or time left, or an error)
    errors: int = 0  # real failures only: waiting for quota or time isn't an error
    backfill: bool = False  # this run was (part of) the account's first, deeper sweep
    fetch_failed: bool = False
    latest_post: str | None = None  # date (YYYY-MM-DD) of the account's newest post, to notice abandoned accounts


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
    # Flash's reading against a lighter model's, on events only lighter models had read (Sweep._audit_upgrade):
    # "compared" events, "dropped" ones, and per field how many Flash changed (date, start_time, title…).
    upgrade_changes: dict[str, int] = field(default_factory=dict)  # a dict: asdict() would mangle a Counter
    reanalyzed: int = 0  # posts analyzed again because their caption was edited
    pending: int = 0
    errors: int = 0
    events_expired: int = 0  # ended more than EVENT_RETENTION_DAYS ago
    processed_forgotten: int = 0  # analyzed-post records older than PROCESSED_RETENTION_DAYS
    flyers_removed: int = 0
    rate_limited: bool = False  # Instagram throttled the app: accounts after that one wait for the next run
    out_of_time: bool = False  # the run used its time budget: some posts wait for the next run
    gemini_requests: dict[str, int] = field(default_factory=dict)  # per Gemini model, and per external provider
    models_unavailable: list[str] = field(default_factory=list)  # Gemini models this key couldn't use
    external: ExternalReport = field(default_factory=ExternalReport)  # the last resort (Groq, OpenRouter) this run
    due_accounts: list[str] = field(default_factory=list)  # whose turn it was (the ones not read wait for the next run)
    instagram_usage: int = 0  # the highest share of Instagram's quota used during the run (0-100)
    instagram_usage_detail: dict[str, int] = field(default_factory=dict)  # its measures (instagram.USAGE_MEASURES)
    instagram_reads: ReadsSummary | None = None  # Meta's time and the quota's share per read (instagram_usage.py)
    instagram_stop: StopReason | None = None  # why it stopped reading accounts early, if it did
    by_account: dict[str, AccountStats] = field(default_factory=dict)
    # What happened to which event, one change per event by id (changes.py): the admin page's history. Not in meta.json.
    changes: dict[str, EventChange] = field(default_factory=dict)

    def note(self, kind: ChangeKind, event: StoredEvent, detail: str | None = None) -> None:
        """Note what happened to an event this run (changes.noted: one per event)."""
        noted(self.changes, change(kind, event, detail))

    def for_meta(self) -> dict[str, Any]:
        """The run's statistics for the site's meta.json (storage.save_meta): without the changes, the admin page's."""
        stats = asdict(self)
        del stats["changes"]
        return stats

    def account(self, name: str) -> AccountStats:
        return self.by_account.setdefault(name, AccountStats())

    def count(self, account: str, field_name: str, amount: int = 1) -> None:
        """Add to a counter of the run and, when it has one, of the account too."""
        setattr(self, field_name, getattr(self, field_name) + amount)
        account_stats = self.account(account)
        if hasattr(account_stats, field_name):
            setattr(account_stats, field_name, getattr(account_stats, field_name) + amount)

    @property
    def failed_accounts(self) -> int:
        return sum(1 for stats in self.by_account.values() if stats.fetch_failed)


class AddPostError(Exception):
    """add_post couldn't do it: the message says why, in Spanish, for the admin tools' answer."""


def download_images(post: Post) -> list[bytes]:
    """The post's images (photo, carousel slides or a video's preview frame). Raises OSError."""
    return [download_image(url) for url in image_urls(post)]


def caption_hash(post: Post) -> str:
    """Short fingerprint of a post's caption, to notice when the academy edits it."""
    return hashlib.sha256((post.get("caption") or "").encode()).hexdigest()[:16]


def has_ended(event: EventDetails, today: date) -> bool:
    """Whether the event's last day (its end_date, a series' last session, else its date) is before today."""
    return bool(event.last_day) and (event.last_day or "") < today.isoformat()


def unpublishable(event: ExtractedEvent) -> list[str]:
    """Why an extracted event can't be published whatever else is stored (run normalize_event first), in Spanish,
    for the post's record: recurring, without a title or valid date, or placed in another city or country."""
    reasons = []
    if event.is_recurring:
        reasons.append("recurrente")
    elif not event.date or not event.title:
        reasons.append("sin fecha")
    if event.in_bogota == "no":
        reasons.append("fuera de Bogotá")
    return reasons


def no_quota_message() -> str:
    return f"No queda cuota de Gemini hoy: inténtalo después de las {clock(quota_reset(config.now_bogota()))}."


def _image_index(event: ExtractedEvent, image_count: int) -> int:
    """The image Gemini says shows the event; the first image if it gave none or an invalid one."""
    if event.image_index is not None and 0 <= event.image_index < image_count:
        return event.image_index
    return 0


Flyer = tuple[str, int] | None  # a saved flyer's path and the slide (image index) it comes from


def save_flyers(post_id: str, events: list[ExtractedEvent], images: list[bytes]) -> list[Flyer]:
    """The flyer of each event: the image Gemini says shows it. Each image is saved once, so events
    announced together on one image (e.g. a monthly schedule) share that file."""
    if not images:
        return [None] * len(events)
    saved: dict[int, str] = {}
    flyers: list[Flyer] = []
    for event in events:
        image_index = _image_index(event, len(images))
        if image_index not in saved:
            saved[image_index] = storage.save_flyer(images[image_index], f"{post_id}-{image_index}")
        flyers.append((saved[image_index], image_index))
    return flyers


def clip_for(post: Post, image_index: int) -> str | None:
    """A preview clip when the flyer's slide is a video (clips.py), else None."""
    url = video_url(post, image_index)
    return clips.make_clip(url, f"{post['id']}-{image_index}") if url else None


def media_for(post: Post, flyer: Flyer) -> EventMedia:
    return EventMedia(
        post_id=post["id"],
        permalink=post["permalink"],
        media_type=post["media_type"],
        published=post["timestamp"],
        flyer=flyer[0] if flyer else None,
        caption=post.get("caption"),
        preview=clip_for(post, flyer[1]) if flyer else None,
        slides=slide_count(post),
    )


def flyer_slide(flyer: str) -> int:
    """ "flyers/<post id>-<slide>.webp" → the slide; 0 for flyers saved before slides were in their names."""
    stem = flyer.rsplit("/", 1)[-1].removesuffix(".webp")
    _, dash, slide = stem.rpartition("-")
    return int(slide) if dash and slide.isdigit() else 0
