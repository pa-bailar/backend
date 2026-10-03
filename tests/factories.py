"""Builders for test data."""

import io
from datetime import timedelta

from PIL import Image

from pa_bailar import config
from pa_bailar.ids import new_event_id
from pa_bailar.models import EventMedia, ExtractedEvent, StoredEvent

# Always a week ahead: tests that run the sweep must not age out of its windows as real days pass.
EVENT_DATE = (config.now_bogota().date() + timedelta(days=8)).isoformat()

DETAILS = {
    "title": "Social",
    "event_type": "social",
    "is_recurring": False,
    "styles": ["salsa"],
    "organizer": None,
    "venue": None,
    "address": None,
    "area": None,
    "date": EVENT_DATE,
    "end_date": None,
    "weekday": None,
    "start_time": None,
    "end_time": None,
    "prices": [],
    "artists": [],
    "activities": [],
    "contact": None,
    "confidence": "high",
    "doubts": [],
}


def make_image() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 500), "red").save(buffer, "JPEG")
    return buffer.getvalue()


def extracted(image_index: int | None = 0, same_as: str | None = None, **details) -> ExtractedEvent:
    return ExtractedEvent(**(DETAILS | details), image_index=image_index, same_as=same_as)


def media(post_id: str = "p1", media_type: str = "IMAGE", published: str = "2026-10-01T12:00:00+0000") -> EventMedia:
    return EventMedia(
        post_id=post_id,
        permalink=f"https://www.instagram.com/p/{post_id}/",
        media_type=media_type,
        published=published,
        flyer=f"flyers/{post_id}-0.webp",
        caption=None,
    )


def stored(event_id: str = "p1-0", account: str = "academia", posts: list[EventMedia] | None = None, **details):
    return StoredEvent(**(DETAILS | details), id=event_id, account=account, media=posts or [media()])


def event_id(title: str) -> str:
    """The id the sweep gives a new event with this title on EVENT_DATE."""
    return new_event_id(title, EVENT_DATE, set())
