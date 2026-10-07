"""The rule checks (checks.py) and OCR's rows (ocr.group_rows): what flags a lighter model's reading for a second
look. The cases are the test set's (gold/), from Flash-Lite's run of 7 Oct 2026."""

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
