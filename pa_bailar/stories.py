"""Stories: events from screenshots of an Instagram story, shared to the admin page (docs/ADMIN.md).

Nothing outside Instagram's app can read a story, so the admin page uploads screenshots of one (up to
MAX_SCREENSHOTS, the slides of one story) and the sweep reads them with one Gemini request (`sweep --story`,
pipeline.Sweep.add_story). This module holds the parts that need neither Gemini nor Instagram:
  - the story's id, `story-<hash>` of the screenshots' bytes (the same screenshots twice are one story, so a
    retried request doesn't publish twice), and a perceptual hash of each screenshot (another screenshot of the
    same story is recognized: `same_story`);
  - when the screenshot was taken: its file name ("Screenshot_20261004-183012…"), else the file's date, else
    when it was uploaded;
  - the event's date, worked out here from what's printed (day, month, weekday, "hoy"), never by Gemini;
  - the flyer: Gemini's box around the story's content, checked and padded, or a fixed crop. Only the crop is
    published, never the screenshot (it can show notifications or the reply bar);
  - the account's name as read in the image, and matching a cut-off one ("salsa_cl…") to a known account.
"""

import difflib
import hashlib
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from PIL import Image

from . import config, links, patterns
from .models import StoryEvent, StorySession
from .text import WEEKDAYS, fold

STORY_PREFIX = "story-"
_STORY_ID = re.compile(patterns.STORY_ID)
MAX_SCREENSHOTS = patterns.MAX_SCREENSHOTS
# Perceptual hashes this close (bits of 64 that differ) are the same story, if shared within SAME_STORY_HOURS of
# each other: a story lasts 24 hours, and an academy's weekly flyer made from one template (only the date
# changes) looks the same to the hash a week later.
HASH_DISTANCE = 10
SAME_STORY_HOURS = 36
FIXED_CROP = 0.12  # of the height, off the top (Instagram's header) and the bottom (the reply bar)
PADDING = 0.03  # added around Gemini's box: full-screen flyers have text near the edges
MIN_BOX_AREA = 0.12  # a smaller box is a misreading (a sticker, the avatar)
BOX_ASPECT = (0.3, 2.5)  # width / height of a plausible flyer
FAR_AHEAD_DAYS = 60  # a date further ahead is flagged for a look
# A printed date at most this many days before the screenshot is that recent day (an event that just passed: a
# screenshot taken after midnight of last night's social), not next year's.
RECENT_PAST_DAYS = 7
SCREENSHOT_MAX_AGE_DAYS = 30
_WEEKDAY_KEYS = {fold(name)[:3]: number for number, name in enumerate(WEEKDAYS)}
_FILE_TIME = re.compile(r"(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)[-_. T]?(\d\d)[-_.:h]?(\d\d)[-_.:m]?(\d\d)")
# "5 h", "32 min", "1 d", and spelled out: "5 horas", "32 minutos", "5hrs", "1 día" (the audit of 7 Oct 2026).
_AGE = re.compile(r"(\d+)\s*(minutos?|mins?|m|horas?|hrs?|h|d[ií]as?|d)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Screenshot:
    """One uploaded screenshot, with what the browser said about its file before shrinking it."""

    image: bytes  # JPEG, 1080 px wide, the phone's status bar already cut off (admin-web/public/app.js)
    name: str = ""
    modified: int | None = None  # the file's date (File.lastModified, ms): often when it was shared, on Android
    uploaded: int | None = None  # when the Worker stored it (ms)


def story_id(images: Sequence[bytes]) -> str:
    """ "story-<16 hex>", the same for the same screenshots in any order."""
    digests = sorted(hashlib.sha256(image).hexdigest() for image in images)
    return STORY_PREFIX + hashlib.sha256("".join(digests).encode()).hexdigest()[:16]


def is_story_id(text: str) -> bool:
    return bool(_STORY_ID.fullmatch(text))


# ---------- the same story, another screenshot ----------


def image_hash(image: bytes) -> str:
    """A 64-bit difference hash (dHash) of the screenshot's middle, as 16 hex digits. The top and bottom are left
    out: Instagram's header (with the story's age) and the reply bar change between two screenshots of a story."""
    picture = Image.open(io.BytesIO(image)).convert("L")
    width, height = picture.size
    middle = picture.crop((0, round(height * FIXED_CROP), width, round(height * (1 - FIXED_CROP))))
    pixels = middle.resize((9, 8), Image.Resampling.LANCZOS).tobytes()  # one byte per pixel (grayscale)
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return f"{bits:016x}"


def hash_distance(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def same_story(hashes: Sequence[str], others: Sequence[str]) -> bool:
    """Whether a screenshot of one is a screenshot of the other (any pair HASH_DISTANCE or closer)."""
    return any(hash_distance(a, b) <= HASH_DISTANCE for a in hashes for b in others)


# ---------- when ----------


def taken_at(shot: Screenshot, now: datetime) -> tuple[datetime, str]:
    """When the screenshot was taken (Bogotá time) and how that's known, in Spanish: its file name (Android
    names them by the time, in the phone's time zone), else the file's date, else when it was uploaded, else now.
    A time in the future or older than SCREENSHOT_MAX_AGE_DAYS is ignored."""
    oldest, latest = now - timedelta(days=SCREENSHOT_MAX_AGE_DAYS), now + timedelta(minutes=10)
    if match := _FILE_TIME.search(shot.name):
        year, month, day, hour, minute, second = (int(part) for part in match.groups())
        try:
            moment: datetime | None = datetime(year, month, day, hour, minute, second, tzinfo=config.BOGOTA_TZ)
        except ValueError:
            moment = None
        if moment and oldest <= moment <= latest:
            return moment, "del nombre del archivo"
    for milliseconds, source in ((shot.modified, "de la fecha del archivo"), (shot.uploaded, "de cuando se subió")):
        if milliseconds:
            moment = datetime.fromtimestamp(milliseconds / 1000, config.BOGOTA_TZ)
            if oldest <= moment <= latest:
                return moment, source
    return now, "de ahora: la captura no dice cuándo se tomó"


def story_age(text: str | None) -> timedelta | None:
    """ "5 h", "32 min", "1 d" (next to the account's name) → how long ago the story was posted; None if unread or
    over a day (stories last 24 hours)."""
    match = _AGE.search(text or "")
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()[:1]
    age = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount)}.get(unit, timedelta(days=amount))
    return age if age <= timedelta(days=1) else None


