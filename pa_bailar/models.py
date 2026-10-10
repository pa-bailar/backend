"""Data models: what Gemini returns and what is stored in data/events.json.

These models are the source of truth for the data contract with the frontend
(the site repository's frontend/src/scripts/types.ts mirrors StoredEvent; its check-data.mjs checks
every data PR against the contract).
"""

import datetime as dt
import re
from itertools import pairwise
from typing import Literal, Self, get_args

from pydantic import BaseModel, Field, model_validator

from . import config

# "party" ("Rumba" on the site): a night out, apart from a dancers' social (the owner, 6 Oct 2026; prompts.py).
EventType = Literal["social", "party", "workshop", "concert", "festival", "congress", "competition", "show", "other"]
Confidence = Literal["high", "medium", "low"]

# Dance styles. Salsa and bachata have one level of specificity; the plain name is the fallback when
# the variant can't be told. Every other style stays general. Synonyms are mapped in normalize.py.
Style = Literal[
    "salsa",
    "salsa cubana",  # casino, rueda de casino, timba
    "salsa en línea",  # on1, on2, mambo, New York / Los Angeles style
    "salsa caleña",  # estilo caleño, Cali
    "bachata",
    "bachata sensual",
    "bachata dominicana",  # tradicional
    "merengue",
    "cha cha chá",
    "son",
    "kizomba",
    "zouk",
    "champeta",
    "urbano",  # reguetón, hip hop, street
    "afro",  # afro, afrobeat, rumba cubana, folclor afro
    "dancehall",
    "heels",
    "tango",
    "swing",
    "otro",
]
STYLES: tuple[str, ...] = get_args(Style)


class Price(BaseModel):
    label: str = Field(description="As written, e.g. 'Preventa', 'Taquilla', 'Alumnos', 'General'")
    amount_cop: int = Field(
        description="Colombian pesos only. '15K' or '15 mil' = 15000; 0 = free. Never a price in another currency"
    )
    condition: str | None = Field(None, description="e.g. 'hasta el 24 de septiembre', 'solo 50 cupos'")


class Session(BaseModel):
    """One dated session of a workshop series."""

    date: str = Field(description="YYYY-MM-DD")
    start_time: str | None = Field(description="HH:MM, 24-hour; null if not given")
    end_time: str | None = Field(description="HH:MM, 24-hour; null if not given")


