"""Clean what Gemini returns before it is stored: the frontend relies on these formats."""

import re
from collections.abc import Sequence
from datetime import date, time

from . import config
from .models import STYLES, ExtractedEvent
from .text import fold

_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


# Accent-insensitive names and synonyms → the style list in models.py.
_STYLE_SYNONYMS = {
    **{fold(style): style for style in STYLES},
    "mambo": "salsa en línea",
    "on1": "salsa en línea",
    "on2": "salsa en línea",
    "salsa on1": "salsa en línea",
    "salsa on2": "salsa en línea",
    "salsa linea": "salsa en línea",
    "salsa new york": "salsa en línea",
    "salsa ny": "salsa en línea",
    "salsa los angeles": "salsa en línea",
    "salsa la": "salsa en línea",
    "casino": "salsa cubana",
    "salsa casino": "salsa cubana",
    "rueda": "salsa cubana",
    "rueda de casino": "salsa cubana",
    "timba": "salsa cubana",
    "calena": "salsa caleña",
    "salsa estilo caleno": "salsa caleña",
    "estilo caleno": "salsa caleña",
    "salsa cali": "salsa caleña",
    "sensual": "bachata sensual",
    "bachata tradicional": "bachata dominicana",
    "bachata moderna": "bachata",
    "bachata fusion": "bachata",
    "chachacha": "cha cha chá",
    "cha cha cha": "cha cha chá",
    "son cubano": "son",
    "brazilian zouk": "zouk",
    "zouk brasileno": "zouk",
    "reggaeton": "urbano",
    "regueton": "urbano",
    "hip hop": "urbano",
    "street": "urbano",
    "rumba": "afro",
    "rumba cubana": "afro",
    "afrobeat": "afro",
    "afrohouse": "afro",
    "west coast swing": "swing",
    "lindy hop": "swing",
}


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


def normalize_style(style: str) -> str | None:
    """A style from the list for any spelling or synonym; 'otro' for unknown ones, None for blanks."""
    key = fold(style)
    if not key:
        return None
    return _STYLE_SYNONYMS.get(key, "otro")


def normalize_styles(styles: Sequence[str]) -> list[str]:
    """Styles from the list, without duplicates, in their original order.

    The generic 'salsa' / 'bachata' is dropped when a specific variant of it is present.
    """
    seen: dict[str, None] = {}
    for style in styles:
        normalized = normalize_style(style)
        if normalized:
            seen.setdefault(normalized, None)
    result = list(seen)
    for family in ("salsa", "bachata"):
        if family in result and any(style.startswith(f"{family} ") for style in result):
            result.remove(family)
    return result


_WHATSAPP = re.compile(r"\b(whats\s*app|wpp|wsp|wa)\b", re.IGNORECASE)
_HANDLE = re.compile(r"^@[A-Za-z0-9._]+$")
_WEBSITE = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", re.IGNORECASE)


def normalize_contact(contact: str | None) -> str | None:
    """A contact the site can link: "@academia", a website, a phone number (7+ digits), or "WhatsApp " and a
    number when it's marked as WhatsApp. Anything else (a word read off the flyer, e.g. "SOCIAL") is dropped."""
    text = " ".join((contact or "").split())
    if not text:
        return None
    if _HANDLE.match(text) or _WEBSITE.match(text):
        return text
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return None
    number = re.sub(r"[^\d+ ()-]", "", _WHATSAPP.sub("", text)).strip()
    return f"WhatsApp {number}" if _WHATSAPP.search(text) else number


def parse_end_date(start: str | None, end: str | None, doubts: list[str]) -> str | None:
    """The last day of an event over several consecutive days, after its first day (`start`, already parsed) and
    at most MAX_EVENT_DAYS in all; otherwise None (a one-day event). A range that can't be right is noted as a
    doubt, so the event is reviewed (health.events_to_review)."""
    end = parse_iso_date(end)
    if not start or not end or end == start:
        return None
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if days < 1:
        doubts.append("fecha final anterior a la inicial")
        return None
    if days > config.MAX_EVENT_DAYS:
        doubts.append("dura más de una semana: revisar fechas")
        return None
    return end


def normalize_event(event: ExtractedEvent) -> ExtractedEvent:
    """A copy with valid dates and times (invalid ones become None), clean styles and no negative prices."""
    doubts = list(event.doubts)
    start_time, end_time = parse_time(event.start_time), parse_time(event.end_time)
    if event.start_time and not start_time:
        doubts.append(f"Hora de inicio no reconocida: {event.start_time}")
    start = parse_iso_date(event.date)
    return event.model_copy(
        update={
            "title": " ".join(event.title.split()),
            "date": start,
            "end_date": parse_end_date(start, event.end_date, doubts),
            "start_time": start_time,
            "end_time": end_time,
            "styles": normalize_styles(event.styles),
            # The site's check-data.mjs requires a label: a price without one isn't shown.
            "prices": [price for price in event.prices if price.amount_cop >= 0 and price.label.strip()],
            "contact": normalize_contact(event.contact),
            "doubts": doubts,
        }
    )
