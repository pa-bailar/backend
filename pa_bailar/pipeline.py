"""The sweep: fetch recent posts, analyze new ones with Gemini, store one-time events and their flyers.

Per account:
  - A new account gets a deeper first sweep (its last BACKFILL_POSTS posts from the last BACKFILL_DAYS
    days); once all of them are analyzed it joins the regular sweep (last DEFAULT_LOOKBACK_DAYS days).
  - Each new post is triaged by the light model; only posts that announce events are extracted by Flash.
  - Posts extracted provisionally (Flash was out of quota) are re-extracted with Flash when there's budget.
  - Posts that couldn't be analyzed (no quota left today, network errors) stay pending for the next run.
  - A post whose caption was edited since it was analyzed (e.g. the venue added) is analyzed again.
  - After MAX_RUN_MINUTES no new Gemini work starts; the rest waits for the next run.

After all accounts: events older than EVENT_RETENTION_DAYS are deleted, then every flyer no event uses.
"""

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from google.genai import errors as genai_errors

from . import clips, config, links, storage
from .extraction import EventExtractor
from .gemini import ExtractionError, QuotaExhaustedError, RejectedRequestError
from .ids import new_event_id
from .instagram import (
    InstagramClient,
    InstagramError,
    Post,
    download_image,
    image_urls,
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

log = logging.getLogger(__name__)

# Errors that leave a post pending (retried next run) instead of stopping the sweep.
# OSError covers network and image errors.
RETRYABLE_ERRORS = (ExtractionError, genai_errors.APIError, OSError)


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
    events_expired: int = 0  # dated more than EVENT_RETENTION_DAYS ago
    processed_forgotten: int = 0  # analyzed-post records older than PROCESSED_RETENTION_DAYS
    flyers_removed: int = 0
    rate_limited: bool = False  # Instagram throttled the app: accounts after that one wait for the next run
    out_of_time: bool = False  # the run used its time budget: some posts wait for the next run
    gemini_requests: dict[str, int] = field(default_factory=dict)
    models_unavailable: list[str] = field(default_factory=list)  # Gemini models this key couldn't use
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
    """Only one-time events with a valid date make it to the website (run normalize_event first)."""
    return not event.is_recurring and bool(event.date)


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


def _details(event: ExtractedEvent) -> dict[str, Any]:
    return event.model_dump(include=set(EventDetails.model_fields))


class Sweep:
    def __init__(
        self,
        lookback_days: int,
        instagram: PostSource | None = None,
        extractor: Extractor | None = None,
    ):
        """Clients are built from the environment unless given (tests pass fakes)."""
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

        for account in self._accounts_in_order():
            usage = getattr(self.instagram, "app_usage_percent", 0)
            if usage >= config.INSTAGRAM_USAGE_STOP:
                log.warning("Instagram quota %s%% used: the remaining accounts wait for the next run", usage)
                self.rate_limited = True
            if self.rate_limited:
                log.warning("Instagram rate limit reached: the remaining accounts wait for the next run")
                break
            self.stats.accounts += 1
            try:
                self._process_account(account)
            except Exception:  # unexpected (e.g. a malformed answer): lose this account's run, not everyone's
                log.exception("   unexpected error with @%s, continuing with the next account", account)
                self.stats.count(account, "errors")

        self._apply_retention()
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        self.stats.models_unavailable = self.extractor.models_unavailable()
        self.stats.rate_limited = self.rate_limited
        self.stats.out_of_time = self.time_up_logged
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))
        return self.stats

    def _accounts_in_order(self) -> list[str]:
        """Accounts in their regular sweep first, so a backlog of new accounts (which can take several
        days of quota) never uses up the quota for today's posts of the accounts already followed."""

        def is_new(account: str) -> bool:
            state = self.accounts.get(account)
            return state is None or not state.backfill_done

        # Accounts Instagram's limit kept the last run from reaching go first in their group, so the end of
        # accounts.txt doesn't lose out every time.
        history = storage.read_json(config.RUN_HISTORY_FILE, [])
        skipped = set(history[-1].get("skipped_accounts", [])) if history else set()
        # stable: keeps accounts.txt order within each group
        return sorted(storage.read_accounts(), key=lambda account: (is_new(account), account not in skipped))

    def _apply_retention(self) -> None:
        """Delete long-past events and forget old analyzed posts, so data and flyers don't grow forever."""
        now = config.now_bogota()
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

    # ---------- one post, from the admin tools ----------

    def add_post(self, url: str, account: str | None = None) -> AddedPost:
        """Publish the events of one post by hand (`sweep --post`, from `admin add-post`): find it among the
        account's latest posts and extract it, without triage (whoever asks knows it's an event). A post
        analyzed before is analyzed again. An account that isn't swept yet is added to accounts.txt."""
        code = links.post_code(url)
        if not code:
            raise AddPostError("Ese enlace no es de una publicación de Instagram (instagram.com/p/…).")
        known = next((record for record in self.processed.values() if links.same_post(record.permalink, code)), None)
        account = account or (known.account if known else None) or links.account_in_link(url)
        if not account:
            raise AddPostError(
                "No sé de qué cuenta es: el enlace no lo dice y no la tengo registrada. Indica la @cuenta."
            )

        try:
            self.instagram.check_token()
            posts = self.instagram.fetch_recent_posts(account, limit=config.ADMIN_POST_SEARCH)
        except InstagramError as error:
            raise AddPostError(
                f"No pude leer @{account} en Instagram ({error}). Si es una cuenta personal o privada, la API no "
                "la puede ver."
            ) from error
        post = next((post for post in posts if links.same_post(post["permalink"], code)), None)
        if post is None:
            raise AddPostError(
                f"La publicación no está entre las últimas {config.ADMIN_POST_SEARCH} de @{account}. ¿Es una "
                "colaboración publicada desde otra cuenta, o se borró? Revisa la @cuenta."
            )

        added = storage.add_account(account)
        if added:
            self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
            log.info("@%s added to accounts.txt", account)
        published = published_at(post)
        log.info("   %s %-14s %s (by hand)", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
        self._extract_post(account, post, published)

        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))

        record = self.processed[post["id"]]
        events = [event for event in self.events if event.id in record.event_ids]
        return AddedPost(
            account, added, post["permalink"], record.outcome, record.reason, record.model, record.provisional, events
        )

    def _extract_post(self, account: str, post: Post, published: datetime) -> None:
        """Extract and store one post without triage, or raise AddPostError saying why it couldn't."""
        if not self.extractor.can_analyze():
            raise AddPostError("No queda cuota de Gemini hoy: inténtalo después de las 2:00 a. m.")
        try:
            images = _download_images(post)
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(account, post, published, images, known)
        except RejectedRequestError as error:
            raise AddPostError(f"Gemini no pudo leer la publicación ({error}).") from error
        except QuotaExhaustedError as error:
            raise AddPostError("No queda cuota de Gemini hoy: inténtalo después de las 2:00 a. m.") from error
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
            self.stats.count(account, "errors")
            account_stats.fetch_failed = True
            return

        if posts:
            account_stats.latest_post = max(published_at(p) for p in posts).date().isoformat()
        window = timedelta(days=config.BACKFILL_DAYS) if backfill else self.lookback
        cutoff = datetime.now(UTC) - window
        # Oldest first, so a flyer is usually stored before the video or reminder that follows it.
        for post in sorted(posts, key=lambda p: p["timestamp"]):
            published = published_at(post)
            if published < cutoff:
                continue
            record = self.processed.get(post["id"])
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
                if self._analyze_new_post(account, post, published):
                    self.stats.reanalyzed += 1
            elif record.provisional and self.extractor.can_extract_with_flash() and not self._out_of_time():
                log.info("   %s upgrading provisional analysis %s", f"{published:%Y-%m-%d}", post["permalink"])
                self._upgrade_post(account, post, published)

        self._complete_media(posts)
        if backfill and account_stats.pending == 0:
            state.backfill_done = True
            log.info("   first sweep complete: from now on, regular sweep")
        storage.save_account_state(self.accounts)

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

    def _analyze_new_post(self, account: str, post: Post, published: datetime) -> bool:
        """Triage, then extract if it's an event. False when the post must be retried next run."""
        if not self.extractor.can_analyze():
            return False  # no quota left today: it waits (no download, not an error)
        try:
            images = _download_images(post)
        except OSError as error:
            return self._retry_later(account, f"could not download images: {error}")

        try:
            triage, triage_model = self.extractor.triage(account, post, published, images)
        except RETRYABLE_ERRORS as error:
            # Triage unavailable: let the extraction decide on its own.
            log.info("     triage unavailable (%s), extracting directly", error)
            triage, triage_model = None, None

        if triage is not None and not triage.is_event_post:
            self.stats.count(account, "posts_analyzed")
            self.stats.posts_triaged_out += 1
            self._record_processed(account, post, False, triage.reason, triage_model or "-", provisional=False)
            self._set_outcome(post, "not_event")
            self._save()
            log.info("     not an event: %s", triage.reason)
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
        since = (published - timedelta(days=1)).date().isoformat()
        return [event for event in self.events if event.account == account and (event.date or "") >= since]

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
            log.info("     same event as an earlier post, merged: %s %s", existing.date, existing.title)
            return existing.id, True
        event = StoredEvent(
            **_details(candidate), id=self._event_id(candidate, reusable), account=account, media=[media]
        )
        self.events.append(event)
        if count:
            self.stats.count(account, "events_new")
        log.info("     event: %s %s | %s [%s]", event.date, event.start_time or "", event.title, event.event_type)
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
