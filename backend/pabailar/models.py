"""Data models: what Gemini returns and what is stored in data/events.json.

These models are the source of truth for the data contract with the frontend
(frontend/src/scripts/types.ts mirrors StoredEvent).
"""

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["social", "workshop", "concert", "festival", "competition", "show", "other"]
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
STYLES: tuple[str, ...] = Style.__args__


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
    date: str | None = Field(description="YYYY-MM-DD")
    weekday: str | None = Field(description="Spanish weekday name, lowercase")
    start_time: str | None = Field(description="HH:MM, 24-hour")
    end_time: str | None = Field(description="HH:MM, 24-hour")
    prices: list[Price]
    artists: list[str] = Field(description="Guest teachers, DJs, orchestras, performers")
    activities: list[str] = Field(description="Short Spanish phrases, e.g. 'clase de bachata', 'show'")
    contact: str | None = Field(description="Phone/WhatsApp or @username")
    confidence: Confidence
    doubts: list[str] = Field(description="Missing or assumed information, in Spanish")


# ---------- Gemini response schema ----------


class ExtractedEvent(EventDetails):
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


class StoredEvent(EventDetails):
    """One record of data/events.json: one event, announced by one or more posts."""

    id: str  # readable and never changed once set, e.g. "social-de-halloween-24-oct" (ids.py); the event's URL
    account: str
    media: list[EventMedia]  # main post first: images before videos, then oldest first


class ProcessedPost(BaseModel):
    """One record of backend/state/processed_posts.json, keyed by post id."""

    account: str
    permalink: str
    processed_at: str
    is_event_post: bool
    reason: str
    model: str
    # Extracted by the lighter model because Flash was out of quota: re-extracted with Flash on a later run.
    provisional: bool = False


# ---------- Account discovery (tools/discover_accounts) ----------

AccountKind = Literal["academy", "venue", "organizer", "dance_company", "teacher", "dance_other", "not_dance"]


class AccountClassification(BaseModel):
    kind: AccountKind = Field(
        description="academy = dance school/academy; venue = bar, club or salsoteca with dancing; "
        "organizer = events, socials, festivals or congresses; dance_company = performing group; "
        "teacher = individual dancer or instructor; dance_other = other dance-related (shops, media, "
        "photographers); not_dance = unrelated to dancing"
    )
    in_bogota: Literal["yes", "no", "unknown"] = Field(
        description="Is it based in or regularly active in Bogotá, Colombia? Use the bio, website, "
        "addresses, neighborhoods and captions. 'unknown' if there's no evidence either way."
    )
    city: str | None = Field(description="City it's based in, if stated")
    styles: list[Style] = Field(description="Dance styles it teaches or plays, from the list")
    announces_events: bool = Field(
        description="Do its recent captions announce socials, parties, workshops or other dated events?"
    )
    reason: str = Field(description="One short sentence explaining the classification, in Spanish")


class AccountState(BaseModel):
    """One record of backend/state/accounts.json, keyed by Instagram username."""

    first_seen: str
    backfill_done: bool = False  # True once its first, deeper sweep has analyzed every post
