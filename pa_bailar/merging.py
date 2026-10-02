"""One event, many posts: match a newly extracted event to a stored one and merge them.

Academies often announce the same event several times (a flyer, then a video, then a reminder).
Those posts must end up as ONE event that lists all of them in `media`.
"""

from .models import EventDetails, EventMedia, ExtractedEvent, StoredEvent
from .text import fold

_DETAIL_FIELDS = list(EventDetails.model_fields)
# Logistics a later post may correct (rescheduled, new prices): the newest post's value wins. Everything
# else keeps the first known value (the flyer's title beats a reminder's caption) and is only filled in
# when missing (a venue "to be confirmed" on the flyer, given later in a reminder).
_UPDATABLE_FIELDS = {"date", "weekday", "start_time", "end_time", "prices"}
_EMPTY = (None, "", [])


def media_order(media: EventMedia) -> tuple[int, str]:
    """Images and carousels first (they carry the flyer), videos last; then oldest first."""
    return (1 if media.media_type == "VIDEO" else 0, media.published)


def looks_like_same_event(stored: StoredEvent, account: str, candidate: EventDetails) -> bool:
    """Rule-based fallback when Gemini didn't link the post: same account and date, plus the same
    start time, or the same title when a start time is missing."""
    if stored.account != account or stored.date != candidate.date:
        return False
    if stored.start_time and candidate.start_time:
        return stored.start_time == candidate.start_time
    return fold(stored.title) == fold(candidate.title)


def find_existing(
    events: list[StoredEvent], account: str, candidate: ExtractedEvent, post_id: str
) -> StoredEvent | None:
    """The stored event this extracted one refers to, if any. Gemini's `same_as` wins over the rules.

    Events that already contain `post_id` are never matched: two events announced in the same post
    are different events, even if they share a date and time.
    """
    others = [e for e in events if all(m.post_id != post_id for m in e.media)]
    if candidate.same_as:
        linked = next((e for e in others if e.id == candidate.same_as and e.account == account), None)
        if linked:
            return linked
    return next((e for e in others if looks_like_same_event(e, account, candidate)), None)


def merge_into(stored: StoredEvent, candidate: EventDetails, media: EventMedia) -> StoredEvent:
    """Add a post to an existing event: fill in what it was missing, and take date, times and prices from
    the post if it's the newest one announcing the event (an older post re-analyzed never overrides)."""
    others = [m for m in stored.media if m.post_id != media.post_id]
    is_newest = all(media.published >= other.published for other in others)
    updates = {}
    for field in _DETAIL_FIELDS:
        current, new = getattr(stored, field), getattr(candidate, field)
        if new in _EMPTY:
            continue
        if current in _EMPTY or (is_newest and field in _UPDATABLE_FIELDS and new != current):
            updates[field] = new
    updates["media"] = sorted([*others, media], key=media_order)
    return stored.model_copy(update=updates)


def detach_post(events: list[StoredEvent], post_id: str) -> list[StoredEvent]:
    """Remove a post from every event (used before re-analyzing it). Events left without posts disappear."""
    result = []
    for event in events:
        remaining = [m for m in event.media if m.post_id != post_id]
        if remaining:
            result.append(
                event if len(remaining) == len(event.media) else event.model_copy(update={"media": remaining})
            )
    return result
