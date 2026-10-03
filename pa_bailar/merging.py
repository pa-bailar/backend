"""One event, many posts: match a newly extracted event to a stored one and merge them.

Academies often announce the same event several times (a flyer, then a video, then a reminder), and an
organizer and its venue, or two collaborators, may each post it. Those posts must end up as ONE event that
lists all of them in `media`, under the account that posted it first.
"""

from datetime import date

from . import config
from .models import EventDetails, EventMedia, ExtractedEvent, StoredEvent
from .text import fold

_DETAIL_FIELDS = list(EventDetails.model_fields)
# Logistics a later post may correct (rescheduled, new prices): the newest post's value wins. Everything
# else keeps the first known value (the flyer's title beats a reminder's caption) and is only filled in
# when missing (a venue "to be confirmed" on the flyer, given later in a reminder).
_UPDATABLE_FIELDS = {"date", "end_date", "weekday", "start_time", "end_time", "prices"}
# What a single day can't change in an event over several days: a post about one of its days (a teacher's
# class, one night) is part of the event, not a new date for it.
_RANGE_FIELDS = {"date", "end_date", "weekday", "start_time", "end_time"}
_EMPTY: tuple[object, ...] = (None, "", [])


def ordered_media(media: list[EventMedia]) -> list[EventMedia]:
    """An event's posts, main post first: flyers (images and carousels) before videos, and the newest
    first within each, so the latest flyer is the event's cover (a corrected or updated flyer replaces
    the first announcement)."""
    newest_first = sorted(media, key=lambda item: item.published, reverse=True)
    return sorted(newest_first, key=lambda item: item.media_type == "VIDEO")  # stable: keeps newest first


def _days(event: EventDetails) -> tuple[str, str] | None:
    """The event's first and last day (the same for a one-day event); None without a date."""
    return (event.date, event.end_date or event.date) if event.date else None


def _overlap(a: EventDetails, b: EventDetails) -> bool:
    """Whether two events share a day: the same date, or a day within an event over several days."""
    days_a, days_b = _days(a), _days(b)
    if days_a is None or days_b is None:
        return False
    return days_a[0] <= days_b[1] and days_b[0] <= days_a[1]


def _multi_day(event: EventDetails) -> bool:
    return bool(event.end_date)


def looks_like_same_event(stored: StoredEvent, account: str, candidate: EventDetails) -> bool:
    """Rule-based fallback when Gemini didn't link the post: same account and a day in common, plus
    - for two one-day events: the same start time, or the same title when a start time is missing;
    - when either lasts several days: the same title, or distinctive title words in common (a festival
      and a post about its teacher), never the start time alone (a festival weekend has several nights).
    """
    if stored.account != account or not _overlap(stored, candidate):
        return False
    if _multi_day(stored) or _multi_day(candidate):
        return fold(stored.title) == fold(candidate.title) or _share_title(stored, candidate)
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


def _share_title(a: EventDetails, b: EventDetails) -> bool:
    """Two or more distinctive title words in common, most of the shorter title's ("Level Up … Fusion Congress")."""
    words_a, words_b = _title_words(a.title), _title_words(b.title)
    shared = words_a & words_b
    return len(shared) >= 2 and len(shared) / (min(len(words_a), len(words_b)) or 1) >= 0.6


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
    flyer): a day in common, no clash in start time (compared between one-day events only) or venue, and one of
      - one event names the other's account, plus the same start time or a title in common;
      - the same venue and start time, plus a title in common;
      - two or more distinctive title words in common ("Level Up … Fusion Congress").
    """
    if stored.account == account or not _overlap(stored, candidate):
        return False
    one_day = not _multi_day(stored) and not _multi_day(candidate)
    if one_day and stored.start_time and candidate.start_time and stored.start_time != candidate.start_time:
        return False
    venues = _key(stored.venue), _key(candidate.venue)
    if all(venues) and venues[0] not in venues[1] and venues[1] not in venues[0]:
        return False
    same_time = one_day and bool(stored.start_time) and stored.start_time == candidate.start_time
    shared = _title_words(stored.title) & _title_words(candidate.title)
    if _names_account(stored, account) or _names_account(candidate, stored.account):
        return same_time or bool(shared)
    if all(venues) and same_time:
        return bool(shared)
    return _share_title(stored, candidate)


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
    """Add a post to an existing event: fill in what it was missing, and take dates, times and prices from
    the post if it's the newest one announcing the event (an older post re-analyzed never overrides). A post
    about one day of an event over several days (no range of its own, a day within the event's) leaves its
    days and times as they are."""
    others = [m for m in stored.media if m.post_id != media.post_id]
    is_newest = all(media.published >= other.published for other in others)
    one_of_its_days = _multi_day(stored) and not _multi_day(candidate) and _overlap(stored, candidate)
    updates = {}
    for field in _DETAIL_FIELDS:
        current, new = getattr(stored, field), getattr(candidate, field)
        if new in _EMPTY or (one_of_its_days and field in _RANGE_FIELDS):
            continue
        if current in _EMPTY or (is_newest and field in _UPDATABLE_FIELDS and new != current):
            updates[field] = new
    updates["media"] = ordered_media([*others, media])
    merged = stored.model_copy(update=updates)
    if not _valid_range(merged):  # a new date the old last day doesn't fit (rescheduled): one day, as posted
        merged.end_date = None
    return merged


def _valid_range(event: EventDetails) -> bool:
    """No end_date, or one after the first day and within MAX_EVENT_DAYS of it (normalize.parse_end_date)."""
    if not event.end_date:
        return True
    if not event.date:
        return False
    days = (date.fromisoformat(event.end_date) - date.fromisoformat(event.date)).days + 1
    return 1 < days <= config.MAX_EVENT_DAYS


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
