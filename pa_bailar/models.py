"""Data models: what Gemini returns and what is stored in data/events.json.

These models are the source of truth for the data contract with the frontend
(the site repository's frontend/src/scripts/types.ts mirrors StoredEvent; its check-data.mjs checks
every data PR against the contract).
"""

from typing import Literal, get_args

from pydantic import BaseModel, Field

EventType = Literal["social", "workshop", "concert", "festival", "congress", "competition", "show", "other"]
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
    amount_cop: int = Field(description="Colombian pesos. '15K' or '15 mil' = 15000")
    condition: str | None = Field(None, description="e.g. 'hasta el 24 de septiembre', 'solo 50 cupos'")


class EventDetails(BaseModel):
    """Fields shared by an extracted event and a stored event."""

    title: str
    event_type: EventType = Field(
        description="social = socials, parties, dance nights, anniversaries; "
        "workshop = one-time workshops, masterclasses and special classes with guest teachers"
    )
    is_recurring: bool = Field(description="True for regular classes or nights that repeat (weekly, every Friday...)")
    styles: list[Style] = Field(
        description="Dance styles from the list. Use a salsa/bachata variant only when the post says it; "
        "otherwise plain 'salsa' or 'bachata'."
    )
    organizer: str | None
    venue: str | None = Field(description="Venue name if given")
    address: str | None
    area: str | None = Field(description="Bogotá neighborhood or zone if given")
    date: str | None = Field(description="YYYY-MM-DD; an event over several consecutive days: its first day")
    # Optional in stored data (events stored before it existed have none); ExtractedEvent makes Gemini fill it.
    end_date: str | None = Field(
        None,
        description="Last day (YYYY-MM-DD) of an event over several consecutive days, e.g. 'NOV 13-15' → "
        "2026-11-15. Null for a one-day event.",
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
        """The event's last day: its end_date over several days, else its date. Upcoming until it has passed."""
        return self.end_date or self.date


# ---------- Gemini response schema ----------


class ExtractedEvent(EventDetails):
    # Required (but nullable) like the other fields, so Gemini's response schema asks for it.
    end_date: str | None = Field(
        description="Last day (YYYY-MM-DD) of an event over several consecutive days, e.g. 'NOV 13-15' → "
        "2026-11-15. Null for a one-day event."
    )
    image_index: int | None = Field(
        description="Number of the attached image that shows THIS event (its own flyer, or the schedule slide "
        "where it is listed). Null if no image shows it."
    )
    same_as: str | None = Field(
        description="If this post announces again one of the KNOWN EVENTS listed in the prompt (a video, reminder "
        "or second flyer of the same event), that event's id. Null for a new event."
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


# ---------- Stored data ----------


MediaType = Literal["IMAGE", "CAROUSEL_ALBUM", "VIDEO"]


class EventMedia(BaseModel):
    """One Instagram post that announces the event (a flyer, a carousel, a video...)."""

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


PostOutcome = Literal["event", "merged", "discarded", "not_event", "rejected"]


class ProcessedPost(BaseModel):
    """One record of state/processed_posts.json, keyed by post id."""

    account: str
    permalink: str
    processed_at: str
    is_event_post: bool
    reason: str
    model: str
    # Extracted by the lighter model because Flash was out of quota: re-extracted with Flash on a later run.
    provisional: bool = False
    # Fingerprint of the caption analyzed: if the academy edits it (e.g. adds the venue), it's analyzed again.
    caption_hash: str | None = None
    # What became of it, so `admin why` can explain a missing event (None: analyzed before this was recorded):
    #   event: published as new events · merged: added to events another post announced · discarded: an event
    #   post whose events weren't publishable (`detail`: "recurrente", "sin fecha") · not_event · rejected
    outcome: PostOutcome | None = None
    event_ids: list[str] = []  # the events it became or was merged into
    detail: str | None = None


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
    latest_post: str | None = None  # its newest post's date (YYYY-MM-DD): quiet accounts take their turn less often
