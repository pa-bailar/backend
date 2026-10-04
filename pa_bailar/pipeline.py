"""The sweep: fetch recent posts, analyze new ones with Gemini, store one-time events and their flyers.

Per account:
  - A new account gets a deeper first sweep (its last BACKFILL_POSTS posts from the last BACKFILL_DAYS
    days); once all of them are analyzed it joins the regular sweep (last DEFAULT_LOOKBACK_DAYS days).
  - Each new post is triaged by the light model; only posts that announce events are extracted by Flash.
  - Posts extracted provisionally (Flash was out of quota) are re-extracted with Flash when there's budget.
  - Posts that couldn't be analyzed (no quota left today, network errors) stay pending for the next run.
  - A post whose caption was edited since it was analyzed (e.g. the venue added) is analyzed again.
  - After MAX_RUN_MINUTES no new Gemini work starts; the rest waits for the next run.

After all accounts: events whose last day is older than EVENT_RETENTION_DAYS are deleted, then every flyer no
event uses.
"""

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

import httpx
from google.genai import errors as genai_errors

from . import clips, config, links, public_post, storage
from .extraction import EventExtractor
from .gemini import ExtractionError, GeminiKeyError, QuotaExhaustedError, RejectedRequestError, quota_reset
from .ids import new_event_id
from .instagram import (
    InstagramClient,
    InstagramError,
    Post,
    download_image,
    image_urls,
    is_not_visible,
    is_rate_limited,
    published_at,
    slide_count,
    video_url,
)
from .merging import detach_post, find_existing, merge_into
from .models import (
    AccountState,
    EventDetails,
    EventMedia,
    ExtractedEvent,
    PostAnalysis,
    PostOutcome,
    ProcessedPost,
    StoredEvent,
    Triage,
)
from .normalize import normalize_event
from .text import clock

log = logging.getLogger(__name__)

# Errors that leave a post pending (retried next run) instead of stopping the sweep.
# OSError covers network and image errors; httpx.TransportError, Gemini's timeouts and dropped connections.
RETRYABLE_ERRORS = (ExtractionError, genai_errors.APIError, OSError, httpx.TransportError)


class PostSource(Protocol):
    """Where posts come from: InstagramClient (tests pass a fake)."""

    def check_token(self) -> str: ...
    def fetch_recent_posts(self, account: str, limit: int = ...) -> list[Post]: ...


class Extractor(Protocol):
    """What reads posts: EventExtractor (tests pass a fake)."""

    def can_extract_with_flash(self) -> bool: ...
    def can_analyze(self) -> bool: ...
    def models_unavailable(self) -> list[str]: ...
    def requests_this_run(self) -> dict[str, int]: ...
    def triage(self, account: str, post: Post, published: datetime, images: list[bytes]) -> tuple[Triage, str]: ...
    def extract(
        self,
        account: str,
        post: Post,
        published: datetime,
        images: list[bytes],
        known_events: list[StoredEvent],
        allow_provisional: bool = ...,
    ) -> tuple[PostAnalysis, str, bool]: ...


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
    reanalyzed: int = 0  # posts analyzed again because their caption was edited
    pending: int = 0
    errors: int = 0
    events_expired: int = 0  # ended more than EVENT_RETENTION_DAYS ago
    processed_forgotten: int = 0  # analyzed-post records older than PROCESSED_RETENTION_DAYS
    flyers_removed: int = 0
    rate_limited: bool = False  # Instagram throttled the app: accounts after that one wait for the next run
    out_of_time: bool = False  # the run used its time budget: some posts wait for the next run
    gemini_requests: dict[str, int] = field(default_factory=dict)
    models_unavailable: list[str] = field(default_factory=list)  # Gemini models this key couldn't use
    due_accounts: list[str] = field(default_factory=list)  # whose turn it was (the ones not read wait for the next run)
    instagram_usage: int = 0  # share of Instagram's quota used when the run ended (0-100)
    by_account: dict[str, AccountStats] = field(default_factory=dict)

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


