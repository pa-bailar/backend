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

The admin tools add one post by hand (`add_post`), or a story from its screenshots (`add_story`, stories.py), and
take a story off the site again (`hide_story`).
"""

import hashlib
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

import httpx
from google.genai import errors as genai_errors

from . import clips, config, links, public_post, storage, stories
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
from .merging import already_stored, detach_post, find_existing, matches_hidden, merge_into, refused_link
from .models import (
    AccountState,
    EventDetails,
    EventMedia,
    ExtractedEvent,
    HiddenEvent,
    PostAnalysis,
    PostOutcome,
    ProcessedPost,
    Session,
    StoredEvent,
    StoryAnalysis,
    StoryEvent,
    Triage,
)
from .normalize import normalize_event
from .text import WEEKDAYS, clock, fold

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


def _has_ended(event: EventDetails, today: date) -> bool:
    """Whether the event's last day (its end_date, a series' last session, else its date) is before today."""
    return bool(event.last_day) and (event.last_day or "") < today.isoformat()


def _unpublishable(event: ExtractedEvent) -> list[str]:
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


# A caption or Gemini's reason saying the event is off (folded text: lowercase, no accents).
_CANCELLED = re.compile(
    r"\b(cancelad[oa]s?|cancelamos|se cancela|cancell?ed|aplazad[oa]s?|aplazamos|se aplaza|pospuest[oa]s?"
    r"|posponemos|se pospone|postponed|suspendid[oa]s?|suspendemos)\b"
)


def _says_cancelled(post: Post, analysis: PostAnalysis) -> bool:
    """Whether the post's caption, or Gemini's reason for finding no event in it, says it's cancelled or postponed."""
    return bool(_CANCELLED.search(fold(f"{post.get('caption') or ''} {analysis.reason}")))


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
    detail: str | None = None  # ProcessedPost.detail: why it was discarded ("ya pasó", "fuera de Bogotá"...)


@dataclass
class AddedStory:
    """What add_story did, for the admin tools' answer (the "receipt": what was read and where it came from)."""

    story_id: str
    account: str
    account_source: str  # where the account came from, in Spanish
    account_checked: bool  # Instagram's API can read it (so it's swept)
    account_added: bool
    outcome: str | None  # ProcessedPost.outcome
    reason: str  # Gemini's
    model: str | None
    provisional: bool  # read by Flash-Lite (Flash out of quota): kept as it is
    events: list[StoredEvent]
    taken: datetime
    taken_source: str
    date_notes: dict[str, list[str]] = field(default_factory=dict)  # by event title: how its date was worked out
    mentions: list[str] = field(default_factory=list)
    location: str | None = None
    gemini_crop: bool = True  # the flyer is Gemini's box; False: the fixed crop
    past: list[str] = field(default_factory=list)  # events whose date had passed: not published
    unchanged: bool = False  # these same screenshots were published before: not read again
    duplicate_of: str | None = None  # another screenshot of a story published before (stories.same_story)

    @property
    def done(self) -> bool:
        """Its screenshots aren't needed any more (published, or already were): they can be deleted."""
        return self.unchanged or self.duplicate_of is not None or self.outcome in ("event", "merged")


@dataclass
class HiddenFromSite:
    """What hide_event did."""

    event: StoredEvent  # as it was on the site
    already: bool = False  # it was hidden before


@dataclass
class HiddenStory:
    """What hide_story did."""

    story_id: str
    account: str
    removed: list[StoredEvent]  # off the site
    kept: list[StoredEvent]  # still on the site: other posts announce them
    already: bool = False


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
    """An event's day for the log: its date, or first → last day (a workshop series: and how many sessions)."""
    sessions = f" ({len(event.sessions)} sessions)" if event.sessions else ""
    return f"{event.date} → {event.end_date}{sessions}" if event.end_date else str(event.date)


def _details(event: ExtractedEvent) -> dict[str, Any]:
    return event.model_dump(include=set(EventDetails.model_fields))


