"""Text helpers shared by matching, normalization, ids, discovery and the admin tools' answers."""

import unicodedata
from datetime import date

_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def fold(text: str | None) -> str:
    """Lowercase, no accents, single spaces: 'Salsa  Caleña' → 'salsa calena'. For comparing, not showing."""
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def dates_label(start: str | None, end: str | None = None) -> str:
    """An event's day for the admin tools' answers: its date as stored ('2026-11-13'), or the range of an event
    over several days: '13–15 nov 2026', '31 oct – 2 nov 2026', '30 dic 2026 – 1 ene 2027'."""
    if not start or not end or end <= start:
        return start or "?"
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.year != last.year:
        return f"{first.day} {_MONTHS[first.month - 1]} {first.year} – {last.day} {_MONTHS[last.month - 1]} {last.year}"
    if first.month != last.month:
        return f"{first.day} {_MONTHS[first.month - 1]} – {last.day} {_MONTHS[last.month - 1]} {last.year}"
    return f"{first.day}–{last.day} {_MONTHS[last.month - 1]} {last.year}"
