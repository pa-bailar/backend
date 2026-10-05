"""Clean what Gemini returns before it is stored: the frontend relies on these formats."""

import re
from collections.abc import Sequence
from datetime import date, time
from itertools import pairwise

from . import config
from .models import STYLES, ExtractedEvent, Price, Session
from .patterns import HANDLE
from .text import WEEKDAYS, fold

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


# Words that name a style in a caption, for an event that came back without styles (styles_in_text). Not "son"
# ("they are"), "salsa la", "otro" nor the bare variants' short forms: too common as plain words.
_TEXT_STYLE_WORDS = sorted(
    (key for key in _STYLE_SYNONYMS if key not in {"son", "salsa la", "otro", "sensual", "rueda", "la"}),
    key=len,
    reverse=True,
)
_TEXT_STYLE = re.compile(r"\b(" + "|".join(re.escape(key) for key in _TEXT_STYLE_WORDS) + r")\b")


def styles_in_text(text: str | None) -> list[str]:
    """The styles a text names ("Noche de SALSA y bachata" → salsa, bachata), longest names first, so "salsa en
    linea" wins over "salsa". For an event that came back without styles: free, no request."""
    found = [_STYLE_SYNONYMS[m.group(1)] for m in _TEXT_STYLE.finditer(fold(text))]
    return normalize_styles(found)


# A post announcing several events, read only by a lighter model (Flash-Lite as the final reader, or a provisional
# reading): it mixes up each event's times and prices (one post with workshops at 15:00, 16:00 and 17:00 came back all
# at 15:00, Oct 2026). Listed for review (health.review_reasons).
MULTI_DOUBT = "varios eventos en una publicación, leída por un modelo ligero: confirma horas y precios"


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
_HANDLE = re.compile(rf"^@{HANDLE}$")  # longer than Instagram allows: not an account (dropped, unless it's digits)
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


# Gemini couldn't tell whether the event is in Bogotá (ExtractedEvent.in_bogota "unknown"; "no" isn't published).
CITY_DOUBT = "ciudad sin confirmar: ¿es en Bogotá?"

# Places a caption can name when an event is elsewhere (folded: text.fold). Checked in code after Gemini, for free:
# "Nos vemos en expofitness Medellin 2027" came out as a Bogotá event (La Revuelta, read by Flash-Lite, Oct 2026).
_OTHER_PLACES = re.compile(
    r"\b(medellin|cali|barranquilla|cartagena|bucaramanga|manizales|armenia|villavicencio|ibague|tunja|"
    r"santa marta|cucuta|neiva|popayan|monteria|sincelejo|valledupar|riohacha|quibdo|envigado|rionegro|"
    r"mexico|cdmx|miami|madrid|barcelona|lima|quito|guayaquil|panama|caracas|santiago de chile|buenos aires)\b"
)
# "estilo Cali", "desde Medellín", "style Cali", "Cali Pachanguero" (a song): where a style, a guest or a song comes
# from, not where the event is. (Pasto and Pereira are left out: a word and a surname as often as cities; New York,
# Puerto Rico and La Habana name salsa styles and artists' origins far more often than an event's place.)
_NOT_A_PLACE = re.compile(r"\b(estilo|style|desde|llega de|viene de|sabor)\s+$")
_SONGS = re.compile(r"\bcali pachanguero\b")


def doubtful_city(event: ExtractedEvent, caption: str | None) -> ExtractedEvent:
    """An event Gemini placed in Bogotá ("yes") with no address of its own, from a caption that names another city
    and never Bogotá, becomes "unknown": published with CITY_DOUBT and listed for review, not dropped (a caption
    also names where a guest artist comes from: "llega desde Medellín")."""
    text = _SONGS.sub("", fold(caption))
    if event.in_bogota != "yes" or event.address or "bogota" in text:
        return event
    named = [
        m for m in _OTHER_PLACES.finditer(text) if not _NOT_A_PLACE.search(text[max(0, m.start() - 12) : m.start()])
    ]
    return event.model_copy(update={"in_bogota": "unknown"}) if named else event


COURSE_DOUBT = f"más de {config.MAX_SERIES_SESSIONS} sesiones o más de 4 meses: es un curso"


def parse_sessions(
    sessions: Sequence[Session] | None, start_time: str | None, end_time: str | None, doubts: list[str]
) -> list[Session] | None:
    """A workshop series' sessions as stored: real dates, in order, without repeats, each with valid times (the
    event's own when a session gives none: "domingos 8, 22 y 29 de 2 a 5 p. m."). None when fewer than two are
    left (not a series). The caller checks the count and the span (fit_sessions)."""
    by_date: dict[str, Session] = {}
    for session in sessions or []:
        day = parse_iso_date(session.date)
        if day and day not in by_date:
            session_start, session_end = parse_time(session.start_time), parse_time(session.end_time)
            if session.start_time and not session_start:
                doubts.append(f"Hora de inicio no reconocida: {session.start_time}")
            by_date[day] = Session(
                date=day,
                start_time=session_start or (None if session.start_time else start_time),
                end_time=session_end or (None if session.end_time else end_time),
            )
    ordered = [by_date[day] for day in sorted(by_date)]
    return ordered if len(ordered) >= config.MIN_SERIES_SESSIONS else None