# ---------- the event's date, from what's printed ----------


def weekday_number(name: str | None) -> int | None:
    """ "sábado", "SAB", "Sáb." → 5 (Monday is 0); None for anything else."""
    return _WEEKDAY_KEYS.get(fold(name)[:3]) if name and len(fold(name)) >= 3 else None


@dataclass
class ResolvedDate:
    start: date | None  # the event's day (its first, over several days)
    end: date | None = None  # its last day, over several consecutive days
    notes: list[str] = field(default_factory=list)  # Spanish, for the answer and the event's doubts
    year_inferred: bool = False
    weekday_mismatch: bool = False
    weekly: bool = False
    far_ahead: bool = False
    # A workshop series: each session's date, with the session as printed (its times); start and end are the first
    # and the last.
    sessions: list[tuple[date, StorySession]] = field(default_factory=list)


def _valid(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _first(*options: list[date]) -> date | None:
    """The first date of the first list that has one."""
    return next((dates[0] for dates in options if dates), None)


def _next_with_day(day: int, after: date, weekday: int | None) -> date | None:
    """The next date with this day of the month on or after `after` (within a year), the weekday's first."""
    candidates = [
        found
        for months in range(13)
        if (found := _valid(after.year + (after.month - 1 + months) // 12, (after.month - 1 + months) % 12 + 1, day))
        and found >= after
    ]
    matching = [found for found in candidates if weekday is not None and found.weekday() == weekday]
    return _first(matching, candidates)


def resolve_date(event: StoryEvent, taken: date, today: date) -> ResolvedDate:
    """The event's day from what the story prints, relative to the day the screenshot was taken:
    - "hoy" / "mañana": that day or the next;
    - day and month: the next such date on or after the screenshot's day, or up to RECENT_PAST_DAYS before it (an
      event that just passed stays in the past, and isn't published, instead of becoming next year's), the printed
      weekday settling the year (a printed year is used as it is);
    - a day alone ("sábado 12"): the next 12th (or one up to RECENT_PAST_DAYS before), the weekday settling the
      month;
    - a weekday alone ("este sábado"): the next one; a weekly night ("todos los viernes"): the next one from today.
    A workshop series (two or more sessions printed) is worked out by resolve_sessions.
    Flags a weekday that doesn't match the date, an inferred year, and a date more than FAR_AHEAD_DAYS ahead."""
    if len(event.sessions or []) >= config.MIN_SERIES_SESSIONS and (series := resolve_sessions(event, taken)):
        return series
    weekday = weekday_number(event.weekday)
    result = ResolvedDate(start=None, weekly=event.weekly)
    if event.relative_day == "hoy":
        result.start = taken
    elif event.relative_day == "mañana":
        result.start = taken + timedelta(days=1)
    elif event.day and event.month:
        years = [event.year] if event.year else [taken.year, taken.year + 1]
        result.year_inferred = not event.year
        dates = [found for year in years if (found := _valid(year, event.month, event.day))]
        upcoming = [found for found in dates if found >= taken - timedelta(days=RECENT_PAST_DAYS)]
        matching = [found for found in upcoming if weekday is not None and found.weekday() == weekday]
        result.start = _first(matching, upcoming, dates[-1:])
    elif event.day:
        result.start = _next_with_day(event.day, taken - timedelta(days=RECENT_PAST_DAYS), weekday)
        if result.start:
            result.notes.append("mes deducido")
    elif weekday is not None:
        start = max(taken, today) if event.weekly else taken
        result.start = start + timedelta(days=(weekday - start.weekday()) % 7)
        result.notes.append("fecha deducida del día de la semana")
    if result.start is not None:
        _check_start(result, result.start, event, weekday, taken)
    return result


def _check_start(result: ResolvedDate, start: date, event: StoryEvent, weekday: int | None, taken: date) -> None:
    """With the event's first day found: its last day, and the notes and flags on it (a printed weekday that
    doesn't match, an inferred year, a weekly night, a date far ahead)."""
    if weekday is not None and start.weekday() != weekday:
        result.weekday_mismatch = True
        result.notes.append(f"dice {event.weekday}, pero esa fecha es {WEEKDAYS[start.weekday()]}")
    if result.year_inferred:
        result.notes.append("año deducido")
    if event.weekly:
        result.notes.append("semanal: publiqué la próxima fecha")
    result.end = _end_date(event, start)
    if (start - taken).days > FAR_AHEAD_DAYS:
        result.far_ahead = True
        result.notes.append(f"más de {FAR_AHEAD_DAYS} días adelante: revisar")


def _series_from(first_year: int, printed: list[tuple[int, int]]) -> list[date] | None:
    """The sessions' dates when the first one is in `first_year`: each the next (month, day) after the one
    before (the year turns when the months do: "29 dic, 5 ene"). None if a day doesn't exist."""
    days: list[date] = []
    for month, day in printed:
        years = [first_year] if not days else [days[-1].year, days[-1].year + 1]
        found = next(
            (found for year in years if (found := _valid(year, month, day)) and (not days or found > days[-1])), None
        )
        if found is None:
            return None
        days.append(found)
    return days


def resolve_sessions(event: StoryEvent, taken: date) -> ResolvedDate | None:
    """A workshop series' sessions from what the story prints, relative to the day the screenshot was taken: the
    year (unless printed) that makes it the earliest series not over yet (a story can be shared after its first
    sessions), preferring one whose sessions fall on the printed weekday ("domingos"). A session without its month
    takes the one before's, or the next month when its day is smaller ("29 nov, 6" → 6 dic). None when fewer than
    two sessions have a date."""
    printed: list[tuple[int, int]] = []
    sessions: list[StorySession] = []
    notes: list[str] = []
    for session in event.sessions or []:
        month = session.month or (printed[-1][0] if printed else event.month)
        if month is None:
            month = taken.month
            notes.append("mes deducido")
        elif not session.month and printed and session.day <= printed[-1][1]:
            month = month % 12 + 1  # "29 nov, 6": the next month
        if not 1 <= month <= 12 or (printed and (month, session.day) == printed[-1]):
            continue  # no such month, or the same session twice
        printed.append((month, session.day))
        sessions.append(session)
    if len(printed) < config.MIN_SERIES_SESSIONS:
        return None
    years = [event.year] if event.year else [taken.year - 1, taken.year, taken.year + 1]
    options = [days for year in years if (days := _series_from(year, printed))]
    if not options:
        return None
    weekday = weekday_number(event.weekday)
    upcoming = [days for days in options if days[-1] >= taken]
    matching = [days for days in upcoming if weekday is not None and all(day.weekday() == weekday for day in days)]
    days = (matching or upcoming or options[-1:])[0]
    result = ResolvedDate(start=days[0], end=days[-1], sessions=list(zip(days, sessions, strict=True)))
    result.notes = list(dict.fromkeys(notes))
    if not event.year:
        result.year_inferred = True
        result.notes.append("año deducido")
    if weekday is not None and any(day.weekday() != weekday for day in days):
        result.weekday_mismatch = True
        wrong = next(day for day in days if day.weekday() != weekday)
        result.notes.append(f"dice {event.weekday}, pero el {wrong.day} es {WEEKDAYS[wrong.weekday()]}")
    if (days[0] - taken).days > FAR_AHEAD_DAYS:
        result.far_ahead = True
        result.notes.append(f"más de {FAR_AHEAD_DAYS} días adelante: revisar")
    return result


def _end_date(event: StoryEvent, start: date) -> date | None:
    """The last day of an event over several consecutive days, after `start` and at most MAX_EVENT_DAYS in all."""
    if not event.end_day:
        return None
    month = event.end_month or start.month
    end = _valid(start.year, month, event.end_day)
    if end and end < start and event.end_month is None:  # "30 oct - 2": the next month
        end = _valid(start.year + start.month // 12, start.month % 12 + 1, event.end_day)
    elif end and end < start:
        end = _valid(start.year + 1, month, event.end_day)
    if end is None or not 1 < (end - start).days + 1 <= config.MAX_EVENT_DAYS:
        return None
    return end


# ---------- the flyer: a crop of the screenshot ----------

Box = tuple[int, int, int, int]  # left, top, right, bottom, in pixels


def checked_box(content_box: Sequence[int] | None, width: int, height: int) -> Box | None:
    """Gemini's box ([ymin, xmin, ymax, xmax], 0-1000) in pixels with PADDING around it, or None when it can't be
    right: out of range, smaller than MIN_BOX_AREA of the screenshot, or not shaped like a flyer."""
    if not content_box or len(content_box) != 4:
        return None
    top, left, bottom, right = content_box
    if not (0 <= top < bottom <= 1000 and 0 <= left < right <= 1000):
        return None
    share_x, share_y = (right - left) / 1000, (bottom - top) / 1000
    if share_x * share_y < MIN_BOX_AREA:
        return None
    if not BOX_ASPECT[0] <= (share_x * width) / (share_y * height) <= BOX_ASPECT[1]:
        return None
    pad_x, pad_y = PADDING * width, PADDING * height
    return (
        max(0, round(left / 1000 * width - pad_x)),
        max(0, round(top / 1000 * height - pad_y)),
        min(width, round(right / 1000 * width + pad_x)),
        min(height, round(bottom / 1000 * height + pad_y)),
    )


def fixed_box(width: int, height: int) -> Box:
    """Without a usable box: FIXED_CROP off the top and the bottom."""
    return (0, round(height * FIXED_CROP), width, round(height * (1 - FIXED_CROP)))


@dataclass(frozen=True)
class Crop:
    image: bytes  # JPEG
    from_gemini: bool  # Gemini's box (checked); False: the fixed crop
    area: float  # share of the screenshot


def crop(image: bytes, content_box: Sequence[int] | None) -> Crop:
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    width, height = picture.size
    box = checked_box(content_box, width, height)
    chosen = box or fixed_box(width, height)
    buffer = io.BytesIO()
    picture.crop(chosen).save(buffer, "JPEG", quality=92)
    area = (chosen[2] - chosen[0]) * (chosen[3] - chosen[1]) / (width * height)
    return Crop(buffer.getvalue(), box is not None, area)


# ---------- the account ----------


def read_handle(text: str | None) -> tuple[str | None, bool]:
    """A username as read in the image ("@salsa.club", "salsa_cl…") → (the valid username or None, cut off?)."""
    cleaned = (text or "").strip().lstrip("@").strip()
    cut = cleaned.endswith(("…", "..."))
    cleaned = cleaned.rstrip("…").rstrip(".").strip()
    return (links.account_name(cleaned) if cleaned else None), cut


def known_account(name: str, cut: bool, known: Iterable[str]) -> str | None:
    """A known account this name stands for: the only one it starts, when it was cut off with "…"; otherwise a
    very close spelling (a letter misread)."""
    accounts = sorted({account.lower() for account in known})
    if cut:
        starting = [account for account in accounts if account.startswith(name)]
        return starting[0] if len(starting) == 1 else None
    close = difflib.get_close_matches(name, accounts, n=1, cutoff=0.88)
    return close[0] if close else None