def _story_event(
    item: StoryEvent, resolved: "stories.ResolvedDate", location: str | None, image_index: int
) -> ExtractedEvent:
    """A story's event as the sweep stores events: its date (a workshop series: its sessions) worked out in code, the
    location sticker as the venue when none is written, and a weekday that doesn't match the date (or a date far
    ahead) as a doubt."""
    doubts = list(item.doubts)
    if resolved.weekday_mismatch or resolved.far_ahead:
        doubts += [note for note in resolved.notes if note.startswith(("dice ", "más de"))]
    return ExtractedEvent(
        title=item.title,
        event_type=item.event_type,
        is_recurring=item.is_recurring,  # a weekly night isn't: its next date is published
        styles=item.styles,
        organizer=item.organizer,
        venue=item.venue or location,
        address=item.address,
        area=item.area,
        date=resolved.start.isoformat() if resolved.start else None,
        end_date=resolved.end.isoformat() if resolved.end else None,
        sessions=[
            Session(date=day.isoformat(), start_time=session.start_time, end_time=session.end_time)
            for day, session in resolved.sessions
        ]
        or None,
        weekday=WEEKDAYS[resolved.start.weekday()] if resolved.start else item.weekday,
        start_time=item.start_time,
        end_time=item.end_time,
        prices=item.prices,
        artists=item.artists,
        activities=item.activities,
        contact=item.contact,
        confidence="low" if resolved.weekday_mismatch else item.confidence,
        doubts=doubts,
        image_index=image_index,
        same_as=item.same_as,
        in_bogota="yes",  # shared by hand by the admin, who saw where it is (the prompt still leaves out other cities)
    )


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
        self.hidden = storage.load_hidden_events()
        # An event hidden by hand stays off the site, even if the data PR of the run that hid it wasn't merged.
        stored = storage.load_events()
        self.events = [event for event in stored if event.id not in self.hidden]
        if len(self.events) != len(stored):
            storage.save_events(self.events)
        self.processed = storage.load_processed_posts()
        self.by_hand = False  # adding a post or story by hand: it may publish again what was hidden
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
        past = [key for key, item in self.hidden.items() if (item.event.last_day or "") < oldest_date]
        for key in past:  # long past: no post of it will be read again
            del self.hidden[key]

        # Never forget a post the lookback could still fetch (e.g. a manual run with --days 60).
        keep_days = max(config.PROCESSED_RETENTION_DAYS, self.lookback.days + 1)
        oldest_record = now - timedelta(days=keep_days)
        old = [pid for pid, rec in self.processed.items() if datetime.fromisoformat(rec.processed_at) < oldest_record]
        for post_id in old:
            del self.processed[post_id]
        self.stats.processed_forgotten = len(old)

        if self.stats.events_expired or old or past:
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
        self.by_hand = True  # whoever asks wants it published, even if it was hidden before
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
            detail=record.detail,
        )

    # ---------- a story, from the admin tools: its screenshots (stories.py) ----------

    def add_story(
        self, shots: list[stories.Screenshot], account: str | None = None, notes: str | None = None
    ) -> AddedStory:
        """Publish the events of a story from screenshots of it (`sweep --story`, the admin tools' "Agregar
        historia"): one Gemini request for all of them (up to stories.MAX_SCREENSHOTS), no triage.

        - The same screenshots again (a retried request) aren't read again; another screenshot of a story already
          published, within a day and a half, neither (perceptual hash), unless notes come with it.
        - The account: the one typed, else the author of a post the story reshares, else the name at the top of
          the story; checked with one Instagram call, or matched to a known account when it's cut off ("…").
          Mentions and a location sticker are hints, never the account. An account the API can read and isn't
          swept yet is added.
        - Dates are worked out from what's printed (stories.resolve_date), relative to when the screenshot was
          taken; an event whose date passed isn't published. A weekly night publishes its next date.
        - The flyer is a crop of the screenshot (Gemini's box, checked and padded, or a fixed crop): the
          screenshot itself is never published. The event's permalink is the account's profile."""
        if not shots:
            raise AddPostError("No llegó ninguna captura.")
        self.by_hand = True
        shots = shots[: stories.MAX_SCREENSHOTS]
        images = [shot.image for shot in shots]
        story_id = stories.story_id(images)
        now = config.now_bogota()
        taken, taken_source = min((stories.taken_at(shot, now) for shot in shots), key=lambda pair: pair[0])
        hashes = [stories.image_hash(image) for image in images]

        record = self.processed.get(story_id)
        if record and record.outcome in ("event", "merged"):
            log.info("   %s: the same screenshots, published before", story_id)
            return self._story_answer(story_id, taken, taken_source, unchanged=True)
        twin = None if notes else self._same_story(hashes, now)
        if twin:
            log.info("   %s: another screenshot of %s, published before", story_id, twin)
            return self._story_answer(twin, taken, taken_source, duplicate_of=twin)

        if not self.extractor.can_analyze():
            raise AddPostError(_no_quota_message())
        known = self._known_events(account, taken) if account else []
        try:
            analysis, model, provisional = self.extractor.extract_story(images, taken, account, notes, known)
        except RejectedRequestError as error:
            raise AddPostError(f"Gemini no pudo leer las capturas ({error}).") from error
        except QuotaExhaustedError as error:
            raise AddPostError(_no_quota_message()) from error
        except GeminiKeyError as error:
            raise AddPostError("La clave de Gemini no funciona (vencida o revocada): hay que cambiarla.") from error
        except RETRYABLE_ERRORS as error:
            raise AddPostError(f"Algo falló al leerlas ({error}). Inténtalo de nuevo en un rato.") from error

        owner, source, checked = self._story_account(account, analysis)
        today = now.date()
        crops = [stories.crop(image, self._content_box(analysis, index)) for index, image in enumerate(images)]
        best = max(range(len(crops)), key=lambda index: (crops[index].from_gemini, crops[index].area))
        extracted: list[ExtractedEvent] = []
        date_notes: dict[str, list[str]] = {}
        past: list[str] = []
        for item in analysis.events:
            resolved = stories.resolve_date(item, taken.date(), today)
            index = item.image_index
            image_index = index if index is not None and 0 <= index < len(crops) else best
            event = _story_event(item, resolved, analysis.location_sticker, image_index)
            if _has_ended(event, today):
                past.append(item.title)
                continue
            extracted.append(event)
            date_notes[" ".join(item.title.split())] = resolved.notes

        age = stories.story_age(analysis.story_age)
        published = (taken - age) if age else taken
        post = cast(
            Post,
            {
                "id": story_id,
                "media_type": "STORY",
                "permalink": stories.profile_link(owner),
                "timestamp": published.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000"),
            },
        )
        day = f"{published:%Y-%m-%d}"
        log.info("   %s STORY %s (@%s, %s screenshot(s), by hand)", day, story_id, owner, len(shots))
        result = PostAnalysis(is_event_post=analysis.is_event_post, reason=analysis.reason, events=extracted)
        if not self._store_analysis(owner, post, [item.image for item in crops], result, model, provisional):
            raise AddPostError("No se pudo guardar el flyer. Inténtalo de nuevo en un rato.")
        record = self.processed[story_id]
        record.provisional = False  # no later sweep sees a story: a Flash-Lite read stays as it is
        record.image_hashes = hashes
        if past and record.outcome == "not_event":
            record.outcome, record.detail = "discarded", "ya pasó"
        self._save()

        added = checked and storage.add_account(owner)
        if added:
            self.accounts.setdefault(owner, AccountState(first_seen=today.isoformat()))
            log.info("@%s added to accounts.txt", owner)
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))
        answer = self._story_answer(story_id, taken, taken_source)
        answer.account_source, answer.account_checked, answer.account_added = source, checked, added
        answer.provisional, answer.date_notes, answer.past = provisional, date_notes, past
        answer.mentions = [name for raw in analysis.mentions_in_image if (name := stories.read_handle(raw)[0])]
        answer.location = analysis.location_sticker
        flyer_slides = {event.image_index for event in extracted}
        answer.gemini_crop = all(crops[index].from_gemini for index in flyer_slides if index is not None)
        return answer

    def _story_answer(
        self,
        story_id: str,
        taken: datetime,
        taken_source: str,
        unchanged: bool = False,
        duplicate_of: str | None = None,
    ) -> AddedStory:
        record = self.processed[story_id]
        events = [event for event in self.events if event.id in record.event_ids]
        return AddedStory(
            story_id=story_id,
            account=record.account,
            account_source="",
            account_checked=True,
            account_added=False,
            outcome=record.outcome,
            reason=record.reason,
            model=record.model,
            provisional=False,
            events=events,
            taken=taken,
            taken_source=taken_source,
            unchanged=unchanged,
            duplicate_of=duplicate_of,
        )

    def _same_story(self, hashes: list[str], now: datetime) -> str | None:
        """A published story these screenshots are of (another screenshot of it), shared recently."""
        since = now - timedelta(hours=stories.SAME_STORY_HOURS)
        return next(
            (
                story_id
                for story_id, record in self.processed.items()
                if story_id.startswith(stories.STORY_PREFIX)
                and record.outcome in ("event", "merged")
                and datetime.fromisoformat(record.processed_at) >= since
                and stories.same_story(hashes, record.image_hashes)
            ),
            None,
        )

    @staticmethod
    def _content_box(analysis: StoryAnalysis, index: int) -> list[int] | None:
        return next((image.content_box for image in analysis.images if image.index == index), None)

    def _can_read(self, account: str) -> bool:
        """Whether Instagram's API can read the account (one call)."""
        try:
            self.instagram.fetch_recent_posts(account, limit=1)
        except InstagramError as error:
            log.info("   the API can't read @%s (%s)", account, error)
            return False
        return True

    def _story_account(self, typed: str | None, analysis: StoryAnalysis) -> tuple[str, str, bool]:
        """(the story's account, where it came from in Spanish, whether the API can read it)."""
        candidates: list[tuple[str | None, str]] = [(typed, "escrita en el pedido")] if typed else []
        candidates += [
            (analysis.reshared_from, "la de la publicación que comparte la historia"),
            (analysis.account_in_image, "leída del encabezado de la historia"),
        ]
        swept = set(storage.read_accounts())
        known = swept | {event.account for event in self.events}
        for raw, source in candidates:
            name, cut = (raw, False) if raw == typed else stories.read_handle(raw)
            if not name:
                continue
            if not cut and self._can_read(name):
                return name, source, True
            if raw == typed:
                return name, f"{source}; Instagram no la deja leer (personal o privada)", False
            match = stories.known_account(name, cut, known)
            if match:
                return match, f"{source}, completada con una cuenta conocida", match in swept
            if not cut:
                return name, f"{source}; no pude comprobarla en Instagram", False
        raise AddPostError(
            "No pude saber de qué cuenta es la historia (el nombre no se ve o está cortado y no lo reconozco). "
            "Compártela otra vez escribiendo la @cuenta."
        )

    def hide_story(self, story_id: str) -> HiddenStory:
        """Take a story added by hand off the site ("Ocultar historia"): its events lose it, and those only it
        announced disappear (with its flyer). Recorded as `hidden`; sharing the same screenshots again reads it
        again."""
        record = self.processed.get(story_id)
        if not stories.is_story_id(story_id) or record is None:
            raise AddPostError(f"No encontré la historia {story_id}: ¿se agregó hace más de 45 días?")
        if record.outcome == "hidden":
            return HiddenStory(story_id, record.account, [], [], already=True)
        affected = [event for event in self.events if any(media.post_id == story_id for media in event.media)]
        self.events = detach_post(self.events, story_id)
        remaining = {event.id for event in self.events}
        record.outcome = "hidden"
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self._save()
        storage.save_meta(asdict(self.stats))
        log.info("   %s hidden: %s event(s) affected", story_id, len(affected))
        return HiddenStory(
            story_id,
            record.account,
            removed=[event for event in affected if event.id not in remaining],
            kept=[event for event in self.events if event.id in {e.id for e in affected}],
        )

    def hide_event(self, event_id: str) -> HiddenFromSite:
        """Take any event off the site by hand ("Ocultar", e.g. a new workshop series that isn't right), whatever
        it came from (posts, stories). It's kept in state/hidden_events.json: the sweeps never publish it again from
        the same posts (a caption edit, an upgrade) nor from a later post of the same event (merging.matches_hidden);
        a genuinely new event is published as usual. Adding one of its posts by hand (Agregar, Volver a leer)
        publishes it again. Its posts' records lose it (`hidden` when it was all they announced)."""
        if event_id in self.hidden:
            return HiddenFromSite(self.hidden[event_id].event, already=True)
        event = next((item for item in self.events if item.id == event_id), None)
        if event is None:
            raise AddPostError(f"No encontré el evento `{event_id}` en el sitio: ¿ya pasó, o cambió de nombre?")
        self.events.remove(event)
        self.hidden[event_id] = HiddenEvent(hidden_at=config.now_bogota().isoformat(timespec="seconds"), event=event)
        for media in event.media:
            record = self.processed.get(media.post_id)
            if record is None:
                continue
            record.event_ids = [other for other in record.event_ids if other != event_id]
            if not record.event_ids:
                record.outcome, record.provisional = "hidden", False  # no upgrade for nothing
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self._save()
        storage.save_meta(asdict(self.stats))
        log.info("   %s hidden by hand: %s", event_id, event.title)
        return HiddenFromSite(event)

    def _hidden_match(self, account: str, candidate: ExtractedEvent, post_id: str) -> HiddenEvent | None:
        return next(
            (item for item in self.hidden.values() if matches_hidden(item.event, account, candidate, post_id)), None
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
        publishable: list[ExtractedEvent] = []
        reasons: set[str] = set()  # why the others weren't published, for the post's record
        for event in cleaned if analysis.is_event_post else []:
            why = self._discard_reasons(account, post["id"], event)
            reasons.update(why)
            if not why:
                publishable.append(event)
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
        announced = {event.id for event in self.events if any(media.post_id == post["id"] for media in event.media)}
        self.events = detach_post(self.events, post["id"])
        cancelled = not publishable and bool(announced) and _says_cancelled(post, analysis)

        if not publishable:
            log.info("     skipped: %s", analysis.reason)
        added = [
            self._add_event(account, post, candidate, _media_for(post, flyer), reusable, count=count_as_new)
            for candidate, flyer in zip(publishable, flyers, strict=True)
        ]
        results = [result for result in added if result]
        if results:
            merged_only = all(merged for _, merged in results)
            self._set_outcome(post, "merged" if merged_only else "event", [event_id for event_id, _ in results])
        elif added:  # every event it announces was hidden by hand
            self._set_outcome(post, "hidden", detail="oculto a mano")
        elif cancelled:  # it announced events, and now says they're cancelled ("CANCELADO")
            self._take_down_cancelled(account, announced)
            self._set_outcome(post, "discarded", detail="cancelado")
        elif analysis.is_event_post and analysis.events:
            self._set_outcome(post, "discarded", detail=", ".join(sorted(reasons)))
        else:
            self._set_outcome(post, "not_event")
        self._save()
        return True

    def _take_down_cancelled(self, account: str, event_ids: set[str]) -> None:
        """A post that announced these events now says they're cancelled or postponed (its caption edited to
        "CANCELADO"); those only it announced are gone already (detach_post). Of the others, still announced by
        other posts, the events of this post's own account (the one that announced them first: events are stored
        under it) leave the site, and the other posts' records lose them. Another account's event stays, with low
        confidence and a doubt, so the health report lists it for review: a venue or collaborator dropping out
        doesn't cancel the organizer's event."""
        for event in [event for event in self.events if event.id in event_ids]:
            if event.account == account:
                self.events.remove(event)
                for record in self.processed.values():
                    if event.id not in record.event_ids:
                        continue
                    record.event_ids = [other for other in record.event_ids if other != event.id]
                    if not record.event_ids:  # nothing left to upgrade or show
                        record.outcome, record.detail, record.provisional = "discarded", "cancelado", False
                log.info("     cancelled, taken off the site: %s %s", _days(event), event.title)
            else:
                doubt = f"@{account} lo anunció cancelado o aplazado: revisar"
                flagged = event.model_copy(update={"confidence": "low", "doubts": [*event.doubts, doubt]})
                self.events[self.events.index(event)] = flagged
                log.info("     @%s says it's cancelled, flagged for review: %s %s", account, _days(event), event.title)

    def _discard_reasons(self, account: str, post_id: str, event: ExtractedEvent) -> list[str]:
        """Why an extracted event isn't published (empty: it is), in Spanish: _unpublishable, or "ya pasó" when its
        last day is before today in Bogotá and it isn't an event already stored (a new account's first sweep reads
        posts a month old; an event already on the site still takes its later posts and re-reads)."""
        reasons = _unpublishable(event)
        if "fuera de Bogotá" in reasons:
            log.info("     not in Bogotá (Gemini), left out: %s %s", _days(event), event.title)
        ended = bool(event.date) and _has_ended(event, config.now_bogota().date())
        if ended and not already_stored(self.events, account, event, post_id):
            log.info("     already over, left out: %s %s", _days(event), event.title)
            reasons.append("ya pasó")
        return reasons

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
    ) -> tuple[str, bool] | None:
        """Merge into the same event from another post, or store it as a new event: (its id, merged?). None when
        it's an event hidden by hand (hide_event): left off the site, unless the post is added by hand.

        `count=False` for re-extractions (upgrades), which replace events instead of adding new ones.
        """
        hidden = self._hidden_match(account, candidate, post["id"])
        if hidden and not self.by_hand:
            log.info("     hidden by hand, left off the site: %s %s", _days(hidden.event), hidden.event.title)
            return None
        if hidden:  # added by hand: published again (with its old id, when it's stored as new)
            del self.hidden[hidden.event.id]
            log.info("     hidden by hand before, published again (added by hand): %s", hidden.event.title)
        if refused := refused_link(self.events, account, candidate, post["id"]):
            log.info("     Gemini linked it to %s, which isn't on its day: not merged", refused.id)
            doubt = f"posible cambio de fecha: Gemini lo une a {refused.id}"
            candidate = candidate.model_copy(update={"doubts": [*candidate.doubts, doubt]})
        existing = find_existing(self.events, account, candidate, post["id"])
        if existing:
            self.events[self.events.index(existing)] = merge_into(existing, candidate, media)
            if count:
                self.stats.count(account, "events_merged")
            log.info("     same event as an earlier post, merged: %s %s", _days(existing), existing.title)
            return existing.id, True
        event_id = hidden.event.id if hidden else self._event_id(candidate, reusable)
        event = StoredEvent(**_details(candidate), id=event_id, account=account, media=[media])
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
        taken = {event.id for event in self.events} | set(self.hidden)  # a hidden event keeps its id to itself
        if previous:
            reusable.remove(previous)
            return previous.id
        assert candidate.date, "only events with a date are stored (_unpublishable)"
        return new_event_id(candidate.title, candidate.date, taken)

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
        storage.save_hidden_events(self.hidden)
