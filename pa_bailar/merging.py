"""One event, many posts: match a newly extracted event to a stored one and merge them.

Academies often announce the same event several times (a flyer, then a video, then a reminder), and an
organizer and its venue, or two collaborators, may each post it. Those posts must end up as ONE event that
lists all of them in `media`, under the account that posted it first.
"""

from .models import EventDetails, EventMedia, ExtractedEvent, StoredEvent
from .text import fold

_DETAIL_FIELDS = list(EventDetails.model_fields)
# Logistics a later post may correct (rescheduled, new prices): the newest post's value wins. Everything
# else keeps the first known value (the flyer's title beats a reminder's caption) and is only filled in
# when missing (a venue "to be confirmed" on the flyer, given later in a reminder).
_UPDATABLE_FIELDS = {"date", "weekday", "start_time", "end_time", "prices"}
_EMPTY: tuple[object, ...] = (None, "", [])


def ordered_media(media: list[EventMedia]) -> list[EventMedia]:
    """An event's posts, main post first: flyers (images and carousels) before videos, and the newest
    first within each, so the latest flyer is the event's cover (a corrected or updated flyer replaces
    the first announcement)."""
    newest_first = sorted(media, key=lambda item: item.published, reverse=True)
    return sorted(newest_first, key=lambda item: item.media_type == "VIDEO")  # stable: keeps newest first


def looks_like_same_event(stored: StoredEvent, account: str, candidate: EventDetails) -> bool:
    """Rule-based fallback when Gemini didn't link the post: same account and date, plus the same
    start time, or the same title when a start time is missing."""
    if stored.account != account or stored.date != candidate.date:
        return False
    if stored.start_time and candidate.start_time:
        return stored.start_time == candidate.start_time
    return fold(stored.title) == fold(candidate.title)


# Words every dance event's title shares: they don't tell two events apart.
# Compared folded (no accents). Place names too: "Bogotá" in a title doesn't name @bogotadanceclub.
_COMMON_WORDS = {
    *("social", "sociales", "clase", "clases", "taller", "talleres", "workshop", "fiesta", "noche", "baile"),
    *("bailes", "evento", "dance", "gran", "100"),
    *("bachata", "salsa", "kizomba", "zouk", "tango", "merengue", "champeta", "cumbia", "urbano", "urbana"),
    *("sensual", "dominicana", "calena"),
    *("los", "las", "del", "con", "por", "para", "una", "uno", "the", "and", "nuestro", "nuestra", "este", "esta"),
    *("bogota", "colombia", "cali", "medellin"),
}


def _key(text: str | None) -> str:
    """Letters and digits only, folded: 'Distrito Social' → 'distritosocial', '@ludance.studios' → 'ludancestudios'."""
    return "".join(char for char in fold(text) if char.isalnum())


def _title_words(title: str) -> set[str]:
    words = "".join(char if char.isalnum() else " " for char in fold(title)).split()
    return {word for word in words if len(word) >= 3 and word not in _COMMON_WORDS}


def _names_account(event: EventDetails, account: str) -> bool:
    """Whether the event names this account: its organizer, venue or contact is the account (or the account's
    name starts with it, 'Bachatamanía' for @bachatamania_bogota), or the title names it."""
    handle = _key(account)
    names = [_key(event.organizer), _key(event.venue), _key(event.contact)]
    if any(len(name) >= 5 and (handle.startswith(name) or name.startswith(handle)) for name in names):
        return True
    return any(len(word) >= 5 and handle.startswith(_key(word)) for word in _title_words(event.title))


def looks_like_shared_event(stored: StoredEvent, account: str, candidate: EventDetails) -> bool:
    """Rule-based match across accounts (an organizer and its venue, or two collaborators, each posting the
    flyer): same date, no clash in start time or venue, and one of
      - one event names the other's account, plus the same start time or a title in common;
      - the same venue and start time, plus a title in common;
      - two or more distinctive title words in common ("Level Up … Fusion Congress").
    """
    if stored.account == account or not stored.date or stored.date != candidate.date:
        return False
    if stored.start_time and candidate.start_time and stored.start_time != candidate.start_time:
        return False
    venues = _key(stored.venue), _key(candidate.venue)
    if all(venues) and venues[0] not in venues[1] and venues[1] not in venues[0]:
        return False
    same_time = bool(stored.start_time) and stored.start_time == candidate.start_time
    shared = _title_words(stored.title) & _title_words(candidate.title)
    smaller = min(len(_title_words(stored.title)), len(_title_words(candidate.title))) or 1
    if _names_account(stored, account) or _names_account(candidate, stored.account):
        return same_time or bool(shared)
    if all(venues) and same_time:
        return bool(shared)
    return len(shared) >= 2 and len(shared) / smaller >= 0.6


def find_existing(
    events: list[StoredEvent], account: str, candidate: ExtractedEvent, post_id: str
) -> StoredEvent | None:
    """The stored event this extracted one refers to, if any. Gemini's `same_as` wins over the rules; the
    same account's events come before other accounts' (no Gemini request: Gemini only sees this account's).

    Events that already contain `post_id` are never matched: two events announced in the same post
    are different events, even if they share a date and time.
    """
    others = [e for e in events if all(m.post_id != post_id for m in e.media)]
    if candidate.same_as:
        linked = next((e for e in others if e.id == candidate.same_as and e.account == account), None)
        if linked:
            return linked
    same_account = next((e for e in others if looks_like_same_event(e, account, candidate)), None)
    return same_account or next((e for e in others if looks_like_shared_event(e, account, candidate)), None)


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
    updates["media"] = ordered_media([*others, media])
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
