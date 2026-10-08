"""Rules that flag a reading for a second look, with no AI: the post's text (its caption and the flyer's OCR text,
ocr.py) says something its events don't. Flash-Lite's misses on the test set (gold/, 7 Oct 2026) were judgments, not
misreadings: a four-Saturday course and two bar nights dropped as "regular", three workshops merged into one, a start
time in the caption skipped, "11 OCT — 01 NOV" kept as one day. Each leaves a trace these rules see. A flag costs one
more request on a post; a missed error costs a wrong or missing event on the site.

Hand-written on purpose: no maintained Python library reads Spanish date ranges, lists and relative dates together
(dateparser has no ranges or "este sábado"; Recognizers-Text's Python port skips most Spanish cases; Duckling is a
Haskell server), research of 7 Oct 2026. Dates are worked out from the post's day (`published`); without it, the
rules that need a calendar day fall back to counting."""

import re
from contextlib import suppress
from datetime import date, timedelta
from typing import Any

from .text import MONTHS, PRICE_WORDS, WEEKDAYS, fold

_MONTHS = {
    **{"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8},
    **{"septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12},
    **{short: number for number, short in enumerate(MONTHS, start=1)},  # "ene" … "dic" (text.MONTHS)
    **{"sept": 9, "set": 9},
}
_WEEKDAYS = {fold(name): number for number, name in enumerate(WEEKDAYS)}  # "lunes": 0 … "domingo": 6 (text.WEEKDAYS)
# The short forms flyers print ("SÁB 10 OCT", "VIE 9"), read only with a day after them; not "mar" (marzo).
_WEEKDAYS_SHORT = {"lun": 0, "mie": 2, "mier": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"
# A month before its day: not "mar", which on a flyer is more often martes ("MAR 13") than marzo (the audit of 7 Oct).
_MONTH_FIRST = "(?:" + "|".join(sorted(set(_MONTHS) - {"mar"}, key=len, reverse=True)) + ")"
_WEEKDAY = "(?:" + "|".join(_WEEKDAYS) + ")"
_ANY_WEEKDAY = "(?:" + "|".join(sorted({*_WEEKDAYS, *_WEEKDAYS_SHORT}, key=len, reverse=True)) + ")"
# 1 to 31, not a piece of an address ("#3-84"), of a number, or a time's minutes ("8:30").
_DAY = r"(?<![\d#/:])(?:3[01]|[12]\d|0?[1-9])(?!\d)"

# "11 de octubre", "9DEOCT" (OCR drops spaces), "octubre 11", "11/10" (not "24/7"). Matched line by line (_lines).
_DATE = re.compile(
    rf"(?P<day>{_DAY})(?:ro|o|°)?[ \t]*(?:de[ \t]*)?(?P<month>{_MONTH})\b"
    rf"|\bprimero[ \t]*de[ \t]*(?P<month_of_first>{_MONTH})\b"
    rf"|\b(?P<month_first>{_MONTH_FIRST})\.?[ \t]*(?P<day_after>{_DAY})"
    rf"|(?!24/7\b)(?P<day_slash>{_DAY})/(?P<month_number>1[0-2]|0?[1-9])(?:/(?:20)?\d\d)?(?![\d/])"
    rf"|(?P<day_dash>{_DAY})(?P<sep>[.-])(?P<month_dash>1[0-2]|0?[1-9])(?P=sep)(?:20)?\d\d(?!\d)"
)
# A range: "del 13 al 16 de noviembre", "11 OCT — 01 NOV", "19 al 21 de marzo", "20 y 21 noviembre" ("y" only
# between consecutive days: "17 y 24 de octubre" ends a list of dates, _LIST).
_RANGE = re.compile(
    rf"(?P<first>{_DAY})[ \t]*(?:de[ \t]*)?(?:(?P<first_month>{_MONTH})\.?)?[ \t]*(?P<joint>-|–|—|al|a|hasta|y|&)[ \t]*"
    rf"(?:el[ \t]+)?(?P<last>{_DAY})[ \t]*(?:de[ \t]*)?(?P<last_month>{_MONTH})\b"
    rf"|\b(?P<month_before>{_MONTH_FIRST})\.?[ \t]*(?P<first_after>{_DAY})[ \t]*(?P<joint_after>-|–|—|al|a|&)[ \t]*"
    rf"(?P<last_after>{_DAY})(?![\d:])"
)
# A list: "3, 10, 17 y 24 de octubre" (a series' dates, or several nights), "3, 10, 17, 24 de octubre", "3 · 10 · 17 ·
# 24 OCT", "17 y el 24 de octubre".
_LIST = re.compile(
    rf"(?:{_DAY}(?:[ \t]*[,·][ \t]*{_DAY})+(?:[ \t]*,?[ \t]*y[ \t]*(?:el[ \t]+)?{_DAY})?"
    rf"|{_DAY}[ \t]*y[ \t]+el[ \t]+{_DAY})[ \t]*(?:de[ \t]*)?(?P<month>{_MONTH})\b"
)
# A number that's an hour, not a day: "sábado 6PM", "viernes 8:30".
_AN_HOUR = r"(?=[ \t]*(?::|a\.?[ \t]*m\b|p\.?[ \t]*m\b|h\b|hrs?\b|de[ \t]+la[ \t]+(?:noche|tarde|manana)\b))"
# A weekday with its day: "sábado 10 de octubre", "jueves 08", "domingo 11".
_WEEKDAY_DAY = re.compile(
    rf"\b(?P<weekday>{_ANY_WEEKDAY})s?\.?[ \t,]*(?!{_DAY}{_AN_HOUR})(?P<day>{_DAY})"
    rf"(?:[ \t]*(?:de[ \t]*)?(?P<month>{_MONTH})\b)?"
)
# A day relative to the post: "este sábado", "el próximo viernes", "este fin de semana"; not with a day after it
# ("este jueves, 22 de octubre" is that date: _WEEKDAY_DAY), though an hour may follow ("este sábado 6PM"), nor a day
# gone ("el sábado pasado"). Not "esta noche": captions use it for the event's night whenever it is ("esta noche no
# vienes solo a bailar").
_RELATIVE = re.compile(
    rf"\b(?P<which>este|el proximo|proximo|el|hoy|manana)[ \t]+(?P<weekday>{_WEEKDAY})\b"
    rf"(?![ \t,]*{_DAY}(?!{_AN_HOUR}))(?![ \t]+(?:pasado|anterior|que[ \t]+paso)\b)"
    r"|\b(?P<weekend>este (?:fin de semana|finde))\b"
)
# Words around a weekday and its day that make it a deadline, not an event: "Miércoles 30 | Fin segundo corte",
# "Preventa hasta el viernes 9". Not "hasta" after it: "Sábado 10, de 8 pm hasta las 2 am" is the event's night.
_DEADLINE_WORDS = {"corte", "cierre", "preventa", "preventas", "inscripcion", "inscripciones", "plazo", "vence"}
_DEADLINE_WORDS |= {"limite", "ultimo", "ultima", "ultimos", "ultimas", "vencen", "tardar", "matricula"}
_DEADLINE_WORDS |= {"matriculas", "early", "promo"}
# A closing night is an event: "Fiesta de cierre sábado 10" isn't a deadline (the audit of 7 Oct 2026).
_CLOSING_NIGHT = re.compile(r"\b(?:fiesta|noche|gala|social|rumba|evento|concierto|show)[ \t]+de[ \t]+cierre\b")

_SUFFIX = r"(?:a\.?[ \t]*m\b\.?|p\.?[ \t]*m\b\.?|m\b|de[ \t]+la[ \t]+(?:noche|tarde|manana)\b)"
# A clock time: "8:30 p.m.", "8:30P.M", "6pm", "9 AM", "12:00 M", "20:30", "20h30", "21h" (an "h" after an hour
# under 12 is a duration: "2 h", "clase de 1h").
_TIME = re.compile(
    rf"(?<![\d:/])(?P<hour>\d{{1,2}})(?::(?P<minutes>[0-5]\d))?[ \t]*(?P<suffix>{_SUFFIX})"
    r"|(?<![\d:/])(?P<hour24>\d{1,2})(?::|h)(?P<minutes24>[0-5]\d)(?!\d)"
    r"|(?<![\d:/])(?P<hourh>1\d|2[0-3])h\b"
    r"|\b(?P<named>mediodia|medianoche)\b"
)
# A span of time: "de 9 a 10 pm", "10pm. a 2:30 am", "9:00 AM A 12:00 M", "desde las 2 hasta las 10 pm": its start
# is a start time, its end isn't. A start without am/pm takes the end's ("de 9 a 10 pm" starts at 21:00), or the
# night's when the span ends after midnight ("de 11 a 2 am" starts at 23:00).
_SPAN = re.compile(
    rf"(?P<start>\d{{1,2}}(?::[0-5]\d)?)[ \t]*(?P<start_suffix>{_SUFFIX})?[ \t]*(?:a|-|–|—|hasta)[ \t]*(?:las[ \t]*)?"
    rf"(?P<end>\d{{1,2}}(?::[0-5]\d)?)[ \t]*(?P<end_suffix>{_SUFFIX})"
)
_UNTIL = re.compile(
    r"\b(?:hasta|antes[ \t]+de|despues[ \t]+de|cerramos[ \t]+a|cierra[ \t]+a|termina[ \t]+a|terminamos[ \t]+a"
    r"|finaliza[ \t]+a)[ \t]*(?:las?[ \t]*)?$"
)  # "hasta las 5 am", "antes de las 10 pm", "cerramos a las 3 am": an end or a bound, not a start
_WORDS = re.compile(r"[a-z]+")
# A price or a sale: "$70.000", "30k", "20 mil", "cover", "etapa", "boletería".
_PRICE = re.compile(
    r"\$|\b\d+[ \t]*(?:k|mil)\b|\b\d{1,3}\.\d{3}\b"
    rf"|\b(?:{'|'.join(PRICE_WORDS)}|etapa|boleteria|taquilla|preventa|consumible|cop)\b"
)

DATES_WITHOUT_EVENT = "fechas sin evento"  # a coming date in the text, no event read (or only "recurring" ones)
TIME_NOT_READ = "hora sin leer"  # a time in the text, an event without one
RANGE_AS_ONE_DAY = "rango como un día"  # a range of dates in the text, its last day in no event
TIMES_OVER_EVENTS = "más horas que eventos"  # three or more start times in the text, one event
LIST_NOT_READ = "lista de fechas sin leer"  # "3, 10, 17 y 24 de octubre", a coming one in no event
DAY_WITHOUT_EVENT = "día sin evento"  # "sábado 10 de octubre" (from the post's day on), no event that day
RELATIVE_WITHOUT_EVENT = "día relativo sin evento"  # "este sábado", "el próximo viernes"…, no event that day
BEFORE_POST = "antes de la publicación"  # an event over before the post went up: a date misread


def _lines(text: str) -> str:
    """Folded line by line, so a pattern never joins the end of one line to the next (an address and a date)."""
    return "\n".join(fold(line) for line in text.splitlines())


def _day(day: int, month: int, published: date | None) -> date | None:
    """That day of that month in the post's year, or the next one when the month is already well past (a December
    post about January). None without the post's day, or for a day that doesn't exist ("31 de noviembre")."""
    if published is None:
        return None
    year = published.year + (1 if month < published.month - 1 else 0)
    with suppress(ValueError):
        return date(year, month, day)
    return None


def _date_of(match: re.Match[str], published: date | None) -> date | None:
    if match.group("day"):
        return _day(int(match.group("day")), _MONTHS[match.group("month")], published)
    if match.group("month_of_first"):
        return _day(1, _MONTHS[match.group("month_of_first")], published)
    if match.group("day_after"):
        return _day(int(match.group("day_after")), _MONTHS[match.group("month_first")], published)
    if match.group("day_dash"):
        return _day(int(match.group("day_dash")), int(match.group("month_dash")), published)
    return _day(int(match.group("day_slash")), int(match.group("month_number")), published)


def _clock(hour: int, minutes: str | None, suffix: str | None) -> str | None:
    suffix = (suffix or "").replace(".", "").replace(" ", "").replace("\t", "")
    if suffix.startswith("dela"):  # "de la noche", "de la tarde": pm; "de la mañana": am; "12 de la noche": 0:00
        suffix = "am" if suffix.endswith("manana") or (hour == 12 and suffix.endswith("noche")) else "pm"
    if suffix.startswith("p") and hour < 12:
        hour += 12
    elif suffix.startswith("a") and hour == 12:
        hour = 0
    return f"{hour:02d}:{minutes or '00'}" if hour <= 23 else None


def _time_of(match: re.Match[str]) -> str | None:
    if match.group("named"):
        return "12:00" if match.group("named") == "mediodia" else "00:00"
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
        start_suffix, end_suffix = match.group("start_suffix"), match.group("end_suffix")
        if not start_suffix:
            past_midnight = end_suffix.startswith("a") and start_hour > end_hour
            start_suffix = "pm" if past_midnight else end_suffix if start_hour <= end_hour else None
        if start := _clock(start_hour, start_minutes, start_suffix):
            starts.add(start)
        if end := _clock(end_hour, end_minutes, end_suffix):
            ends.add(end)
    for match in _TIME.finditer(folded):
        value = _time_of(match)
        if value is None or value.endswith(":59"):  # "11:59 p. m.": a deadline, never an event's start
            continue
        every.add(value)
        if _UNTIL.search(folded[max(0, match.start() - 24) : match.start()]):
            ends.add(value)
        elif value not in ends:
            starts.add(value)
    return starts, every | starts | ends


def times(text: str) -> set[str]:
    """Every clock time in a text, as HH:MM (24 h)."""
    return clock_times(text)[1]


def _slots(clock: set[str]) -> set[str]:
    """Times on a 12-hour dial: "8:30" in the flyer's OCR and "8:30 pm" in the caption are one time."""
    return {f"{int(value[:2]) % 12:02d}{value[2:]}" for value in clock}


def _covers(event: dict[str, Any], day: date) -> bool:
    """Whether the event is on that day: its date, a day of its range, or one of its sessions."""
    iso = day.isoformat()
    first, last = event.get("date") or "", event.get("end_date") or event.get("date") or ""
    sessions = [session.get("date") for session in event.get("sessions") or []]
    return first <= iso <= last or iso in sessions


def _uncovered(days: list[date], events: list[dict[str, Any]], published: date) -> bool:
    """Whether a coming day among these is on no event."""
    return any(day >= published and not any(_covers(event, day) for event in events) for day in days)


def _occasions(event: dict[str, Any]) -> int:
    """How many days an event takes: its sessions, the days of its range, or one."""
    if event.get("sessions"):
        return len(event["sessions"])
    first, last = event.get("date"), event.get("end_date")
    if isinstance(first, str) and isinstance(last, str):
        with suppress(ValueError):  # a date that isn't one
            return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    return 1


def _is_deadline(folded: str, match: re.Match[str]) -> bool:
    """Whether the words right around a weekday and its day make it a deadline (_DEADLINE_WORDS)."""
    line_start = folded.rfind("\n", 0, match.start()) + 1
    line_end = folded.find("\n", match.end())
    line = folded[line_start : line_end if line_end >= 0 else None]
    before = _WORDS.findall(folded[line_start : match.start()])[-3:]
    after = _WORDS.findall(folded[match.end() : line_end if line_end >= 0 else None])[:4]
    words = _DEADLINE_WORDS - ({"cierre"} if _CLOSING_NIGHT.search(line) else set())
    return "hasta" in before[-2:] or "antes" in before[-3:] or bool(words & {*before, *after})


def _weekday_dates(folded: str, published: date) -> list[date]:
    """The days the text names with their weekday, from the post's day on: "sábado 10 de octubre" (_day), "jueves 08"
    (the next 8th that's a Thursday, within two months). A weekday that doesn't fit the day (a typo, an OCR misread)
    names nothing, nor does a deadline (_is_deadline)."""
    found = []
    for match in _WEEKDAY_DAY.finditer(folded):
        if _is_deadline(folded, match):
            continue
        weekday, day = {**_WEEKDAYS, **_WEEKDAYS_SHORT}[match.group("weekday")], int(match.group("day"))
        if match.group("month"):
            candidates = [found_day] if (found_day := _day(day, _MONTHS[match.group("month")], published)) else []
        else:
            candidates = [published + timedelta(days=offset) for offset in range(62)]
            candidates = [candidate for candidate in candidates if candidate.day == day]
        fitting = [c for c in candidates if c.weekday() == weekday and c >= published]
        if fitting:
            found.append(fitting[0])
    return found


def _relative_dates(folded: str, published: date, dated: list[date]) -> list[list[date]]:
    """The days the text names relative to the post: "este sábado" (the next Saturday, or the day itself), "el
    próximo viernes" (that or the one after), "este fin de semana" (Thursday to Sunday). Each mention: the days any
    of which is right. A weekday the text also gives with its date (`dated`) is that date too: "este sábado 24 de
    octubre … Este sábado nos vemos", posted on the 5th (@salsaysonoficial, 7 Oct 2026)."""
    found = []
    for match in _RELATIVE.finditer(folded):
        if match.group("weekend"):
            friday = published + timedelta(days=(4 - published.weekday()) % 7)
            found.append([friday - timedelta(days=1), *(friday + timedelta(days=offset) for offset in range(3))])
        else:
            weekday = _WEEKDAYS[match.group("weekday")]
            ahead = (weekday - published.weekday()) % 7
            later = [published + timedelta(days=ahead + 7)] if "proximo" in match.group("which") else []
            same_weekday = [day for day in dated if day.weekday() == weekday]
            found.append([published + timedelta(days=ahead), *later, *same_weekday])
    return found


def _on_a_price_line(folded: str, match: re.Match[str]) -> bool:
    """Whether the match sits with a price or a sale's words (one piece of an OCR row, or the caption's line): "Del 16
    al 30 de Octubre: $70.000" is when a price holds, not the event's days (@elratonsalsaclub, 7 Oct 2026)."""
    start = max(folded.rfind("\n", 0, match.start()), folded.rfind("|", 0, match.start())) + 1
    ends = [found for found in (folded.find("\n", match.end()), folded.find("|", match.end())) if found >= 0]
    return bool(_PRICE.search(folded[start : min(ends) if ends else None])) or _is_deadline(folded, match)


def _range_first(match: re.Match[str]) -> int:
    return int(match.group("first") or match.group("first_after"))


def _range_last(match: re.Match[str]) -> tuple[int, str]:
    # A range's last day and its month's name: "13 al 16 de noviembre" or "noviembre 13 al 16".
    if match.group("last_after"):
        return int(match.group("last_after")), match.group("month_before")
    return int(match.group("last")), match.group("last_month")


def _range_joint(match: re.Match[str]) -> str:
    return match.group("joint") or match.group("joint_after")


def _range_flag(folded: str, kept: list[dict[str, Any]], published: date | None) -> bool:
    """A range of dates whose last day is on no event ("11 OCT — 01 NOV" read as 11 Oct only); two nights in a row
    read as two events cover it. Without the post's day: any range, and no event over several days."""
    ranges = [
        match
        for match in _RANGE.finditer(folded)
        if (_range_joint(match) not in ("y", "&") or _range_last(match)[0] == _range_first(match) + 1)
        and not _on_a_price_line(folded, match)
    ]
    if not ranges or not kept:
        return False
    if published is None:
        return not any(event.get("end_date") or event.get("sessions") for event in kept)
    last_days = [_day(day, _MONTHS[month], published) for day, month in map(_range_last, ranges)]
    return _uncovered([day for day in last_days if day], kept, published)


def _list_flag(folded: str, kept: list[dict[str, Any]], published: date | None) -> bool:
    """A list of dates ("3, 10, 17 y 24 de octubre") with a coming day on no event. Without the post's day: more days
    listed than the events take."""
    if not kept:
        return False
    for match in _LIST.finditer(folded):
        days = [int(day) for day in re.findall(_DAY, match.group(0))]
        if published is None:
            if len(days) > sum(_occasions(event) for event in kept):
                return True
            continue
        listed = [_day(day, _MONTHS[match.group("month")], published) for day in days]
        if _uncovered([day for day in listed if day], kept, published):
            return True
    return False


def flags(text: str, events: list[dict[str, Any]], published: date | None = None) -> list[str]:
    """Why the reading of a post with this text deserves a second look (empty: it doesn't). `events` as the model
    answered them (PostAnalysis.events, as JSON); `published`: the post's day in Bogotá (the rules about coming days,
    weekdays, relative days and past dates need it)."""
    folded = _lines(text)
    kept = [event for event in events if not event.get("is_recurring")]
    found: list[str] = []
    dates = [_date_of(match, published) for match in _DATE.finditer(folded)]
    coming = dates if published is None else [day for day in dates if day and day >= published]
    if coming and not kept:
        found.append(DATES_WITHOUT_EVENT)
    starts, every = clock_times(text)
    # A festival over several days has its workshops' hours, not one start (@casineafest); a series has its own.
    one_start = [event for event in kept if event.get("sessions") or not event.get("end_date")]
    if every and any(not event.get("start_time") for event in one_start):
        found.append(TIME_NOT_READ)
    if _range_flag(folded, kept, published):
        found.append(RANGE_AS_ONE_DAY)
    # Classes before a social are that social (@showstarscol: bachata 7 pm, bachazouk 8 pm, the social 9 pm).
    if len(_slots(starts)) >= 3 and len(kept) == 1 and kept[0].get("event_type") not in ("social", "party"):
        found.append(TIMES_OVER_EVENTS)
    if _list_flag(folded, kept, published):
        found.append(LIST_NOT_READ)
    if published is None:
        return found
    named = _weekday_dates(folded, published)
    if kept and _uncovered(named, kept, published):
        found.append(DAY_WITHOUT_EVENT)
    relative = _relative_dates(folded, published, [*named, *(day for day in coming if day)])
    if relative and not any(any(_covers(event, day) for event in kept) for days in relative for day in days):
        found.append(RELATIVE_WITHOUT_EVENT)
    if any((event.get("end_date") or event.get("date") or "9999") < published.isoformat() for event in kept):
        found.append(BEFORE_POST)
    return found
