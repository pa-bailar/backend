"""One event, many posts: match a newly extracted event to a stored one and merge them.

Academies often announce the same event several times (a flyer, then a video, then a reminder), and an
organizer and its venue, or two collaborators, may each post it. Those posts must end up as ONE event that
lists all of them in `media`, under the account that posted it first.
"""

from datetime import date

from . import config
from .models import EventDetails, EventMedia, ExtractedEvent, StoredEvent, series_problems
from .text import fold

_DETAIL_FIELDS = list(EventDetails.model_fields)
# Logistics a later post may correct (rescheduled, new prices): the newest post's value wins. Everything
# else keeps the first known value (the flyer's title beats a reminder's caption) and is only filled in
# when missing (a venue "to be confirmed" on the flyer, given later in a reminder).
_UPDATABLE_FIELDS = {"date", "end_date", "weekday", "start_time", "end_time", "prices"}
# What a single day can't change in an event over several days: a post about one of its days (a teacher's
# class, one night, one session of a workshop series) is part of the event, not a new date for it.
_RANGE_FIELDS = {"date", "end_date", "weekday", "start_time", "end_time"}
# An event's first and last day, and a workshop series' sessions, taken together from one post (merge_into).
_DAY_FIELDS = {"date", "end_date", "sessions"}
_EMPTY: tuple[object, ...] = (None, "", [])


# Main post first: flyers (images and carousels), then videos, then stories (a crop of a screenshot, linked to a
# profile rather than a post): a post's flyer is the cover whenever the event has one.
_MEDIA_ORDER = {"VIDEO": 1, "STORY": 2}


def ordered_media(media: list[EventMedia]) -> list[EventMedia]:
    """An event's posts, main post first: flyers (images and carousels) before videos, stories last, and the
    newest first within each, so the latest flyer is the event's cover (a corrected or updated flyer replaces
    the first announcement)."""
    newest_first = sorted(media, key=lambda item: item.published, reverse=True)
    return sorted(newest_first, key=lambda item: _MEDIA_ORDER.get(item.media_type, 0))  # stable: newest first


def _days(event: EventDetails) -> tuple[str, str] | None:
    """The event's first and last day (the same for a one-day event); None without a date."""
    return (event.date, event.end_date or event.date) if event.date else None


def _within(day: str, event: EventDetails) -> bool:
    """Whether the event takes place that day: one of a series' sessions, or a day from its first to its last."""
    if event.sessions:
        return day in event.session_dates
    days = _days(event)
    return days is not None and days[0] <= day <= days[1]


def _overlap(a: EventDetails, b: EventDetails) -> bool:
    """Whether two events share a day: the same date, a day within an event over several days, or one of a
    workshop series' sessions (the days between them aren't the series')."""
    if a.sessions or b.sessions:
        series, other = (a, b) if a.sessions else (b, a)
        return any(_within(day, other) for day in series.session_dates)
    days_a, days_b = _days(a), _days(b)
    if days_a is None or days_b is None:
        return False
    return days_a[0] <= days_b[1] and days_b[0] <= days_a[1]


def _multi_day(event: EventDetails) -> bool:
    """Over several days: consecutive ones (end_date), or a workshop series' sessions."""
    return bool(event.end_date or event.sessions)


def _same_series(a: EventDetails, b: EventDetails) -> bool:
    """Two workshop series of one account are the same program when most sessions match (at least half of the
    shorter one's), with the same start time on a session they share when both give one, and the same title or
    distinctive title words in common: two levels of one academy's intensive on the same Sundays ("Nivel 1",
    "Nivel 2") have different times, or a title that tells them apart."""
    shared = sorted(set(a.session_dates) & set(b.session_dates))
    if 2 * len(shared) < min(len(a.session_dates), len(b.session_dates)):
        return False
    times_a = {s.date: s.start_time for s in a.sessions or []}
    times_b = {s.date: s.start_time for s in b.sessions or []}
    if any(times_a[day] and times_b[day] and times_a[day] != times_b[day] for day in shared):
        return False
    return fold(a.title) == fold(b.title) or _share_title(a, b)


def _session_of(series: EventDetails, other: EventDetails) -> bool:
    """A post about one session of a workshop series (a reminder, "sesión 3"): one of its session days, no clash
    in start time with that session, and the same title, a distinctive title word in common, or the same venue
    (both known) at the same start time."""
    day = other.date
    if not day or other.end_date or other.sessions or day not in series.session_dates:
        return False
    session = next(s for s in series.sessions or [] if s.date == day)
    same_time = bool(other.start_time) and other.start_time == session.start_time
    if other.start_time and session.start_time and not same_time:
        return False
    if fold(series.title) == fold(other.title) or _title_words(series.title) & _title_words(other.title):
        return True
    venues = _key(series.venue), _key(other.venue)
    return all(venues) and venues[0] == venues[1] and same_time


