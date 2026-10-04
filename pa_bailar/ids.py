"""Readable, stable event ids. They are the event's URL on the website (/evento/<id>/), so:

- they read well when shared: "salsa-freestyle-con-renato-palacios-3-oct";
- they are set once, when the event is first stored, and never recomputed: a later re-extraction that
  rewords the title keeps the id (see Sweep._event_id), so shared links keep working.
"""

import re

from .text import MONTHS, fold

MAX_TITLE_LENGTH = 50  # characters of the title part, cut at a word boundary


def slugify(text: str) -> str:
    """'¡Social de Halloween!' → 'social-de-halloween': lowercase ASCII words joined by hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def _shorten(slug: str) -> str:
    if len(slug) <= MAX_TITLE_LENGTH:
        return slug
    cut = slug[: MAX_TITLE_LENGTH + 1].rsplit("-", 1)[0]
    return cut or slug[:MAX_TITLE_LENGTH]


def new_event_id(title: str, date: str, taken: set[str]) -> str:
    """'<title>-<day>-<month>', e.g. 'social-de-halloween-24-oct' for 2026-10-24.

    A number is added when the id is already used ('…-24-oct-2'), e.g. two academies with an event of
    the same name on the same day, or the same name a year later.
    """
    _, month, day = (int(part) for part in date.split("-"))
    base = "-".join(part for part in (_shorten(slugify(title)), str(day), MONTHS[month - 1]) if part)
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate
