"""Clean what Gemini returns before it is stored: the frontend relies on these formats."""

import re
from collections.abc import Sequence
from datetime import date, time
from itertools import pairwise

from . import config
from .models import STYLES, EventType, ExtractedEvent, Price, Session
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
    "cubano": "salsa cubana",
    "estilo cubano": "salsa cubana",
    "salsa estilo cubano": "salsa cubana",
    "salsa on 1": "salsa en línea",
    "salsa on 2": "salsa en línea",
    # Salsa's other names (the owner, 5 Oct 2026): plain salsa.
    "pachanga": "salsa",
    "boogaloo": "salsa",
    "bugalu": "salsa",
    "salsa brava": "salsa",
    "salsa dura": "salsa",
    "salsa choke": "salsa",
    # The words around a style that a caption uses instead of its name (the owner, 7 Oct 2026: the Spanish synonyms
    # of every word the code relies on; the audit that day found these named no style): a salsa night's "salsoteca",
    # "Fania", "salsero"; "bachatero"; "perreo"; "milonga" is a tango social.
    "salsero": "salsa",
    "salsera": "salsa",
    "salseros": "salsa",
    "salseras": "salsa",
    "salsoteca": "salsa",
    "fania": "salsa",
    "calena": "salsa caleña",
    "salsa estilo caleno": "salsa caleña",
    "estilo caleno": "salsa caleña",
    "salsa cali": "salsa caleña",
    "salsa estilo cali": "salsa caleña",
    "estilo cali": "salsa caleña",
    "sensual": "bachata sensual",
    "bachata tradicional": "bachata dominicana",
    "bachata moderna": "bachata",
    "bachata fusion": "bachata",
    "bachatero": "bachata",
    "bachatera": "bachata",
    "bachateros": "bachata",
    "bachateras": "bachata",
    "bachazouk": "bachata",
    "chachacha": "cha cha chá",
    "cha cha cha": "cha cha chá",
    "son cubano": "son",
    "brazilian zouk": "zouk",
    "zouk brasileno": "zouk",
    "reggaeton": "urbano",
    "regueton": "urbano",
    "hip hop": "urbano",
    "perreo": "urbano",
    "dembow": "urbano",
    "street": "urbano",
    "rumba": "afro",
    "rumba cubana": "afro",
    "guaguanco": "afro",
    "afrobeat": "afro",
    "afrohouse": "afro",
    "afrobeats": "afro",
    "amapiano": "afro",
    "milonga": "tango",
    "milongas": "tango",
    "tanguero": "tango",
    "tanguera": "tango",
    "kiz": "kizomba",
    "urban kiz": "kizomba",
    "urbankiz": "kizomba",
    "semba": "kizomba",
    "tarraxinha": "kizomba",
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


# Words that name a style in a caption, for an event that came back without styles (styles_in_text): the synonyms
# above, but not the ones captions use as plain words or names, which gave wrong styles (Oct 2026 review): "son"
# ("they are"), "salsa la", "otro", "sensual", "rueda", "rumba" ("la mejor rumba salsera": a party), "street" and
# "urbano" ("street food", "transporte urbano"), "casino" ("Casino Royal"), "mambo" ("Mambo Cafe"), "calena" ("la
# caleña"), "swing" ("Swing Latino", a salsa company), "timba", "cubano" ("ron cubano") and "pachanga" ("¡qué
# pachanga!"). A model's own styles keep the whole map (normalize_style).
_NOT_IN_TEXT = {"son", "salsa la", "otro", "sensual", "rueda", "rumba", "street", "urbano", "casino", "mambo"}
_NOT_IN_TEXT |= {"calena", "swing", "timba", "cubano", "pachanga"}
# Phrases only a caption uses for a style (urban dance without the bare word "urbano").
_TEXT_ONLY_STYLES = {
    "baile urbano": "urbano",
    "bailes urbanos": "urbano",
    "danza urbana": "urbano",
    "danzas urbanas": "urbano",
}
# Word (folded) → the style it names. Also the base of a `solo:` account's caption filter (account_options).
TEXT_STYLE_WORDS = {key: style for key, style in _STYLE_SYNONYMS.items() if key not in _NOT_IN_TEXT} | _TEXT_ONLY_STYLES
_TEXT_STYLE = re.compile(
    r"\b(" + "|".join(re.escape(key) for key in sorted(TEXT_STYLE_WORDS, key=len, reverse=True)) + r")\b"
)


def styles_in_text(text: str | None) -> list[str]:
    """The styles a text names ("Noche de SALSA y bachata" → salsa, bachata), longest names first, so "salsa en
    linea" wins over "salsa". For an event that came back without styles: free, no request."""
    found = [TEXT_STYLE_WORDS[m.group(1)] for m in _TEXT_STYLE.finditer(fold(text))]
    return normalize_styles(found)


def style_family(style: str) -> str:
    """A style's family: "salsa" for salsa and its variants, "bachata" likewise, any other style itself."""
    return next((family for family in ("salsa", "bachata") if style.startswith(family)), style)


# Styles the safeguards filled in (from the text or the account, pipeline/base.py: _safeguarded), not read from the
# post: a later reading's own styles replace them (merging.merge_into), and they don't count as the account's usual.
GUESSED_STYLES_DOUBT = "estilos deducidos del texto o de la cuenta, no leídos en el post"


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


_WHATSAPP = re.compile(r"\b(whats\s*app?|wpp|wsp|wa|wasap|wassap|guasap)\b", re.IGNORECASE)
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
_FREE = re.compile(r"\b(?:gratis|gratuit[oa]s?|libre|free|sin costo|sin cover|no cover|cortesia)\b")


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


# A dancers' social, said in words: a bar's night that says so stays a social. Its other names too: a "milonga" (a
# tango social) and a "práctica" (the audit of 7 Oct 2026: both became parties). Not the word's other uses, common in
# captions: "redes sociales", "red social", a "... Social Club" or "Club Social" (a bar's own name), "eventos sociales"
# (a venue's rentals), "causa/obra/labor/proyecto social"...
_SOCIAL_WORD = re.compile(
    r"(?<!redes )(?<!red )(?<!club )(?<!eventos )(?<!causa )(?<!obra )(?<!labor )(?<!proyecto )(?<!impacto )"
    r"(?<!responsabilidad )\bsociale?s?\b(?! club)|\b(?:milongas?|practicas?)\b"
)


def party_at_a_bar(event_type: EventType, text: str) -> EventType:
    """A bar's night read as a "social" is a party ("Rumba"), unless its title or caption announces a social (the
    owner, 6 Oct 2026: a salsa bar's party isn't a dancers' social). A fixed rule, so it holds whatever model read the
    post; other types (a concert, a workshop) stay as read."""
    if event_type != "social" or _SOCIAL_WORD.search(fold(text)):
        return event_type
    return "party"