def looks_like_same_event(stored: StoredEvent, account: str, candidate: EventDetails) -> bool:
    """Rule-based fallback when Gemini didn't link the post: same account and a day in common, plus
    - for two one-day events: the same start time, or the same title when a start time is missing;
    - when either lasts several days: the same title, or distinctive title words in common (a festival
      and a post about its teacher), never the start time alone (a festival weekend has several nights);
    - a workshop series and a post about one of its sessions: _session_of; two series: _same_series.
    """
    if stored.account != account or not _overlap(stored, candidate):
        return False
    if stored.sessions and candidate.sessions:
        return _same_series(stored, candidate)
    if stored.sessions or candidate.sessions:
        series, other = (stored, candidate) if stored.sessions else (candidate, stored)
        return _session_of(series, other)
    if _multi_day(stored) or _multi_day(candidate):
        return fold(stored.title) == fold(candidate.title) or _share_title(stored, candidate)
    if stored.start_time and candidate.start_time:
        return stored.start_time == candidate.start_time
    return fold(stored.title) == fold(candidate.title)


# Words every dance event's title shares: they don't tell two events apart.
# Compared folded (no accents). Place names too: "Bogotá" in a title doesn't name @bogotadanceclub.
_COMMON_WORDS = {
    *("social", "sociales", "clase", "clases", "taller", "talleres", "workshop", "fiesta", "noche", "baile"),
    *("bailes", "evento", "dance", "gran"),
    *("bachata", "salsa", "kizomba", "zouk", "tango", "merengue", "champeta", "cumbia", "urbano", "urbana"),
    *("sensual", "dominicana", "calena"),
    *("los", "las", "del", "con", "por", "para", "una", "uno", "the", "and", "nuestro", "nuestra", "este", "esta"),
    *("bogota", "colombia", "cali", "medellin"),
}
# Kinds and occasions of events: within one account "Aniversario" names its anniversary, but across accounts
# two "Halloween Party" or "Festival … 2026" titles are as likely two events as one.
_EVENT_WORDS = {
    *("congress", "congreso", "festival", "fest", "party", "parties", "fiestas", "halloween", "navidad"),
    *("navideno", "navidena", "aniversario", "anniversary", "internacional", "international", "edicion"),
    *("edition", "tour", "night", "nights", "noches", "workshops", "master", "masterclass", "masterclasses"),
    *("intensivo", "intensive", "bootcamp", "competencia", "competition", "campeonato", "championship"),
    *("concurso", "batalla", "battle", "encuentro", "gala", "show", "especial", "special", "weekend"),
    *("cumpleanos", "fin", "ano", "nuevo", "clausura", "lanzamiento", "inauguracion", "retiro"),
}


def _key(text: str | None) -> str:
    """Letters and digits only, folded: 'Distrito Social' → 'distritosocial', '@ludance.studios' → 'ludancestudios'."""
    return "".join(char for char in fold(text) if char.isalnum())


def _title_words(title: str, across_accounts: bool = False) -> set[str]:
    """A title's distinctive words: no common words, nothing with a digit (years, "100%", "5to"), and across
    accounts no kind of event either (`_EVENT_WORDS`)."""
    words = "".join(char if char.isalnum() else " " for char in fold(title)).split()
    ignored = _COMMON_WORDS | _EVENT_WORDS if across_accounts else _COMMON_WORDS
    return {word for word in words if len(word) >= 3 and word not in ignored and not any(c.isdigit() for c in word)}


def _share_title(a: EventDetails, b: EventDetails, across_accounts: bool = False) -> bool:
    """Two or more distinctive title words in common, most of the shorter title's ("Level Up … Fusion Congress")."""
    words_a, words_b = _title_words(a.title, across_accounts), _title_words(b.title, across_accounts)
    shared = words_a & words_b
    return len(shared) >= 2 and len(shared) / (min(len(words_a), len(words_b)) or 1) >= 0.6


def _names_account(event: EventDetails, account: str) -> bool:
    """Whether the event names this account: its organizer, venue or contact is the account (or the account's
    name starts with it, 'Bachatamanía' for @bachatamania_bogota), or the title names it."""
    handle = _key(account)
    names = [_key(event.organizer), _key(event.venue), _key(event.contact)]
    if any(len(name) >= 5 and (handle.startswith(name) or name.startswith(handle)) for name in names):
        return True
    words = _title_words(event.title, across_accounts=True)
    return any(len(word) >= 5 and handle.startswith(_key(word)) for word in words)