_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _iso_date(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if value and len(value) == 10 else None
    except ValueError:
        return None


def series_problems(event: "EventDetails") -> list[str]:
    """What breaks the rules of a workshop series' `sessions` (none: fine, or not a series): from
    MIN_SERIES_SESSIONS to MAX_SERIES_SESSIONS sessions, real dates in order without repeats, valid times, the last
    session at most MAX_SERIES_DAYS days in all after the first, `date` the first session's and `end_date` the
    last's. The site's check-data.mjs checks the same."""
    sessions = event.sessions
    if sessions is None:
        return []
    problems = []
    if not config.MIN_SERIES_SESSIONS <= len(sessions) <= config.MAX_SERIES_SESSIONS:
        problems.append(
            f"{len(sessions)} sessions: {config.MIN_SERIES_SESSIONS} to {config.MAX_SERIES_SESSIONS} expected"
        )
    parsed = [_iso_date(session.date) for session in sessions]
    days = [day for day in parsed if day]
    if len(days) != len(parsed):
        problems.append("a session without a valid date")
    elif any(later <= earlier for earlier, later in pairwise(days)):
        problems.append("sessions out of order or repeated")
    elif days and (days[-1] - days[0]).days + 1 > config.MAX_SERIES_DAYS:
        problems.append(f"sessions over more than {config.MAX_SERIES_DAYS} days")
    for session in sessions:
        if any(time is not None and not _TIME.match(time) for time in (session.start_time, session.end_time)):
            problems.append(f"bad time in the session of {session.date}")
    if sessions and (event.date != sessions[0].date or event.end_date != sessions[-1].date):
        problems.append("date and end_date must be the first and last sessions' dates")
    return problems


class EventDetails(BaseModel):
    """Fields shared by an extracted event and a stored event."""

    title: str
    event_type: EventType = Field(
        description="social = a night for dancers (an academy's or a dance organizer's socials, dance nights, "
        "anniversaries); party = a night out (a bar's or club's special night, a general public party); "
        "workshop = one-time workshops, masterclasses and special classes with guest teachers, and workshop series "
        "(see sessions)"
    )
    is_recurring: bool = Field(
        description="True for regular classes or nights that repeat (weekly, every Friday...), and courses or "
        "programs whose sessions aren't each dated. A workshop series with every session dated isn't recurring: "
        "see sessions"
    )
    styles: list[Style] = Field(
        description="Dance styles from the list. Use a salsa/bachata variant only when the post says it; "
        "otherwise plain 'salsa' or 'bachata'."
    )
    organizer: str | None
    venue: str | None = Field(description="Venue name if given")
    address: str | None
    area: str | None = Field(description="Bogotá neighborhood or zone if given")
    date: str | None = Field(
        description="YYYY-MM-DD; an event over several consecutive days: its first day; a workshop series: its "
        "first session's"
    )
    # Optional in stored data (events stored before it existed have none); ExtractedEvent makes Gemini fill it.
    end_date: str | None = Field(
        None,
        description="Last day (YYYY-MM-DD) of an event over several consecutive days, e.g. 'NOV 13-15' → "
        "2026-11-15; a workshop series: its last session's. Null for a one-day event.",
    )
    # A workshop series (a finite program on separate dates, each written in the post): its sessions, in order. None
    # for every other event. Optional in stored data, like end_date; ExtractedEvent makes Gemini fill it.
    sessions: list[Session] | None = Field(
        None,
        description="Only for a workshop series (a taller, intensivo, curso corto, bootcamp or ciclo whose 2 to 12 "
        "sessions each have their own date written in the post, on separate non-consecutive days within 4 months): "
        "every session, in order. Null for every other event, including one over consecutive days.",
    )
    weekday: str | None = Field(description="Spanish weekday name, lowercase")
    start_time: str | None = Field(description="HH:MM, 24-hour")
    end_time: str | None = Field(description="HH:MM, 24-hour")
    prices: list[Price]
    artists: list[str] = Field(description="Guest teachers, DJs, orchestras, performers")
    activities: list[str] = Field(description="Short Spanish phrases, e.g. 'clase de bachata', 'show'")
    contact: str | None = Field(
        description="How to reach the organizer: an @username, a website, or a phone number. Write "
        "'WhatsApp ' before a number the flyer or caption marks as WhatsApp (the word or the WhatsApp "
        "icon), e.g. 'WhatsApp 3001234567'; a number not marked so stays as it is."
    )
    confidence: Confidence
    doubts: list[str] = Field(description="Important missing or assumed information, short phrases in Spanish")

    @property
    def last_day(self) -> str | None:
        """The event's last day: its end_date over several days (a series: its last session), else its date.
        Upcoming until it has passed."""
        return self.end_date or self.date

    @property
    def session_dates(self) -> list[str]:
        """A workshop series' session dates, in order; empty for any other event."""
        return [session.date for session in self.sessions or []]


# ---------- Gemini response schema ----------


class ExtractedEvent(EventDetails):
    # Required (but nullable) like the other fields, so Gemini's response schema asks for it.
    end_date: str | None = Field(
        description="Last day (YYYY-MM-DD) of an event over several consecutive days, e.g. 'NOV 13-15' → "
        "2026-11-15; a workshop series: its last session's. Null for a one-day event."
    )
    sessions: list[Session] | None = Field(
        description="Only for a workshop series (a taller, intensivo, curso corto, bootcamp or ciclo whose 2 to 12 "
        "sessions each have their own date written in the post, on separate non-consecutive days within 4 months): "
        "every session, in order, with its own times. Null for every other event, including one over consecutive "
        "days."
    )
    image_index: int | None = Field(
        description="Number of the attached image that shows THIS event (its own flyer, or the schedule slide "
        "where it is listed). Null if no image shows it."
    )
    same_as: str | None = Field(
        description="If this post announces again one of the KNOWN EVENTS listed in the prompt (a video, reminder "
        "or second flyer of the same event), that event's id. Null for a new event."
    )
    # Internal: read by the sweep (Sweep._discard_reasons), never stored (StoredEvent has no such field).
    in_bogota: Literal["yes", "no", "unknown"] = Field(
        description="Is THIS event in Bogotá, Colombia? 'no' when the post places it in another city or country (a "
        "tour date in México, 'taller en Medellín', a venue abroad); 'yes' when it's in Bogotá or no city is stated; "
        "'unknown' when the post hints at another place without saying where this event is."
    )


class Triage(BaseModel):
    """Cheap first pass, so the expensive extraction only runs on posts that announce events."""

    is_event_post: bool = Field(
        description="True if the post announces at least one upcoming one-time event. When unsure, true."
    )
    reason: str = Field(description="One short sentence explaining the decision, in Spanish")


class PostAnalysis(BaseModel):
    is_event_post: bool = Field(description="True if the post announces at least one upcoming one-time event")
    reason: str = Field(description="One short sentence explaining the decision, in Spanish")
    events: list[ExtractedEvent]


class BatchPostAnalysis(BaseModel):
    """One post's answer in a batched extraction (batching.py): its letter, then the same fields as PostAnalysis."""

    post: str = Field(description="The post's letter in this request (A, B, C…)")
    is_event_post: bool = Field(description="True if this post announces at least one upcoming one-time event")
    reason: str = Field(description="One short sentence explaining the decision for this post, in Spanish")
    events: list[ExtractedEvent] = Field(description="This post's own events only")


class BatchAnalysis(BaseModel):
    """A batched extraction's answer: one entry per post of the request, checked in code (batching.split_answer)."""

    posts: list[BatchPostAnalysis]


# ---------- Stored data ----------


# STORY: an Instagram story, from screenshots shared to the admin page (stories.py). Its permalink is the account's
# profile (stories last 24 hours), its post_id "story-<hash>", its caption null.
MediaType = Literal["IMAGE", "CAROUSEL_ALBUM", "VIDEO", "STORY"]


class EventMedia(BaseModel):
    """One Instagram post (or story) that announces the event (a flyer, a carousel, a video...)."""

    post_id: str
    permalink: str
    media_type: MediaType
    published: str  # ISO timestamp from Instagram
    flyer: str | None  # image saved under data/, e.g. "flyers/<post_id>-<slide>.webp"
    caption: str | None
    # When the flyer is a video's frame: a few silent seconds of it (clips.py), e.g. "previews/<post_id>-<slide>.mp4"
    preview: str | None = None
    slides: int | None = None  # carousels: how many slides (the site says there's more to see)


class StoredEvent(EventDetails):
    """One record of data/events.json: one event, announced by one or more posts."""

    id: str  # readable and never changed once set, e.g. "social-de-halloween-24-oct" (ids.py); the event's URL
    account: str
    media: list[EventMedia]  # main post first: flyers before videos, newest first (merging.ordered_media)
    # Its account is a bar or club (accounts.txt `bar`, account_options): open every week, so the site can set these
    # apart. Follows accounts.txt on every run (Sweep's start), not what the account was when the event was stored.
    bar: bool = False

    @model_validator(mode="after")
    def _valid_series(self) -> Self:
        """A stored series follows the contract (series_problems). The code keeps it so (normalize.fit_sessions,
        merging.merge_into); this catches a mistake before the site's check does."""
        if problems := series_problems(self):
            raise ValueError(f"event {self.id}: {'; '.join(problems)}")
        return self


class HiddenEvent(BaseModel):
    """One record of state/hidden_events.json, keyed by event id: an event taken off the site by hand ("Ocultar",
    Sweep.hide_event). The sweeps never publish it again from the same posts, nor from a later post of the same
    event (merging.matches_hidden); adding a post by hand (Agregar, Volver a leer) lifts it."""

    hidden_at: str
    event: StoredEvent  # as it was on the site: what later posts are compared with


PostOutcome = Literal["event", "merged", "discarded", "not_event", "rejected", "hidden"]


def had_events(outcome: PostOutcome | None, is_event_post: bool) -> bool:
    """Whether a post became or joined events (a record's `outcome`). Records from before outcomes were kept (None):
    if Gemini called it an event post."""
    return outcome in ("event", "merged") or (outcome is None and is_event_post)


class ProcessedPost(BaseModel):
    """One record of state/processed_posts.json, keyed by post id."""

    account: str
    permalink: str
    processed_at: str
    is_event_post: bool
    reason: str
    model: str
    # Extracted by a lighter model because Flash was out of quota or busy: re-extracted with Flash on a later run.
    provisional: bool = False
    # Fingerprint of the caption analyzed: if the academy edits it (e.g. adds the venue), it's analyzed again.
    caption_hash: str | None = None
    # What became of it, so `admin why` can explain a missing event (None: analyzed before this was recorded):
    #   event: published as new events · merged: added to events another post announced · discarded: an event
    #   post whose events weren't publishable (`detail`: "recurrente", "sin fecha") · not_event · rejected ·
    #   hidden: a story, or the events of a post, taken off the site by hand ("Ocultar historia", "Ocultar")
    outcome: PostOutcome | None = None
    event_ids: list[str] = []  # the events it became or was merged into
    detail: str | None = None
    # Stories: a perceptual hash (stories.image_hash) of each screenshot, so the same story shared again (another
    # screenshot of it) is recognized.
    image_hashes: list[str] = []
    # Added by hand (Agregar, Volver a leer, a story's screenshots): later reads of it (an upgrade, an edited caption)
    # skip the account's extra rules and style filter too (account_options), as the first one did.
    by_hand: bool = False


# ---------- Stories: screenshots shared to the admin page (stories.py) ----------


class StoryImage(BaseModel):
    index: int = Field(description="The screenshot's number, from 0")
    content_box: list[int] | None = Field(
        description="Where the story's own content (the flyer, photo or video frame) is in this screenshot, "
        "without Instagram's interface (the progress bars and account name at the top, the reply bar and buttons "
        "at the bottom): [ymin, xmin, ymax, xmax], each from 0 to 1000. Null if it shows no event content."
    )


class StorySession(BaseModel):
    """One session of a workshop series in a story, as printed (its date is worked out in code)."""

    day: int = Field(description="Day of the month as printed (1-31)")
    month: int | None = Field(
        description="Its month (1-12): printed next to it, or the month the story gives for the group it belongs to "
        "('8, 22 y 29 de noviembre' → 11 for each); null if no month is printed"
    )
    start_time: str | None = Field(description="HH:MM, 24-hour")
    end_time: str | None = Field(description="HH:MM, 24-hour")


class StoryEvent(BaseModel):
    """An event read from a story. Its date is worked out in code (stories.resolve_date) from what's printed."""

    title: str
    event_type: EventType = Field(
        description="social = a night for dancers (an academy's or a dance organizer's socials, dance nights, "
        "anniversaries); party = a night out (a bar's or club's special night, a general public party); "
        "workshop = one-time workshops, masterclasses and special classes with guest teachers"
    )
    is_recurring: bool = Field(
        description="True for regular classes or courses (schedules, levels, monthly fees). A weekly social "
        "night is not this: see weekly. Nor is a workshop series with every session dated: see sessions"
    )
    weekly: bool = Field(description="True for a social or party night that repeats every week ('todos los viernes')")
    styles: list[Style] = Field(
        description="Dance styles from the list. Use a salsa/bachata variant only when the story says it; "
        "otherwise plain 'salsa' or 'bachata'."
    )
    organizer: str | None
    venue: str | None = Field(description="Venue name if given (a location sticker counts)")
    address: str | None
    area: str | None = Field(description="Bogotá neighborhood or zone if given")
    date_text: str | None = Field(description="The date exactly as printed, e.g. 'SÁB 12 OCT', 'este viernes'")
    day: int | None = Field(description="Day of the month as printed (1-31); null if none is printed")
    month: int | None = Field(description="Month as printed (1-12); null if none is printed")
    year: int | None = Field(description="The year only if it's printed; null otherwise. Never guess it")
    end_day: int | None = Field(description="Last day of an event over several consecutive days, as printed")
    end_month: int | None = Field(description="Month of that last day, if printed")
    sessions: list[StorySession] | None = Field(
        description="Only for a workshop series (a taller, intensivo, curso corto, bootcamp or ciclo whose 2 to 12 "
        "sessions each have their own date printed, on separate non-consecutive days): every session, in order, as "
        "printed. Then day, month and year are the first session's. Null for every other event"
    )
    weekday: str | None = Field(
        description="The weekday printed or meant ('sábado' for 'SÁB' or 'este sábado'), Spanish, lowercase"
    )
    relative_day: Literal["hoy", "mañana"] | None = Field(
        description="'hoy' for 'hoy' or 'esta noche', 'mañana' for 'mañana'; null otherwise"
    )
    start_time: str | None = Field(description="HH:MM, 24-hour")
    end_time: str | None = Field(description="HH:MM, 24-hour")
    prices: list[Price]
    artists: list[str] = Field(description="Guest teachers, DJs, orchestras, performers")
    activities: list[str] = Field(description="Short Spanish phrases, e.g. 'clase de bachata', 'show'")
    contact: str | None = Field(
        description="How to reach the organizer: an @username, a website, or a phone number ('WhatsApp ' "
        "before a number marked as WhatsApp)"
    )
    confidence: Confidence
    doubts: list[str] = Field(description="Important missing or assumed information, short phrases in Spanish")
    image_index: int | None = Field(description="The screenshot that shows this event best")
    same_as: str | None = Field(
        description="If this is one of the KNOWN EVENTS listed in the prompt, that event's id; null otherwise"
    )


class StoryAnalysis(BaseModel):
    is_event_post: bool = Field(description="True if the story announces at least one upcoming one-time event")
    reason: str = Field(description="One short sentence explaining the decision, in Spanish")
    account_in_image: str | None = Field(
        description="The username shown at the top of the story, next to its avatar, exactly as shown (it may "
        "end in '…' when cut off). Null if not visible"
    )
    reshared_from: str | None = Field(
        description="When the story reshares another account's post or story (a card with that account's "
        "@username on it), that username. Null otherwise"
    )
    mentions_in_image: list[str] = Field(description="@usernames in mention stickers or text, without the '@'")
    location_sticker: str | None = Field(description="The text of a location sticker, if any")
    story_age: str | None = Field(
        description="How long ago the story was posted, as shown next to the username ('5 h', '32 min')"
    )
    images: list[StoryImage]
    events: list[StoryEvent]


# ---------- Account discovery (python -m pa_bailar discover) ----------

AccountKind = Literal[
    "academy", "venue", "organizer", "dance_company", "teacher", "musician", "dance_other", "not_dance"
]


class AccountClassification(BaseModel):
    kind: AccountKind = Field(
        description="academy = dance school/academy; venue = bar, club or salsoteca with dancing; "
        "organizer = events, socials, festivals or congresses; dance_company = performing group; "
        "teacher = individual teacher, dancer or dance couple; musician = orchestra, band, singer or DJ "
        "that plays for dancing; dance_other = other dance-related (shops, media, photographers); "
        "not_dance = unrelated to dancing"
    )
    in_bogota: Literal["yes", "no", "unknown"] = Field(
        description="Is it based in or regularly active in Bogotá, Colombia? Use the bio, website, "
        "addresses, neighborhoods and captions. 'unknown' if there's no evidence either way."
    )
    city: str | None = Field(description="City it's based in, if stated")
    styles: list[Style] = Field(description="Dance styles it teaches or plays, from the list")
    announces_events: bool = Field(
        description="Do its recent captions announce one-time dated events (socials, parties, workshops, "
        "intensives, shows, concerts)? Regular weekly classes alone don't count."
    )
    reason: str = Field(description="One short sentence explaining the classification, in Spanish")


class AccountState(BaseModel):
    """One record of state/accounts.json, keyed by Instagram username."""

    first_seen: str
    backfill_done: bool = False  # True once its first, deeper sweep has analyzed every post
    last_swept_at: str | None = None  # when a sweep last read it (ISO, Bogotá): its next turn (Sweep._due_accounts)
    latest_post: str | None = None  # its newest post's date (YYYY-MM-DD): accounts posting rarely are read less often
    # Post id → the runs on which no model gave valid JSON for it (gemini.UnreadableAnswerError): at
    # config.UNREADABLE_RUNS it's recorded as rejected, so it stops spending Flash's quota.
    unreadable: dict[str, int] = {}


class GeminiUsage(BaseModel):
    """state/gemini_usage.json: one Gemini quota day (Pacific, gemini.quota_day) of requests per model, and the models
    Gemini said the key can't use that day (gemini.ModelPool). The sweeps share it through the sweep-state branch."""

    day: str = ""
    requests: dict[str, int] = Field(default_factory=dict)
    unavailable: list[str] = Field(default_factory=list)

    def on(self, day: str) -> "GeminiUsage":
        """This usage if it's `day`'s, else none: a new quota day starts from nothing."""
        return self if self.day == day else GeminiUsage(day=day)