def _consecutive(sessions: list[Session]) -> bool:
    days = [date.fromisoformat(session.date) for session in sessions]
    return all((later - earlier).days == 1 for earlier, later in pairwise(days))


def fit_sessions(update: dict[str, object], sessions: list[Session] | None, doubts: list[str]) -> None:
    """Make a workshop series' event follow its sessions (`update` holds the event's parsed fields): `date` and
    `end_date` the first and last session's, the times and weekday the first session's. Sessions on consecutive
    days are an event over several days instead (date and end_date, no sessions), and too many sessions or too long
    a span (MAX_SERIES_SESSIONS, MAX_SERIES_DAYS) are a course: recurring, not published."""
    update["sessions"] = None
    if not sessions:
        return
    first, last = date.fromisoformat(sessions[0].date), date.fromisoformat(sessions[-1].date)
    if _consecutive(sessions) and len(sessions) <= config.MAX_EVENT_DAYS:
        update |= {"date": sessions[0].date, "end_date": sessions[-1].date}
        return
    if len(sessions) > config.MAX_SERIES_SESSIONS or (last - first).days + 1 > config.MAX_SERIES_DAYS:
        doubts.append(COURSE_DOUBT)
        update["is_recurring"] = True
        return
    update |= {
        "sessions": sessions,
        "date": sessions[0].date,
        "end_date": sessions[-1].date,
        "start_time": sessions[0].start_time,
        "end_time": sessions[0].end_time,
        "weekday": WEEKDAYS[first.weekday()],
    }


# A currency other than Colombian pesos (folded text: lowercase, no accents). "$" alone is pesos too: not here.
_OTHER_CURRENCY = re.compile(
    r"[€£]|\b(?:us|u|mx)\$"
    r"|\b(?:usd|mxn|eur|euros?|gbp|dolar(?:es)?|dollars?|clp|ars|brl|reales|libras)\b"
    r"|\bpesos? (?:mexicanos?|argentinos?|chilenos?|dominicanos?|cubanos?|uruguayos?)\b"
)
_FREE = re.compile(r"\b(?:gratis|gratuit[oa]s?|libre|free|sin costo)\b")


def _in_other_currency(price: Price) -> bool:
    """A price of 0 that is really an amount in another currency ("VIP", "1,000.00 MXN"), not free: the site shows
    0 as free. A label or condition that reads as free ("Entrada libre") keeps it."""
    text = fold(f"{price.label} {price.condition or ''}")
    return any(char.isdigit() for char in text) and bool(_OTHER_CURRENCY.search(text)) and not _FREE.search(text)


def clean_prices(prices: Sequence[Price], doubts: list[str]) -> list[Price]:
    """The prices the site can show: a label (its check-data.mjs requires one), no negative amounts, and no 0 that
    is an amount in another currency (noted as a doubt instead: "Precio en otra moneda: VIP (1,000.00 MXN)")."""
    kept = []
    for price in prices:
        if price.amount_cop < 0 or not price.label.strip():
            continue
        if price.amount_cop == 0 and _in_other_currency(price):
            condition = " ".join((price.condition or "").split())
            written = " ".join(price.label.split()) + (f" ({condition})" if condition else "")
            doubts.append(f"Precio en otra moneda: {written}")
            continue
        kept.append(price)
    return kept


def normalize_event(event: ExtractedEvent) -> ExtractedEvent:
    """A copy with valid dates and times (invalid ones become None), clean styles and prices the site can show
    (clean_prices). A workshop series' dates and times follow its sessions (fit_sessions)."""
    doubts = list(event.doubts)
    start_time, end_time = parse_time(event.start_time), parse_time(event.end_time)
    if event.start_time and not start_time:
        doubts.append(f"Hora de inicio no reconocida: {event.start_time}")
    start = parse_iso_date(event.date)
    sessions = parse_sessions(event.sessions, start_time, end_time, doubts)
    days: dict[str, object] = {
        "date": start,
        "end_date": None if sessions else parse_end_date(start, event.end_date, doubts),
        "start_time": start_time,
        "end_time": end_time,
    }
    fit_sessions(days, sessions, doubts)
    prices = clean_prices(event.prices, doubts)
    if event.in_bogota == "unknown" and CITY_DOUBT not in doubts:
        doubts.append(CITY_DOUBT)  # published, and listed for review (health.review_reasons)
    return event.model_copy(
        update={
            "title": " ".join(event.title.split()),
            **days,
            "styles": normalize_styles(event.styles),
            "prices": prices,
            "contact": normalize_contact(event.contact),
            "doubts": doubts,
        }
    )
