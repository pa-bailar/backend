"""Clean what Gemini returns before it is stored: the frontend relies on these formats."""

import re
from datetime import date, time

from .models import ExtractedEvent

_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_iso_date(value: str | None) -> str | None:
    """'YYYY-MM-DD' for a real calendar date, otherwise None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def parse_time(value: str | None) -> str | None:
    """'HH:MM' (24-hour) for a valid time like '9:05' or '21:00', otherwise None."""
    match = _TIME_PATTERN.match((value or "").strip())
    if not match:
        return None
    hours, minutes = int(match[1]), int(match[2])
    try:
        return time(hours, minutes).strftime("%H:%M")
    except ValueError:
        return None


def normalize_styles(styles: list[str]) -> list[str]:
    """Lowercase, trimmed, without duplicates, in their original order."""
    seen: dict[str, None] = {}
    for style in styles:
        cleaned = " ".join(style.casefold().split())
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def normalize_event(event: ExtractedEvent) -> ExtractedEvent:
    """A copy with valid dates and times (invalid ones become None), clean styles and no negative prices."""
    doubts = list(event.doubts)
    start_time, end_time = parse_time(event.start_time), parse_time(event.end_time)
    if event.start_time and not start_time:
        doubts.append(f"Hora de inicio no reconocida: {event.start_time}")
    return event.model_copy(
        update={
            "title": " ".join(event.title.split()),
            "date": parse_iso_date(event.date),
            "start_time": start_time,
            "end_time": end_time,
            "styles": normalize_styles(event.styles),
            "prices": [price for price in event.prices if price.amount_cop >= 0],
            "doubts": doubts,
        }
    )
