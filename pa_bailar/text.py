"""Text helpers shared by matching, normalization, ids, discovery and the admin tools' answers."""

import unicodedata
from collections.abc import Sequence
from datetime import date, datetime, time

MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")  # short, Spanish
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")  # date.weekday() order


def fold(text: str | None) -> str:
    """Lowercase, no accents, single spaces: 'Salsa  Caleña' → 'salsa calena'. For comparing, not showing."""
    # NFKD first: Instagram's "fancy font" capitals (𝐒𝐀𝐋𝐒𝐀, 𝗦𝗔𝗟𝗦𝗔) have no lowercase of their own and only become
    # plain letters after it.
    decomposed = unicodedata.normalize("NFKD", text or "").casefold()
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def dates_label(start: str | None, end: str | None = None) -> str:
    """An event's day for the admin tools' answers: its date as stored ('2026-11-13'), or the range of an event
    over several days: '13–15 nov 2026', '31 oct – 2 nov 2026', '30 dic 2026 – 1 ene 2027'."""
    if not start or not end or end <= start:
        return start or "?"
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.year != last.year:
        return f"{first.day} {MONTHS[first.month - 1]} {first.year} – {last.day} {MONTHS[last.month - 1]} {last.year}"
    if first.month != last.month:
        return f"{first.day} {MONTHS[first.month - 1]} – {last.day} {MONTHS[last.month - 1]} {last.year}"
    return f"{first.day}–{last.day} {MONTHS[last.month - 1]} {last.year}"


def sessions_label(dates: Sequence[str]) -> str:
    """A workshop series' sessions for the admin tools' answers: '4 sesiones: 8, 22, 29 nov y 6 dic' (the year
    after each month only when they span two years: '2 sesiones: 29 dic 2026 y 5 ene 2027')."""
    days = [date.fromisoformat(day) for day in dates]
    two_years = len({day.year for day in days}) > 1
    parts = []
    for index, day in enumerate(days):
        following = days[index + 1] if index + 1 < len(days) else None
        part = str(day.day)
        if following is None or (following.year, following.month) != (day.year, day.month):  # its month's last
            part += f" {MONTHS[day.month - 1]}" + (f" {day.year}" if two_years else "")
        parts.append(part)
    listed = f"{', '.join(parts[:-1])} y {parts[-1]}" if len(parts) > 1 else "".join(parts)
    return f"{len(days)} sesiones: {listed}"


def event_dates_label(start: str | None, end: str | None = None, sessions: Sequence[str] = ()) -> str:
    """An event's days for the admin tools' answers: a workshop series' sessions (sessions_label), else its date or
    range (dates_label)."""
    return sessions_label(sessions) if len(sessions) > 1 else dates_label(start, end)


def day_label(day: str) -> str:
    """One day, with its weekday, for the admin tools' answers: '2026-10-10' → 'sábado 10 oct 2026'."""
    moment = date.fromisoformat(day)
    return f"{WEEKDAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def parse_hhmm(text: str) -> time:
    """ "21:00" → 21:00 (the times in config and stored events). Raises ValueError for anything else."""
    hour, minute = map(int, text.split(":"))
    return time(hour, minute)


def clock(moment: datetime | time) -> str:
    """The time of day as the admin tools' answers say it: '9:00 p. m.', '12:30 a. m.'."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'a. m.' if moment.hour < 12 else 'p. m.'}"
