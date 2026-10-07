"""Rules that flag a reading for a second look, with no AI: the post's text (its caption and the flyer's OCR text,
ocr.py) says something its events don't. Flash-Lite's misses on the test set (gold/, 7 Oct 2026) were judgments, not
misreadings: a four-Saturday course and two bar nights dropped as "regular", three workshops merged into one, a start
time in the caption skipped, "11 OCT — 01 NOV" kept as one day. Each leaves a trace these rules see. A flag costs one
more request on a post; a missed error costs a wrong or missing event on the site."""

import re
from typing import Any

from .text import fold

_MONTH = (
    r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
    r"|ene|feb|mar|abr|may|jun|jul|ago|sept|sep|set|oct|nov|dic)"
)
# "11 de octubre", "9DEOCT" (OCR drops spaces), "octubre 11", "11/10"; within one line.
_DAY = r"(?<![\d#/])(?:3[01]|[12]\d|0?[1-9])(?!\d)"  # 1 to 31, not a piece of an address ("#3-84") or a number
_DATE = re.compile(rf"{_DAY}[ \t]*(?:de[ \t]*)?{_MONTH}\b|\b{_MONTH}\.?[ \t]*{_DAY}|{_DAY}/(?:1[0-2]|0?[1-9])(?![\d/])")
# "del 13 al 16 de noviembre", "11 OCT — 01 NOV", "20 y 21 noviembre", "19 al 21 de marzo".
_RANGE = re.compile(
    rf"{_DAY}[ \t]*(?:de[ \t]*)?(?:{_MONTH}\.?)?[ \t]*(?:-|–|—|al|hasta|y)[ \t]*{_DAY}[ \t]*(?:de[ \t]*)?{_MONTH}\b"
)
# "8:30 p.m.", "8:30P.M", "6pm", "9 AM", "12:00 M", "20:30", "21h".
_TIME = re.compile(
    r"(?<![\d:/])(\d{1,2})(?::([0-5]\d))?\s*(a\.?\s*m\b\.?|p\.?\s*m\b\.?|m\b|h\b|hrs?\b)|(?<![\d:/])(\d{1,2}):([0-5]\d)(?!\d)"
)

DATES_WITHOUT_EVENT = "fechas sin evento"  # dates in the text, no event read (or only "recurring" ones)
TIME_NOT_READ = "hora sin leer"  # a time in the text, an event without one
RANGE_AS_ONE_DAY = "rango como un día"  # a range of dates in the text, every event a single day
TIMES_OVER_EVENTS = "más horas que eventos"  # three or more times in the text, one event


def times(text: str) -> set[str]:
    """The clock times in a text, as HH:MM (24 h)."""
    found = set()
    for match in _TIME.finditer(fold(text)):
        if match.group(1):  # "8:30 pm", "6pm", "12:00 m"
            hour_text, minutes, suffix = match.group(1), match.group(2), match.group(3)
        else:  # "20:30"
            hour_text, minutes, suffix = match.group(4), match.group(5), ""
        hour = int(hour_text)
        suffix = suffix.replace(".", "").replace(" ", "")
        if suffix.startswith("p") and hour < 12:
            hour += 12
        if hour > 23:
            continue
        found.add(f"{hour:02d}:{minutes or '00'}")
    return found


def flags(text: str, events: list[dict[str, Any]]) -> list[str]:
    """Why the reading of a post with this text deserves a second look (empty: it doesn't). `events` as the model
    answered them (PostAnalysis.events, as JSON)."""
    folded = fold(text)
    published = [event for event in events if not event.get("is_recurring")]
    found: list[str] = []
    if _DATE.search(folded) and not published:
        found.append(DATES_WITHOUT_EVENT)
    clock = times(text)
    if clock and any(not event.get("start_time") for event in published):
        found.append(TIME_NOT_READ)
    if _RANGE.search(folded) and published and not any(e.get("end_date") or e.get("sessions") for e in published):
        found.append(RANGE_AS_ONE_DAY)
    if len(clock) >= 3 and len(published) == 1:
        found.append(TIMES_OVER_EVENTS)
    return found