def _download_images(post: Post) -> list[bytes]:
    """The post's images (photo, carousel slides or a video's preview frame). Raises OSError."""
    return [download_image(url) for url in image_urls(post)]


def _caption_hash(post: Post) -> str:
    """Short fingerprint of a post's caption, to notice when the academy edits it."""
    return hashlib.sha256((post.get("caption") or "").encode()).hexdigest()[:16]


def _is_publishable(event: ExtractedEvent) -> bool:
    """Only one-time events with a title and a valid date make it to the website (run normalize_event first)."""
    return not event.is_recurring and bool(event.date) and bool(event.title)


def _no_quota_message() -> str:
    return f"No queda cuota de Gemini hoy: inténtalo después de las {clock(quota_reset(config.now_bogota()))}."


def _image_index(event: ExtractedEvent, image_count: int) -> int:
    """The image Gemini says shows the event; the first image if it gave none or an invalid one."""
    if event.image_index is not None and 0 <= event.image_index < image_count:
        return event.image_index
    return 0


Flyer = tuple[str, int] | None  # a saved flyer's path and the slide (image index) it comes from


def _save_flyers(post_id: str, events: list[ExtractedEvent], images: list[bytes]) -> list[Flyer]:
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


def _clip_for(post: Post, image_index: int) -> str | None:
    """A preview clip when the flyer's slide is a video (clips.py), else None."""
    url = video_url(post, image_index)
    return clips.make_clip(url, f"{post['id']}-{image_index}") if url else None


def _media_for(post: Post, flyer: Flyer) -> EventMedia:
    return EventMedia(
        post_id=post["id"],
        permalink=post["permalink"],
        media_type=post["media_type"],
        published=post["timestamp"],
        flyer=flyer[0] if flyer else None,
        caption=post.get("caption"),
        preview=_clip_for(post, flyer[1]) if flyer else None,
        slides=slide_count(post),
    )


def _flyer_slide(flyer: str) -> int:
    """ "flyers/<post id>-<slide>.webp" → the slide; 0 for flyers saved before slides were in their names."""
    stem = flyer.rsplit("/", 1)[-1].removesuffix(".webp")
    _, dash, slide = stem.rpartition("-")
    return int(slide) if dash and slide.isdigit() else 0


class AddPostError(Exception):
    """add_post couldn't do it: the message says why, in Spanish, for the admin tools' answer."""


@dataclass
class AddedPost:
    """What add_post did, for the admin tools' answer."""

    account: str
    account_added: bool  # it wasn't swept: added to accounts.txt (its older posts load on the next sweep)
    permalink: str
    outcome: str | None  # ProcessedPost.outcome
    reason: str  # Gemini's
    model: str | None
    provisional: bool
    events: list[StoredEvent]  # the events it became or joined, as stored
    public: bool = False  # read from its public page (public_post.py): the API couldn't give it
    readable: bool = True  # the API can read the account (so it's swept); False: personal or private
    unchanged: bool = False  # analyzed before and unchanged: not read again (no Gemini request; `again` forces it)


# What a post analyzed before became, when reading it again by hand can't change it (caption unchanged):
# published or merged, or discarded (recurring, no date) by the extraction itself. "not_event" (the filter)
# and "rejected" are read again: whoever asks says it's an event, and the extraction skips the filter.
SETTLED_OUTCOMES = ("event", "merged", "discarded")


def hours_overdue(state: AccountState | None, now: datetime) -> float:
    """How long past its turn an account is (negative: not its turn yet). Never read: always due."""
    if state is None or state.last_swept_at is None:
        return float("inf")
    quiet = (
        state.latest_post is not None
        and (now.date() - date.fromisoformat(state.latest_post)).days >= config.QUIET_AFTER_DAYS
    )
    every = config.QUIET_SWEEP_EVERY_HOURS if quiet else config.SWEEP_EVERY_HOURS
    return (now - datetime.fromisoformat(state.last_swept_at)).total_seconds() / 3600 - every


