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


# ---------- the review of 7 Oct 2026: right readings that were flagged, and a missed one ----------


def test_a_festivals_list_of_days_is_covered_by_the_festival():
    days = "Festival del 13 al 16 de noviembre: 13, 14, 15 y 16 de noviembre"
    festival = [event(date="2026-11-13", end_date="2026-11-16")]
    assert checks.flags(days, festival, WEDNESDAY) == []


def test_two_nights_in_a_row_read_as_two_events_arent_a_range_read_as_one_day():
    nights = [event(date="2026-10-09"), event(date="2026-10-10")]
    assert checks.flags("Concierto 9 y 10 de octubre", nights, WEDNESDAY) == []
    assert checks.RANGE_AS_ONE_DAY in checks.flags("Concierto 9 y 10 de octubre", nights[:1], WEDNESDAY)


def test_dates_already_past_when_posted_arent_dates_without_an_event():
    """A recap names the night it thanks people for: no event is right."""
    assert checks.flags("Gracias a todos por venir el 3 de octubre", [], WEDNESDAY) == []
    assert checks.DATES_WITHOUT_EVENT in checks.flags("Nos vemos el 24 de octubre", [], WEDNESDAY)


def test_an_end_time_on_an_events_line_isnt_a_deadline():
    text = "Sábado 10 de octubre, de 8 pm hasta las 2 am"
    assert checks.DAY_WITHOUT_EVENT in checks.flags(text, [event(date="2026-10-17")], WEDNESDAY)
    deadline = "Preventa hasta el viernes 9 de octubre"
    assert checks.DAY_WITHOUT_EVENT not in checks.flags(deadline, [event(date="2026-10-17")], WEDNESDAY)


def test_a_past_weekday_isnt_a_coming_one():
    assert checks.flags("Así se vivió el sábado pasado", [event(date="2026-10-17")], WEDNESDAY) == []


def test_the_same_time_with_and_without_its_pm_is_one_start():
    """The caption says "8:30 pm", the flyer's OCR "8:30": one start, not two."""
    text = "Clase 7 pm · Social 8:30 pm\n8:30"
    assert checks.TIMES_OVER_EVENTS not in checks.flags(text, [event(start_time="19:00")], WEDNESDAY)


def test_a_span_past_midnight_starts_at_night():
    starts, _ = checks.clock_times("Rumba de 11 a 2 am")
    assert starts == {"23:00"}


# ---------- false flags found on the site's own posts (7 Oct 2026), not the test set the rules were tuned on ----------


def test_classes_before_a_social_are_the_social():
    """@showstarscol: bachata 7–8 pm, bachazouk 8–9 pm, the social 9 pm–1 am: one night, read right."""
    text = (
        "De 7:00 PM a 8:00 PM Bachata Tradicional\nDe 8:00 PM a 9:00 PM Bachazouk\n9:00 PM a 1:00 AM — SOCIAL CROSSOVER"
    )
    social = [event(start_time="19:00", event_type="social", date="2026-09-12")]
    assert checks.flags(text, social, date(2026, 9, 8)) == []
    workshops = [event(start_time="19:00", event_type="workshop", date="2026-09-12")]
    assert checks.TIMES_OVER_EVENTS in checks.flags(text, workshops, date(2026, 9, 8))


def test_a_relative_day_after_its_date_is_that_date():
    """@salsaysonoficial, posted on Monday 5 Oct: "este sábado 24 de octubre … Este sábado nos vemos"."""
    text = "este sábado 24 de octubre la cita es en Salsa y Son\nEste sábado nos vemos en Salsa y Son."
    assert checks.flags(text, [event(date="2026-10-24", start_time=None)], date(2026, 10, 5)) == []


def test_a_ticket_tier_isnt_the_events_days():
    """@elratonsalsaclub: "Del 16 al 30 de Octubre: $70.000" is when a price holds."""
    text = "De 3pm a 3am este 31 de Octubre\n🎟️ Hasta el 15 de Octubre: $50.000\n🎟️ Del 16 al 30 de Octubre: $70.000"
    assert checks.flags(text, [event(date="2026-10-31", start_time="15:00")], date(2026, 9, 29)) == []


def test_a_deadlines_time_and_a_festivals_hours_arent_a_start_not_read():
    """@casineafest: "FECHA LÍMITE: 1 DE NOVIEMBRE · 11:59 p. m." for a festival of 13–16 Nov."""
    text = (
        "Festival del 13 al 16 de noviembre 2026\nFECHA LÍMITE: 1 DE NOVIEMBRE DE 2026\n⏰ 11:59 p. m. — hora Colombia"
    )
    festival = [event(date="2026-11-13", end_date="2026-11-16", start_time=None)]
    assert checks.flags(text, festival, date(2026, 9, 22)) == []
    assert checks.TIME_NOT_READ in checks.flags("Social 13 de noviembre 8 pm", [event(start_time=None)], WEDNESDAY)


