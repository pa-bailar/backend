"""Rules that flag a reading for a second look, with no AI: the post's text (its caption and the flyer's OCR text,
ocr.py) says something its events don't. Flash-Lite's misses on the test set (gold/, 7 Oct 2026) were judgments, not
misreadings: a four-Saturday course and two bar nights dropped as "regular", three workshops merged into one, a start
time in the caption skipped, "11 OCT — 01 NOV" kept as one day. Each leaves a trace these rules see. A flag costs one
more request on a post; a missed error costs a wrong or missing event on the site.

Hand-written on purpose: no maintained Python library reads Spanish date ranges, lists and relative dates together
(dateparser has no ranges or "este sábado"; Recognizers-Text's Python port skips most Spanish cases; Duckling is a
Haskell server), research of 7 Oct 2026."""

import re
from contextlib import suppress
from datetime import date, timedelta
from typing import Any

from .text import fold

_MONTHS = {
    **{"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8},
    **{"septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12},
    **{"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sept": 9, "sep": 9},
    **{"set": 9, "oct": 10, "nov": 11, "dic": 12},
}
_WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"
_WEEKDAY = "(?:" + "|".join(_WEEKDAYS) + ")"
_DAY = r"(?<![\d#/])(?:3[01]|[12]\d|0?[1-9])(?!\d)"  # 1 to 31, not a piece of an address ("#3-84") or a number

# "11 de octubre", "9DEOCT" (OCR drops spaces), "octubre 11", "11/10". Matched line by line (_lines).
_DATE = re.compile(rf"{_DAY}[ \t]*(?:de[ \t]*)?{_MONTH}\b|\b{_MONTH}\.?[ \t]*{_DAY}|{_DAY}/(?:1[0-2]|0?[1-9])(?![\d/])")
# A range: "del 13 al 16 de noviembre", "11 OCT — 01 NOV", "19 al 21 de marzo", "20 y 21 noviembre" ("y" only
# between consecutive days: "17 y 24 de octubre" ends a list of dates, _LIST).
_RANGE = re.compile(
    rf"(?P<first>{_DAY})[ \t]*(?:de[ \t]*)?(?:{_MONTH}\.?)?[ \t]*(?P<joint>-|–|—|al|hasta|y)[ \t]*(?P<last>{_DAY})"
    rf"[ \t]*(?:de[ \t]*)?{_MONTH}\b"
)
# A list: "3, 10, 17 y 24 de octubre" (a series' dates, or several nights).
_LIST = re.compile(rf"{_DAY}(?:[ \t]*,[ \t]*{_DAY})+[ \t]*y[ \t]*{_DAY}[ \t]*(?:de[ \t]*)?{_MONTH}\b")
# A number that's an hour, not a day: "sábado 6PM", "viernes 8:30".
_AN_HOUR = r"(?=[ \t]*(?::|a\.?[ \t]*m\b|p\.?[ \t]*m\b|h\b|hrs?\b))"
# A weekday with its day: "sábado 10 de octubre", "jueves 08", "domingo 11".
_WEEKDAY_DAY = re.compile(
    rf"\b(?P<weekday>{_WEEKDAY})s?[ \t,]*(?!{_DAY}{_AN_HOUR})(?P<day>{_DAY})"
    rf"(?:[ \t]*(?:de[ \t]*)?(?P<month>{_MONTH})\b)?"
)
# A day relative to the post: "este sábado", "el próximo viernes", "este fin de semana"; not with a day after it
# ("este jueves, 22 de octubre" is that date: _WEEKDAY_DAY), though an hour may follow ("este sábado 6PM"). Not "esta
# noche": captions use it for the event's night whenever it is ("esta noche no vienes solo a bailar").
_RELATIVE = re.compile(
    rf"\b(?P<which>este|el proximo|proximo|el)[ \t]+(?P<weekday>{_WEEKDAY})\b(?![ \t,]*{_DAY}(?!{_AN_HOUR}))"
    r"|\b(?P<weekend>este (?:fin de semana|finde))\b"
)
# A line about a deadline, not an event: "Miércoles 30 · Fin segundo corte", "preventa hasta el viernes 9".
_DEADLINE = re.compile(r"\b(?:corte|cierre|preventa|inscripcion|inscripciones|hasta|plazo|ultimo dia)\b")

_SUFFIX = r"(?:a\.?[ \t]*m\b\.?|p\.?[ \t]*m\b\.?|m\b)"
# A clock time: "8:30 p.m.", "8:30P.M", "6pm", "9 AM", "12:00 M", "20:30", "20h30", "21h" (an "h" after an hour
# under 12 is a duration: "2 h", "clase de 1h").
_TIME = re.compile(
    rf"(?<![\d:/])(?P<hour>\d{{1,2}})(?::(?P<minutes>[0-5]\d))?[ \t]*(?P<suffix>{_SUFFIX})"
    r"|(?<![\d:/])(?P<hour24>\d{1,2})(?::|h)(?P<minutes24>[0-5]\d)(?!\d)"
    r"|(?<![\d:/])(?P<hourh>1\d|2[0-3])h\b"
)
# A span of time: "de 9 a 10 pm", "10pm. a 2:30 am", "9:00 AM A 12:00 M", "desde las 2 hasta las 10 pm": its start
# is a start time, its end isn't (the start takes the end's am/pm when it has none: "de 9 a 10 pm" starts at 21:00).
_SPAN = re.compile(
    rf"(?P<start>\d{{1,2}}(?::[0-5]\d)?)[ \t]*(?P<start_suffix>{_SUFFIX})?[ \t]*(?:a|-|–|hasta)[ \t]*(?:las[ \t]*)?"
    rf"(?P<end>\d{{1,2}}(?::[0-5]\d)?)[ \t]*(?P<end_suffix>{_SUFFIX})"
)
_UNTIL = re.compile(r"\bhasta[ \t]*(?:las?[ \t]*)?$")  # "hasta las 5 am": an end, not a start

DATES_WITHOUT_EVENT = "fechas sin evento"  # dates in the text, no event read (or only "recurring" ones)
TIME_NOT_READ = "hora sin leer"  # a time in the text, an event without one
RANGE_AS_ONE_DAY = "rango como un día"  # a range of dates in the text, every event a single day
TIMES_OVER_EVENTS = "más horas que eventos"  # three or more start times in the text, one event
LIST_NOT_READ = "lista de fechas sin leer"  # "3, 10, 17 y 24 de octubre", fewer dates read
DAY_WITHOUT_EVENT = "día sin evento"  # "sábado 10 de octubre" (from the post's day on), no event that day
RELATIVE_WITHOUT_EVENT = "día relativo sin evento"  # "este sábado", "esta noche"…, no event that day
BEFORE_POST = "antes de la publicación"  # an event over before the post went up: a date misread


def _lines(text: str) -> str:
    """Folded line by line, so a pattern never joins the end of one line to the next (an address and a date)."""
    return "\n".join(fold(line) for line in text.splitlines())


def _clock(hour: int, minutes: str | None, suffix: str | None) -> str | None:
    suffix = (suffix or "").replace(".", "").replace(" ", "").replace("\t", "")
    if suffix.startswith("p") and hour < 12:
        hour += 12
    elif suffix.startswith("a") and hour == 12:
        hour = 0
    return f"{hour:02d}:{minutes or '00'}" if hour <= 23 else None


def _time_of(match: re.Match[str]) -> str | None:
    if match.group("hour"):
        return _clock(int(match.group("hour")), match.group("minutes"), match.group("suffix"))
    if match.group("hour24"):
        return _clock(int(match.group("hour24")), match.group("minutes24"), None)
    return _clock(int(match.group("hourh")), None, None)


def _split(value: str) -> tuple[int, str | None]:
    hour, _, minutes = value.partition(":")
    return int(hour), minutes or None


def clock_times(text: str) -> tuple[set[str], set[str]]:
    """The text's start times and every time in it, as HH:MM (24 h): a span's end ("a 2:30 am", "hasta las 10 pm")
    is a time but not a start."""
    folded = _lines(text)
    every: set[str] = set()
    ends: set[str] = set()
    starts: set[str] = set()
    for match in _SPAN.finditer(folded):
        (start_hour, start_minutes), (end_hour, end_minutes) = _split(match.group("start")), _split(match.group("end"))
        start_suffix = match.group("start_suffix") or (match.group("end_suffix") if start_hour <= end_hour else None)
        if start := _clock(start_hour, start_minutes, start_suffix):
            starts.add(start)
        if end := _clock(end_hour, end_minutes, match.group("end_suffix")):
            ends.add(end)
    for match in _TIME.finditer(folded):
        value = _time_of(match)
        if value is None:
            continue
        every.add(value)
        if _UNTIL.search(folded[max(0, match.start() - 12) : match.start()]):
            ends.add(value)
        elif value not in ends:
            starts.add(value)
    return starts, every | starts | ends


def times(text: str) -> set[str]:
    """Every clock time in a text, as HH:MM (24 h)."""
    return clock_times(text)[1]


def _covers(event: dict[str, Any], day: date) -> bool:
    """Whether the event is on that day: its date, a day of its range, or one of its sessions."""
    iso = day.isoformat()
    first, last = event.get("date") or "", event.get("end_date") or event.get("date") or ""
    sessions = [session.get("date") for session in event.get("sessions") or []]
    return first <= iso <= last or iso in sessions


def _weekday_dates(folded: str, published: date) -> list[date]:
    """The days the text names with their weekday, from the post's day on: "sábado 10 de octubre" (its month, the
    post's year, or the next one for a month already past), "jueves 08" (the next 8th that's a Thursday, within two
    months). A weekday that doesn't fit the day (a typo, an OCR misread) names nothing, nor does a deadline's line."""
    found = []
    for match in _WEEKDAY_DAY.finditer(folded):
        line_start = folded.rfind("\n", 0, match.start()) + 1
        line_end = folded.find("\n", match.end())
        if _DEADLINE.search(folded[line_start : line_end if line_end >= 0 else None]):
            continue
        weekday, day = _WEEKDAYS[match.group("weekday")], int(match.group("day"))
        candidates: list[date] = []
        if match.group("month"):
            month = _MONTHS[match.group("month")]
            year = published.year + (1 if month < published.month - 1 else 0)  # December's post about January
            with suppress(ValueError):  # "31 de noviembre": no such day
                candidates.append(date(year, month, day))
        else:
            candidates = [published + timedelta(days=offset) for offset in range(62)]
            candidates = [candidate for candidate in candidates if candidate.day == day]
        fitting = [c for c in candidates if c.weekday() == weekday and c >= published]
        if fitting:
            found.append(fitting[0])
    return found


def _relative_dates(folded: str, published: date) -> list[list[date]]:
    """The days the text names relative to the post: "este sábado" (the next Saturday, or the day itself), "el
    próximo viernes" (that or the one after), "este fin de semana" (Thursday to Sunday). Each mention: the days any
    of which is right."""
    found = []
    for match in _RELATIVE.finditer(folded):
        if match.group("weekend"):
            friday = published + timedelta(days=(4 - published.weekday()) % 7)
            found.append([friday - timedelta(days=1), *(friday + timedelta(days=offset) for offset in range(3))])
        else:
            ahead = (_WEEKDAYS[match.group("weekday")] - published.weekday()) % 7
            later = [published + timedelta(days=ahead + 7)] if "proximo" in match.group("which") else []
            found.append([published + timedelta(days=ahead), *later])
    return found


def flags(text: str, events: list[dict[str, Any]], published: date | None = None) -> list[str]:
    """Why the reading of a post with this text deserves a second look (empty: it doesn't). `events` as the model
    answered them (PostAnalysis.events, as JSON); `published`: the post's day in Bogotá (the rules about weekdays,
    relative days and past dates need it)."""
    folded = _lines(text)
    kept = [event for event in events if not event.get("is_recurring")]
    found: list[str] = []
    if _DATE.search(folded) and not kept:
        found.append(DATES_WITHOUT_EVENT)
    starts, every = clock_times(text)
    if every and any(not event.get("start_time") for event in kept):
        found.append(TIME_NOT_READ)
    ranges = [
        match
        for match in _RANGE.finditer(folded)
        if match.group("joint") != "y" or int(match.group("last")) == int(match.group("first")) + 1
    ]
    if ranges and kept and not any(event.get("end_date") or event.get("sessions") for event in kept):
        found.append(RANGE_AS_ONE_DAY)
    if len(starts) >= 3 and len(kept) == 1:
        found.append(TIMES_OVER_EVENTS)
    occasions = sum(len(event.get("sessions") or []) or 1 for event in kept)
    if kept and any(len(re.findall(_DAY, match.group(0))) > occasions for match in _LIST.finditer(folded)):
        found.append(LIST_NOT_READ)
    if published is None:
        return found
    named = _weekday_dates(folded, published)
    if kept and any(not any(_covers(event, day) for event in kept) for day in named):
        found.append(DAY_WITHOUT_EVENT)
    relative = _relative_dates(folded, published)
    if relative and not any(any(_covers(event, day) for event in kept) for days in relative for day in days):
        found.append(RELATIVE_WITHOUT_EVENT)
    if any((event.get("end_date") or event.get("date") or "9999") < published.isoformat() for event in kept):
        found.append(BEFORE_POST)
    return found