def _days(event: EventDetails) -> str:
    """An event's day for the log: its date, or first → last day."""
    return f"{event.date} → {event.end_date}" if event.end_date else str(event.date)


def _details(event: ExtractedEvent) -> dict[str, Any]:
    return event.model_dump(include=set(EventDetails.model_fields))


class Sweep:
    def __init__(
        self,
        lookback_days: int,
        instagram: PostSource | None = None,
        extractor: Extractor | None = None,
        all_accounts: bool = False,
    ):
        """Clients are built from the environment unless given (tests pass fakes). `all_accounts` reads every
        account now, whether it's its turn or not (a manual full sweep)."""
        self.all_accounts = all_accounts
        self.lookback = timedelta(days=lookback_days)
        self.instagram = instagram or InstagramClient.from_env()
        self.extractor = extractor or EventExtractor(config.require_env("GEMINI_API_KEY"))
        self.events = storage.load_events()
        self.processed = storage.load_processed_posts()
        self.accounts = storage.load_account_state()
        self.stats = RunStats()
        self.started = time.monotonic()
        self.time_up_logged = False
        self.rate_limited = False  # Meta is throttling the app: the remaining accounts wait for the next run

    def run(self) -> RunStats:
        try:
            username = self.instagram.check_token()
        except InstagramError as error:
            raise SystemExit(
                f"Instagram token invalid ({error}). Generate a new one, run `python -m pa_bailar refresh-token` "
                "and update META_ACCESS_TOKEN (.env and the GitHub secret)."
            ) from error
        log.info("Instagram token OK (@%s)", username)

        due = self._due_accounts()
        self.stats.due_accounts = due
        share = self._share_per_run()
        if len(due) > share:
            log.info("%s accounts' turn: %s this run, the rest first next run", len(due), share)
        for account in due[:share]:
            usage = getattr(self.instagram, "app_usage_percent", 0)
            if usage >= config.INSTAGRAM_USAGE_STOP:
                log.warning("Instagram quota %s%% used: the remaining accounts wait for the next run", usage)
                self.rate_limited = True
                break
            if self.rate_limited:
                log.warning("Instagram rate limit reached: the remaining accounts wait for the next run")
                break
            self.stats.accounts += 1
            try:
                self._process_account(account)
            except GeminiKeyError as error:  # every post would fail: stop, and let the run fail loudly
                raise SystemExit(
                    f"Gemini API key doesn't work ({error}). Create a new key in Google AI Studio and update "
                    "GEMINI_API_KEY (.env and the GitHub secret)."
                ) from error
            except Exception:  # unexpected (e.g. a malformed answer): lose this account's run, not everyone's
                log.exception("   unexpected error with @%s, continuing with the next account", account)
                self.stats.count(account, "errors")

        self._apply_retention()
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        self.stats.models_unavailable = self.extractor.models_unavailable()
        self.stats.rate_limited = self.rate_limited
        self.stats.instagram_usage = getattr(self.instagram, "app_usage_percent", 0)
        self.stats.out_of_time = self.time_up_logged
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))
        return self.stats

    def _share_per_run(self) -> int:
        """How many accounts one sweep reads: its share of the day's sweeps, plus a margin for late ones."""
        if self.all_accounts:
            return len(storage.read_accounts())
        runs_per_day = max(1, len(config.SWEEP_TIMES))
        return -(-len(storage.read_accounts()) // runs_per_day) + config.EXTRA_ACCOUNTS_PER_RUN

    def _hours_overdue(self, account: str, now: datetime) -> float:
        return hours_overdue(self.accounts.get(account), now)

    def _due_accounts(self) -> list[str]:
        """The accounts whose turn it is, in reading order: accounts in their regular sweep before new ones (a
        new account's first, deeper sweep can take days of quota), and within each, those that waited longest
        first. So an account a sweep didn't reach (its share, Instagram's limit) is first next time."""
        now = config.now_bogota()
        followed = storage.read_accounts()
        due = followed if self.all_accounts else [a for a in followed if self._hours_overdue(a, now) >= 0]

        def is_new(account: str) -> bool:
            state = self.accounts.get(account)
            return state is None or not state.backfill_done

        return sorted(due, key=lambda account: (is_new(account), -self._hours_overdue(account, now)))

    def _apply_retention(self) -> None:
        """Delete long-past events and forget old analyzed posts, so data and flyers don't grow forever."""
        now = config.now_bogota()
        oldest_date = (now - timedelta(days=config.EVENT_RETENTION_DAYS)).date().isoformat()
        kept = [event for event in self.events if not event.last_day or event.last_day >= oldest_date]
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

    # ---------- one post, from the admin tools ----------

    def add_post(self, url: str, account: str | None = None, again: bool = False) -> AddedPost:
        """Publish the events of one post by hand (`sweep --post`, the admin tools' Agregar), without triage
        (whoever asks knows it's an event).

        The post comes from Instagram's API, among the account's latest; when the API can't give it (a personal or
        private account, a collaboration listed under another account, Instagram's limit), from its public page
        (public_post.py), which also names the author when the link doesn't. An account the API can read and
        isn't swept yet is added to accounts.txt.

        Gemini only reads it when that can change something: a post analyzed before is read again only if its
        caption changed, or if it was filtered out as "not an event" or rejected (whoever asks says it is one).
        Otherwise the answer is what it already became, unless `again` ("Volver a leer"): then it's read again
        anyway (one Gemini request), e.g. after the prompts improved."""
        code = links.post_code(url)
        if not code:
            raise AddPostError("Ese enlace no es de una publicación de Instagram (instagram.com/p/…).")
        known_id = self._record_id(code)
        known = self.processed.get(known_id) if known_id else None
        account = account or (known.account if known else None) or links.account_in_link(url)
        public: tuple[str, Post] | None = None
        if not account:
            public = self._public_post(code)
            account = public[0]

        post: Post | None = None
        readable = True
        from_public = False
        try:
            self.instagram.check_token()
            posts = self.instagram.fetch_recent_posts(account, limit=config.ADMIN_POST_SEARCH)
            post = next((post for post in posts if links.same_post(post["permalink"], code)), None)
        except InstagramError as error:
            log.info("   the API can't give @%s's posts (%s): reading the post's public page", account, error)
            readable = not is_not_visible(error)
        if post is None:
            public = public or self._public_post(code)
            post, from_public = public[1], True
            if public[0] != account:  # a collaboration: the post is its author's
                account, readable = public[0], False
        if known_id and known_id != post["id"]:
            post = self._one_identity(known_id, post)

        added = readable and not from_public and storage.add_account(account)
        if added:
            self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
            log.info("@%s added to accounts.txt", account)
        record = self.processed.get(post["id"])
        unchanged = not again and record is not None and record.outcome in SETTLED_OUTCOMES and self._same_caption(post)
        if unchanged:
            log.info("   analyzed before and unchanged: not read again %s", post["permalink"])
        else:
            published = published_at(post)
            by_hand = "by hand, read again" if again and record else "by hand"
            log.info("   %s %-14s %s (%s)", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"], by_hand)
            self._extract_post(account, post, published)
            self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
            self.stats.gemini_requests = self.extractor.requests_this_run()
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))

        record = self.processed[post["id"]]
        events = [event for event in self.events if event.id in record.event_ids]
        return AddedPost(
            record.account,
            added,
            post["permalink"],
            record.outcome,
            record.reason,
            record.model,
            record.provisional,
            events,
            public=from_public,
            readable=readable,
            unchanged=unchanged,
        )

    # ---------- one post, one identity: the API's id, or public-<id> when read from its public page ----------

    def _record_id(self, code: str, public_only: bool = False) -> str | None:
        """The id under which a post (by its link's code) was analyzed, if it was."""
        return next(
            (
                post_id
                for post_id, record in self.processed.items()
                if (not public_only or post_id.startswith(public_post.ID_PREFIX))
                and links.same_post(record.permalink, code)
            ),
            None,
        )

    def _one_identity(self, known_id: str, post: Post) -> Post:
        """The same post under two ids (read once through the API, once from its public page): keep one. The
        API's id wins, so the sweeps recognize it."""
        if known_id.startswith(public_post.ID_PREFIX) and not post["id"].startswith(public_post.ID_PREFIX):
            self._rename_post(known_id, post["id"])
            return post
        return cast(Post, {**post, "id": known_id})

    def _rename_post(self, old: str, new: str) -> None:
        """Move a post's record and its place in events to a new id (flyers and clips keep their file names)."""
        self.processed[new] = self.processed.pop(old)
        for event in self.events:
            for media in event.media:
                if media.post_id == old:
                    media.post_id = new
        log.info("   %s is %s: the same post, now under the API's id", old, new)
        self._save()

    def _same_caption(self, post: Post) -> bool:
        """Whether the post's caption is the one analyzed: its fingerprint or, for a post read before from its
        public page (whose caption may be spaced differently), the caption stored with its events."""
        record = self.processed[post["id"]]
        if record.caption_hash == _caption_hash(post):
            return True
        stored = next(
            (media.caption for event in self.events for media in event.media if media.post_id == post["id"]), None
        )
        return stored is not None and " ".join(stored.split()) == " ".join((post.get("caption") or "").split())

    def _public_post(self, code: str) -> tuple[str, Post]:
        """The post from its public page, or AddPostError saying why it couldn't be read."""
        try:
            return public_post.fetch_public_post(code)
        except public_post.PublicPostError as error:
            raise AddPostError(f"No pude leer la publicación: la API de Instagram no la entrega y {error}.") from error

    def _extract_post(self, account: str, post: Post, published: datetime) -> None:
        """Extract and store one post without triage, or raise AddPostError saying why it couldn't."""
        if not self.extractor.can_analyze():
            raise AddPostError(_no_quota_message())
        try:
            images = _download_images(post)
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(account, post, published, images, known)
        except RejectedRequestError as error:
            raise AddPostError(f"Gemini no pudo leer la publicación ({error}).") from error
        except QuotaExhaustedError as error:
            raise AddPostError(_no_quota_message()) from error
        except GeminiKeyError as error:
            raise AddPostError("La clave de Gemini no funciona (vencida o revocada): hay que cambiarla.") from error
        except RETRYABLE_ERRORS as error:
            raise AddPostError(f"Algo falló al leerla ({error}). Inténtalo de nuevo en un rato.") from error
        if not self._store_analysis(account, post, images, analysis, model, provisional):
            raise AddPostError("No se pudo guardar el flyer. Inténtalo de nuevo en un rato.")

    # ---------- per account ----------

    def _process_account(self, account: str) -> None:
        state = self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
        backfill = not state.backfill_done
        account_stats = self.stats.account(account)
        account_stats.backfill = backfill
        log.info("== @%s%s", account, " (new account: deeper first sweep)" if backfill else "")

        try:
            limit = config.BACKFILL_POSTS if backfill else config.POSTS_PER_ACCOUNT
            posts = self.instagram.fetch_recent_posts(account, limit=limit)
        except InstagramError as error:
            log.error("   could not fetch posts: %s", error)
            self.rate_limited = is_rate_limited(error)
            if not self.rate_limited:
                state.last_swept_at = config.now_bogota().isoformat(timespec="seconds")  # tried: its turn is over
            self.stats.count(account, "errors")
            account_stats.fetch_failed = True
            return

        if posts:
            account_stats.latest_post = config.bogota_date(max(published_at(p) for p in posts)).isoformat()
            state.latest_post = account_stats.latest_post
        window = timedelta(days=config.BACKFILL_DAYS) if backfill else self.lookback
        cutoff = datetime.now(UTC) - window
        # Oldest first, so a flyer is usually stored before the video or reminder that follows it.
        for post in sorted(posts, key=lambda p: p["timestamp"]):
            published = published_at(post)
            if published < cutoff:
                continue
            record = self.processed.get(post["id"]) or self._adopt_public_record(post)
            caption_hash = _caption_hash(post)
            if record is None:
                log.info("   %s %-14s %s", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
                if self._out_of_time() or not self._analyze_new_post(account, post, published):
                    self.stats.count(account, "pending")
            elif record.caption_hash is None:
                record.caption_hash = caption_hash  # analyzed before captions were fingerprinted
                self._save()
            elif record.caption_hash != caption_hash:
                if self._out_of_time():
                    continue  # still edited next run: analyzed then
                log.info("   %s caption edited, analyzing again %s", f"{published:%Y-%m-%d}", post["permalink"])
                # A post that had events skips the filter: the extraction decides again, and takes its old
                # events off the site if it no longer announces them ("CANCELADO"). Others go through the
                # filter as usual (Flash-Lite), keeping Flash's small quota for events.
                # Records from before outcomes were kept (outcome None) had events if Gemini said so.
                had_events = record.outcome in ("event", "merged") or (record.outcome is None and record.is_event_post)
                if self._analyze_new_post(account, post, published, triage=not had_events):
                    self.stats.reanalyzed += 1
            elif record.provisional and self.extractor.can_extract_with_flash() and not self._out_of_time():
                log.info("   %s upgrading provisional analysis %s", f"{published:%Y-%m-%d}", post["permalink"])
                self._upgrade_post(account, post, published)

        self._complete_media(posts)
        # Read: its turn is over, unless posts wait (Gemini's quota, time): then it's due again next run.
        if account_stats.pending == 0:
            state.last_swept_at = config.now_bogota().isoformat(timespec="seconds")
        if backfill and account_stats.pending == 0:
            state.backfill_done = True
            log.info("   first sweep complete: from now on, regular sweep")
        storage.save_account_state(self.accounts)

    def _adopt_public_record(self, post: Post) -> ProcessedPost | None:
        """A post added by hand from its public page, now among the account's posts: the same post, not a new
        one (no second Gemini request). It's analyzed again only if its caption changed since."""
        code = links.post_code(post["permalink"])
        known_id = self._record_id(code, public_only=True) if code else None
        if known_id is None:
            return None
        self._rename_post(known_id, post["id"])
        record = self.processed[post["id"]]
        if self._same_caption(post):
            record.caption_hash = _caption_hash(post)  # the API's spacing from now on
        return record

    def _complete_media(self, posts: list[Post]) -> None:
        """Add what posts stored before clips and slide counts existed are missing, from their fresh copy
        (Instagram's video links expire, so only posts just fetched can get a clip)."""
        by_id = {post["id"]: post for post in posts}
        changed = False
        for event in self.events:
            for media in event.media:
                post = by_id.get(media.post_id)
                if post is None:
                    continue
                if media.slides is None and (slides := slide_count(post)):
                    media.slides, changed = slides, True
                needs_clip = media.preview is None and media.flyer and media.media_type != "IMAGE"
                if needs_clip and media.flyer and (preview := _clip_for(post, _flyer_slide(media.flyer))):
                    media.preview, changed = preview, True
        if changed:
            self._save()

    def _out_of_time(self) -> bool:
        """True once the run has used its time budget (MAX_RUN_MINUTES): start no more Gemini work."""
        over = time.monotonic() - self.started >= config.MAX_RUN_MINUTES * 60
        if over and not self.time_up_logged:
            log.warning("Run time budget used (%s min): the rest waits for the next run", config.MAX_RUN_MINUTES)
            self.time_up_logged = True
        return over

    # ---------- per post ----------

    def _analyze_new_post(self, account: str, post: Post, published: datetime, triage: bool = True) -> bool:
        """Triage, then extract if it's an event (`triage=False`: extract directly). False when the post must be
        retried next run."""
        if not self.extractor.can_analyze():
            return False  # no quota left today: it waits (no download, not an error)
        try:
            images = _download_images(post)
        except OSError as error:
            return self._retry_later(account, f"could not download images: {error}")

        verdict, triage_model = None, None
        if triage:
            try:
                verdict, triage_model = self.extractor.triage(account, post, published, images)
            except QuotaExhaustedError as error:
                # Flash-Lite out of today's quota: wait for it rather than spend Flash's small one on every post.
                log.info("     waits for the next run (triage): %s", error)
                return False
            except RETRYABLE_ERRORS as error:
                # Triage unavailable: let the extraction decide on its own.
                log.info("     triage unavailable (%s), extracting directly", error)

        if verdict is not None and not verdict.is_event_post:
            self.stats.count(account, "posts_analyzed")
            self.stats.posts_triaged_out += 1
            self._record_processed(account, post, False, verdict.reason, triage_model or "-", provisional=False)
            self._set_outcome(post, "not_event")
            self._save()
            log.info("     not an event: %s", verdict.reason)
            return True

        try:
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(account, post, published, images, known)
        except RejectedRequestError as error:
            # Gemini refuses this post itself (e.g. an image it can't read): retrying would spend quota on
            # every run and keep a new account's first sweep from ever finishing. Record it and move on.
            log.warning("     Gemini rejected the post, skipping it: %s", error)
            self.stats.count(account, "errors")
            self._record_processed(account, post, False, f"rechazado por Gemini: {error}", "-", provisional=False)
            self._set_outcome(post, "rejected")
            self._save()
            return True
        except QuotaExhaustedError as error:
            log.info("     waits for the next run: %s", error)
            return False
        except RETRYABLE_ERRORS as error:
            return self._retry_later(account, str(error))

        return self._store_analysis(account, post, images, analysis, model, provisional)

    def _upgrade_post(self, account: str, post: Post, published: datetime) -> None:
        """Re-extract a provisional post with Flash; keep the provisional result if that fails."""
        try:
            images = _download_images(post)
            known = self._known_events(account, published)
            analysis, model, _ = self.extractor.extract(
                account, post, published, images, known, allow_provisional=False
            )
        except RejectedRequestError as error:
            log.warning("     Gemini rejected the upgrade, keeping the provisional analysis: %s", error)
            self.processed[post["id"]].provisional = False  # stop retrying it
            self._save()
            return
        except RETRYABLE_ERRORS as error:
            log.info("     upgrade postponed: %s", error)
            return
        if self._store_analysis(account, post, images, analysis, model, provisional=False, count_as_new=False):
            self.stats.upgraded += 1

    def _store_analysis(
        self,
        account: str,
        post: Post,
        images: list[bytes],
        analysis: PostAnalysis,
        model: str,
        provisional: bool,
        count_as_new: bool = True,
    ) -> bool:
        """Store the post's events. False when it must be retried next run (a flyer couldn't be saved)."""
        cleaned = [normalize_event(event) for event in analysis.events]
        publishable = [event for event in cleaned if _is_publishable(event)] if analysis.is_event_post else []
        try:
            flyers = _save_flyers(post["id"], publishable, images)
        except OSError as error:
            return self._retry_later(account, f"could not save flyer: {error}")

        if count_as_new:
            self.stats.count(account, "posts_analyzed")
        self.stats.events_discarded += len(analysis.events) - len(publishable)
        if provisional:
            self.stats.provisional += 1
            log.info("     extracted by %s (provisional: Flash out of quota, upgraded on a later run)", model)
        self._record_processed(account, post, analysis.is_event_post, analysis.reason, model, provisional)
        # If this post was analyzed before, forget what it contributed and add it again below. Events that
        # only this post announced give their ids back, so a re-extraction keeps the events' URLs.
        reusable = [event for event in self.events if {media.post_id for media in event.media} == {post["id"]}]
        self.events = detach_post(self.events, post["id"])

        if not publishable:
            log.info("     skipped: %s", analysis.reason)
        results = [
            self._add_event(account, post, candidate, _media_for(post, flyer), reusable, count=count_as_new)
            for candidate, flyer in zip(publishable, flyers, strict=True)
        ]
        if results:
            merged_only = all(merged for _, merged in results)
            self._set_outcome(post, "merged" if merged_only else "event", [event_id for event_id, _ in results])
        elif analysis.is_event_post and analysis.events:
            reasons = sorted({"recurrente" if event.is_recurring else "sin fecha" for event in cleaned})
            self._set_outcome(post, "discarded", detail=", ".join(reasons))
        else:
            self._set_outcome(post, "not_event")
        self._save()
        return True

    def _retry_later(self, account: str, reason: str) -> bool:
        log.warning("     left for the next run: %s", reason)
        self.stats.count(account, "errors")
        return False

    def _known_events(self, account: str, published: datetime) -> list[StoredEvent]:
        """Events of this account that a new post could be announcing again (not already over)."""
        since = (config.bogota_date(published) - timedelta(days=1)).isoformat()
        return [event for event in self.events if event.account == account and (event.last_day or "") >= since]

    def _add_event(
        self,
        account: str,
        post: Post,
        candidate: ExtractedEvent,
        media: EventMedia,
        reusable: list[StoredEvent],
        count: bool = True,
    ) -> tuple[str, bool]:
        """Merge into the same event from another post, or store it as a new event: (its id, merged?).

        `count=False` for re-extractions (upgrades), which replace events instead of adding new ones.
        """
        existing = find_existing(self.events, account, candidate, post["id"])
        if existing:
            self.events[self.events.index(existing)] = merge_into(existing, candidate, media)
            if count:
                self.stats.count(account, "events_merged")
            log.info("     same event as an earlier post, merged: %s %s", _days(existing), existing.title)
            return existing.id, True
        event = StoredEvent(
            **_details(candidate), id=self._event_id(candidate, reusable), account=account, media=[media]
        )
        self.events.append(event)
        if count:
            self.stats.count(account, "events_new")
        log.info("     event: %s %s | %s [%s]", _days(event), event.start_time or "", event.title, event.event_type)
        return event.id, False

    def _event_id(self, candidate: ExtractedEvent, reusable: list[StoredEvent]) -> str:
        """The id of the event this post announced before (same date first), else a new readable one."""
        previous = next((event for event in reusable if event.date == candidate.date), None) or next(
            iter(reusable), None
        )
        if previous:
            reusable.remove(previous)
            return previous.id
        assert candidate.date, "only events with a date are stored (_is_publishable)"
        return new_event_id(candidate.title, candidate.date, {event.id for event in self.events})

    def _record_processed(
        self, account: str, post: Post, is_event_post: bool, reason: str, model: str, provisional: bool
    ) -> None:
        self.processed[post["id"]] = ProcessedPost(
            account=account,
            permalink=post["permalink"],
            processed_at=config.now_bogota().isoformat(timespec="seconds"),
            is_event_post=is_event_post,
            reason=reason,
            model=model,
            provisional=provisional,
            caption_hash=_caption_hash(post),
        )

    def _set_outcome(
        self, post: Post, outcome: PostOutcome, event_ids: list[str] | None = None, detail: str | None = None
    ) -> None:
        record = self.processed[post["id"]]
        record.outcome, record.event_ids, record.detail = outcome, event_ids or [], detail

    def _save(self) -> None:
        """Save after every post so progress survives an interrupted run."""
        storage.save_events(self.events)
        storage.save_processed_posts(self.processed)