# ---------- the Spanish the rules missed (the audit of 7 Oct 2026) ----------

POSTED = date(2026, 10, 7)  # a Wednesday


def test_a_flyers_short_weekday_is_a_weekday_but_mar_isnt_march():
    assert checks.DAY_WITHOUT_EVENT in checks.flags("SÁB 10 OCT · VIE. 9", [event(date="2026-10-09")], POSTED)
    assert checks.flags("SÁB 10 OCT", [event(date="2026-10-10")], POSTED) == []
    # "MAR 13" on a flyer is martes 13, not 13 March: no date with no event.
    assert checks.DATES_WITHOUT_EVENT not in checks.flags("MAR 13 · Clase de salsa", [], POSTED)
    assert checks.DATES_WITHOUT_EVENT in checks.flags("13 MAR · Clase de salsa", [], POSTED)


def test_today_and_tomorrow_with_a_weekday_are_relative_days():
    assert checks.RELATIVE_WITHOUT_EVENT in checks.flags("Mañana jueves: social", [event(date="2026-10-15")], POSTED)
    assert checks.flags("Hoy miércoles: social", [event(date="2026-10-07")], POSTED) == []
    assert checks.flags("Reserva hoy · 9 de la mañana", [event(date="2026-10-15", start_time="09:00")], POSTED) == []
    gone = "Gracias por venir este sábado que pasó · nos vemos el 17 de octubre"
    assert checks.RELATIVE_WITHOUT_EVENT not in checks.flags(gone, [event(date="2026-10-17")], POSTED)


def test_hours_said_in_words():
    assert checks.times("Desde las 8 de la noche") == {"20:00"}
    assert checks.times("10 de la mañana · 3 de la tarde") == {"10:00", "15:00"}
    assert checks.times("Al mediodía y hasta la medianoche") == {"12:00", "00:00"}
    assert checks.clock_times("12 de la noche")[1] == {"00:00"}
    # "sábado 8 de la noche" is an hour, not the 8th.
    assert checks.DAY_WITHOUT_EVENT not in checks.flags("Sábado 8 de la noche", [event()], POSTED)


def test_times_that_bound_the_night_arent_starts():
    starts, _ = checks.clock_times("Entrada gratis antes de las 10 pm · cerramos a las 3 am · social desde las 8 pm")
    assert starts == {"20:00"}
    assert checks.clock_times("de 9 pm — 2 am")[0] == {"21:00"}


def test_ranges_in_more_spellings():
    for text in (
        "13 a 16 de noviembre",
        "noviembre 13 al 16",
        "Nov 13-16",
        "13 & 14 de noviembre",
        "desde el 13 hasta el 16 de noviembre",
    ):
        assert checks.RANGE_AS_ONE_DAY in checks.flags(text, [event(date="2026-11-13")], POSTED), text
    assert checks.flags("Nov 13-16", [event(date="2026-11-13", end_date="2026-11-16")], POSTED) == []


def test_lists_in_more_spellings():
    for text in ("3, 10, 17, 24 de octubre", "3 · 10 · 17 · 24 OCT", "17 y el 24 de octubre"):
        assert checks.LIST_NOT_READ in checks.flags(text, [event(date="2026-10-17")], POSTED), text


def test_dates_in_more_spellings():
    for text in (
        "1ro de noviembre",
        "1° de noviembre",
        "primero de noviembre",
        "11/10/2026",
        "11-10-2026",
        "11.10.2026",
    ):
        assert checks.DATES_WITHOUT_EVENT in checks.flags(text, [], POSTED), text
    assert checks.flags("Clase a las 10.30 · cupos 10.10", [], POSTED) == []  # times, not dates


def test_a_closing_night_is_an_event_and_other_deadlines_arent():
    assert checks.DAY_WITHOUT_EVENT in checks.flags("Fiesta de cierre sábado 10", [event(date="2026-10-17")], POSTED)
    for deadline in ("Cierre de inscripciones sábado 10", "Inscríbete antes del sábado 10", "Promo hasta el viernes 9"):
        assert checks.flags(deadline, [event(date="2026-10-17")], POSTED) == [], deadline


def test_a_price_without_its_sign_makes_a_price_line():
    assert checks.flags("Del 16 al 30 de octubre: 70.000 · Inversión", [event(date="2026-10-31")], POSTED) == []