def looks_like_shared_event(stored: StoredEvent, account: str, candidate: EventDetails) -> bool:
    """Rule-based match across accounts (an organizer and its venue, or two collaborators, each posting the
    flyer): a day in common, no clash in start time (compared between one-day events only) or venue, and one of
      - one event names the other's account, plus the same start time or a title word in common;
      - the same venue (both known), plus the same start time and a title word in common, or two or more
        distinctive title words in common, kinds of events aside ("Level Up … Fusion Congress").
    Titles alone never merge two accounts' events: "Halloween Party" or "Festival … 2026" may be two events.
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
    # With an account named or the same venue and time, any title word in common will do ("Halloween").
    shared = _title_words(stored.title) & _title_words(candidate.title)
    if _names_account(stored, account) or _names_account(candidate, stored.account):
        return same_time or bool(shared)
    if not all(venues):  # without the same venue, titles alone don't tie two accounts' posts together
        return False
    return (same_time and bool(shared)) or _share_title(stored, candidate, across_accounts=True)


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


def matches_hidden(hidden: StoredEvent, account: str, candidate: ExtractedEvent, post_id: str) -> bool:
    """Whether an extracted event is one taken off the site by hand (models.HiddenEvent): read again from one of
    its posts (the same event by the same-account rules: a post can announce several events on one day, a workshop
    at 16:00 and a social at 21:00, and hiding one keeps the other), linked to it by Gemini (with a day in common),
    or the same event by the merging rules (a later reminder of it, another account's post of it). Anything else is
    a new event, even from the same account."""
    same_post = post_id in {media.post_id for media in hidden.media} and _overlap(hidden, candidate)
    if same_post and (
        looks_like_same_event(hidden, hidden.account, candidate) or fold(hidden.title) == fold(candidate.title)
    ):
        return True
    if candidate.same_as == hidden.id and hidden.account == account:
        return True
    return looks_like_same_event(hidden, account, candidate) or looks_like_shared_event(hidden, account, candidate)


def merge_into(stored: StoredEvent, candidate: EventDetails, media: EventMedia) -> StoredEvent:
    """Add a post to an existing event: fill in what it was missing, and take dates, times and prices from
    the post if it's the newest one announcing the event (an older post re-analyzed never overrides). A post
    about one day of an event over several days (no range of its own, a day within the event's) leaves its
    days and times as they are.

    The first and last day go together: the newest post's days replace both (one day, as posted, drops the
    old last day), and an older post only gives a missing last day to an event that starts the same day."""
    others = [m for m in stored.media if m.post_id != media.post_id]
    is_newest = all(media.published >= other.published for other in others)
    one_of_its_days = _multi_day(stored) and not _multi_day(candidate) and _overlap(stored, candidate)
    updates: dict[str, object] = {}
    for field in _DETAIL_FIELDS:
        current, new = getattr(stored, field), getattr(candidate, field)
        if field in _DAY_FIELDS or new in _EMPTY or (one_of_its_days and field in _RANGE_FIELDS):
            continue
        if current in _EMPTY or (is_newest and field in _UPDATABLE_FIELDS and new != current):
            updates[field] = new
    if candidate.date and not one_of_its_days:
        if is_newest or not stored.date:
            updates |= {"date": candidate.date, "end_date": candidate.end_date, "sessions": candidate.sessions}
        elif _completes_series(stored, candidate):
            first = (candidate.sessions or [])[0]
            updates |= {
                **{field: getattr(candidate, field) for field in ("date", "end_date", "sessions", "weekday")},
                "start_time": first.start_time or stored.start_time,
                "end_time": first.end_time or stored.end_time,
            }
        elif not stored.end_date and candidate.end_date and not candidate.sessions and candidate.date == stored.date:
            updates["end_date"] = candidate.end_date
    updates["media"] = ordered_media([*others, media])
    merged = stored.model_copy(update=updates)
    if not _valid_range(merged):  # a new date the old last day doesn't fit (rescheduled): one day, as posted
        merged.end_date, merged.sessions = None, None
    return merged


def _completes_series(stored: EventDetails, candidate: EventDetails) -> bool:
    """An older post with a whole workshop series (the program's flyer) for an event stored from a post about one
    of its sessions: the event becomes the series."""
    return (
        bool(candidate.sessions)
        and not stored.sessions
        and not stored.end_date
        and _within(stored.date or "", candidate)
    )


def _valid_range(event: EventDetails) -> bool:
    """No end_date, or one after the first day and within MAX_EVENT_DAYS of it (normalize.parse_end_date); a
    workshop series: its sessions follow the rules (models.series_problems)."""
    if event.sessions:
        return not series_problems(event)
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
