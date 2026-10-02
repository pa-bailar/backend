"""Data models: what Gemini returns and what is stored in data/events.json.

These models are the source of truth for the data contract with the frontend
(frontend/src/scripts/types.ts mirrors StoredEvent).
"""

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["social", "workshop", "concert", "festival", "competition", "show", "other"]
Confidence = Literal["high", "medium", "low"]


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
    styles: list[str] = Field(description="Dance styles, lowercase Spanish: salsa, bachata, mambo, champeta, urbano...")
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


class PostAnalysis(BaseModel):
    is_event_post: bool = Field(description="True if the post announces at least one upcoming one-time event")
    reason: str = Field(description="One short sentence explaining the decision, in Spanish")
    events: list[ExtractedEvent]


# ---------- Stored data ----------


class EventSource(BaseModel):
    account: str
    post_id: str
    permalink: str
    published: str
    caption: str | None


class StoredEvent(EventDetails):
    """One record of data/events.json."""

    id: str  # "<post_id>-<index>", deterministic so re-runs never duplicate
    flyer: str | None  # path relative to data/, e.g. "flyers/<post_id>-<slide>.webp"
    source: EventSource


class ProcessedPost(BaseModel):
    """One record of backend/state/processed_posts.json, keyed by post id."""

    account: str
    permalink: str
    processed_at: str
    is_event_post: bool
    reason: str
    model: str
