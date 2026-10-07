"""The rule checks (checks.py) and OCR's rows (ocr.group_rows): what flags a lighter model's reading for a second
look. The cases are the test set's (gold/), from Flash-Lite's run of 7 Oct 2026."""

from datetime import date

from pa_bailar import checks, ocr


def event(**details) -> dict:
    return {"title": "Social", "date": "2026-10-10", "start_time": "20:00", **details}


def test_times_are_read_in_their_usual_spellings():
    text = "Puertas: 6 pm | Shows: 11 pm y 1 am · 8:30P.M · 9:00 AM A 12:00 M · Social 22:30 · 21h"
    assert checks.times(text) == {"18:00", "23:00", "01:00", "20:30", "09:00", "12:00", "22:30", "21:00"}
    # Prices, phones and addresses aren't times.
    assert checks.times("Cover $20.000 · 313 830 8844 · Cll 12 #3-84 · 4 HORAS INTENSIVAS") == set()


def test_dates_in_the_text_and_no_event_read_is_flagged():
    """A four-Saturday course dropped as "a regular course"; two bar nights marked recurring."""
    course = "📔4 Sabados 3, 10, 17 y 24 de octubre ⏰Hora de 5pm a 6pm"
    assert checks.DATES_WITHOUT_EVENT in checks.flags(course, [])
    nights = "📆 Jueves 08 de Octubre 🎺 Orlando 📆 Sábado 10 de Octubre ⏳ Desde las 4 PM"
    recurring = [event(is_recurring=True), event(date="2026-10-08", is_recurring=True)]
    assert checks.DATES_WITHOUT_EVENT in checks.flags(nights, recurring)
    assert checks.flags("Clases todos los martes", []) == []  # no date: nothing to say


def test_a_time_in_the_text_and_an_event_without_one_is_flagged():
    text = "Taller de dancehall y reggaeton - 8:40 pm · Hasta las 5:00 a.m."
    assert checks.TIME_NOT_READ in checks.flags(text, [event(start_time=None)])
    assert checks.TIME_NOT_READ not in checks.flags(text, [event(start_time="20:40")])


def test_a_range_of_dates_and_only_one_day_events_is_flagged():
    for text in ("ROOTS · 11 OCT — 01 NOV 2026", "del 13 al 16 de noviembre", "20 Y 21 NOVIEMBRE 2026"):
        assert checks.RANGE_AS_ONE_DAY in checks.flags(text, [event()]), text
    assert checks.flags("11 OCT — 01 NOV 2026", [event(end_date="2026-11-01")]) == []
    # An address followed by the next line's date isn't a range (El Callejón, "Cll 12 #3-84").
    assert checks.flags("Cll 12 #3-84, La Candelaria\nSábado 10 de octubre", [event()]) == []


def test_three_times_and_one_event_is_flagged():
    """Three workshops at 3, 4 and 5 pm read as one."""
    text = "3:00 p.m. Reguetón · María Mutante\n4:00 p.m. Sabroseo · Blado\n5:00 p.m. Coreografía · Junior"
    assert checks.TIMES_OVER_EVENTS in checks.flags(text, [event(start_time="15:00")])
    three = [event(start_time=hour) for hour in ("15:00", "16:00", "17:00")]
    assert checks.flags(text, three) == []


def test_ocr_pieces_on_one_line_share_a_row_left_to_right():
    def piece(x: float, y: float, text: str, score: float = 0.95, height: float = 40):
        return [[x, y], [x + 100, y], [x + 100, y + height], [x, y + height]], text, score

    found = [piece(500, 210, "Acere"), piece(40, 205, "10"), piece(40, 100, "Real"), piece(300, 330, "福", 0.4)]
    assert ocr.group_rows(found) == ["Real", "10 | Acere"]  # the stray mark read with low confidence is left out


# ---------- the second round (7 Oct 2026, after the package research): lists, weekdays, relative days, spans ----------

WEDNESDAY = date(2026, 10, 7)


def test_a_list_of_dates_isnt_a_range_and_needs_as_many_dates_read():
    course = "4 Sabados 3, 10, 17 y 24 de octubre"
    one = [event(date="2026-10-03")]
    assert checks.RANGE_AS_ONE_DAY not in checks.flags(course, one)  # "17 y 24" isn't a range
    assert checks.LIST_NOT_READ in checks.flags(course, one)
    series = [event(date="2026-10-03", sessions=[{"date": f"2026-10-{d:02d}"} for d in (3, 10, 17, 24)])]
    assert checks.flags(course, series) == []
    assert checks.RANGE_AS_ONE_DAY in checks.flags("20 y 21 noviembre", [event()])  # consecutive: a range


def test_a_weekday_and_its_day_need_an_event_that_day():
    text = "📆 Jueves 08 de Octubre 🎺 Orlando\n📆 Sábado 10 de Octubre 🎺 Zafra Son"
    only_saturday = [event(date="2026-10-10")]
    assert checks.DAY_WITHOUT_EVENT in checks.flags(text, only_saturday, date(2026, 10, 5))
    both = [event(date="2026-10-08"), event(date="2026-10-10")]
    assert checks.flags(text, both, date(2026, 10, 5)) == []
    # A deadline's line, a weekday that doesn't fit its day (an OCR misread), a day already past: nothing to say.
    assert checks.flags("Miércoles 30 | Fin segundo corte aniversario", both, date(2026, 9, 5)) == []
    assert checks.flags("Domingo 7 noviembre", both, date(2026, 10, 3)) == []  # 7 Nov 2026 is a Saturday


def test_a_relative_day_needs_an_event_that_day():
    assert checks.RELATIVE_WITHOUT_EVENT in checks.flags("Este sábado 6PM", [event(date="2026-10-17")], WEDNESDAY)
    assert checks.flags("Este sábado 6PM", [event(date="2026-10-10", start_time="18:00")], WEDNESDAY) == []
    # With its date after it, it's that date ("este jueves, 22 de octubre"): no relative day.
    assert checks.flags("este jueves, 22 de octubre", [event(date="2026-10-22")], date(2026, 10, 4)) == []


def test_a_spans_end_is_a_time_but_not_a_start():
    starts, every = checks.clock_times("Clase de 9 a 10 pm / Social 10pm. a 2:30 am")
    assert starts == {"21:00", "22:00"} and every == {"21:00", "22:00", "02:30"}
    starts, _ = checks.clock_times("desde las 2PM · Clase 3PM · Fiesta hasta las 10PM")
    assert starts == {"14:00", "15:00"}
    assert checks.times("Duración 2 hrs · clase de 1h · 20h30 · 21h") == {"20:30", "21:00"}


def test_an_event_over_before_the_post_is_flagged():
    assert checks.BEFORE_POST in checks.flags("", [event(date="2026-09-26")], WEDNESDAY)
    assert checks.flags("", [event(date="2026-10-07")], WEDNESDAY) == []
