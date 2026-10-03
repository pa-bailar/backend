"""Gemini output is cleaned before it is stored, because the frontend relies on these formats."""

import pytest

from pa_bailar.models import Price
from pa_bailar.normalize import (
    normalize_contact,
    normalize_event,
    normalize_style,
    normalize_styles,
    parse_iso_date,
    parse_time,
)
from tests.factories import extracted


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-03", "2026-10-03"),
        (" 2026-10-03 ", "2026-10-03"),
        ("2026-10-3", None),
        ("2026-02-30", None),
        ("3 de octubre", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_iso_date(value, expected):
    assert parse_iso_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("21:00", "21:00"), ("9:05", "09:05"), ("24:00", None), ("21:60", None), ("9pm", None), (None, None)],
)
def test_parse_time(value, expected):
    assert parse_time(value) == expected


def test_styles_are_mapped_to_the_list_and_deduplicated():
    assert normalize_styles([" Salsa  Caleña", "salsa caleña", "", "Bachata"]) == ["salsa caleña", "bachata"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mambo", "salsa en línea"),
        ("Salsa On2", "salsa en línea"),
        ("salsa en linea", "salsa en línea"),
        ("Casino", "salsa cubana"),
        ("rueda de casino", "salsa cubana"),
        ("estilo caleño", "salsa caleña"),
        ("bachata tradicional", "bachata dominicana"),
        ("Bachata moderna", "bachata"),
        ("reggaetón", "urbano"),
        ("Rumba", "afro"),
        ("chachachá", "cha cha chá"),
        ("tango", "tango"),
        ("vals", "otro"),
    ],
)
def test_synonyms_map_to_the_style_list(raw, expected):
    assert normalize_style(raw) == expected


def test_generic_salsa_or_bachata_is_dropped_when_a_variant_is_known():
    assert normalize_styles(["salsa", "salsa caleña", "bachata"]) == ["salsa caleña", "bachata"]
    assert normalize_styles(["bachata", "bachata sensual", "salsa"]) == ["bachata sensual", "salsa"]


def test_invalid_start_time_is_dropped_and_noted_as_a_doubt():
    event = normalize_event(extracted(start_time="9pm"))
    assert event.start_time is None
    assert any("9pm" in doubt for doubt in event.doubts)


def test_invalid_date_becomes_none_so_the_event_is_not_published():
    assert normalize_event(extracted(date="sábado")).date is None


def test_negative_prices_are_removed():
    prices = [Price(label="General", amount_cop=20000), Price(label="Error", amount_cop=-1)]
    assert [p.label for p in normalize_event(extracted(prices=prices)).prices] == ["General"]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("@bureodancestudio", "@bureodancestudio"),
        ("appdanza.com", "appdanza.com"),
        ("distrito-social-academy.com/eventos", "distrito-social-academy.com/eventos"),
        ("3164952960", "3164952960"),
        ("350-537-2687", "350-537-2687"),
        ("WhatsApp 320 2332984", "WhatsApp 320 2332984"),
        ("Wpp: 3018847358", "WhatsApp 3018847358"),
        ("SOCIAL", None),
        ("  ", None),
        (None, None),
    ],
)
def test_contacts_are_kept_only_when_the_site_can_link_them(raw, clean):
    assert normalize_contact(raw) == clean


def test_prices_without_a_label_are_dropped_and_untitled_events_arent_published():
    from pa_bailar.pipeline import _is_publishable

    event = normalize_event(
        extracted(prices=[Price(label=" ", amount_cop=20000), Price(label="General", amount_cop=0)])
    )
    assert [price.label for price in event.prices] == ["General"]  # the site's check-data requires a label
    assert not _is_publishable(normalize_event(extracted(title="  ")))


# ---------- events over several days ----------


@pytest.mark.parametrize(
    ("start", "end", "expected", "doubt"),
    [
        ("2026-11-13", "2026-11-15", "2026-11-15", None),
        ("2026-10-31", "2026-11-02", "2026-11-02", None),  # across months
        ("2026-11-13", "2026-11-19", "2026-11-19", None),  # 7 days: the most
        ("2026-11-13", "2026-11-13", None, None),  # the same day: a one-day event
        ("2026-11-13", None, None, None),
        ("2026-11-13", "15 de noviembre", None, None),
        ("2026-11-15", "2026-11-13", None, "fecha final anterior a la inicial"),
        ("2026-11-13", "2026-11-20", None, "dura más de una semana: revisar fechas"),  # 8 days
        (None, "2026-11-15", None, None),  # no first day: nothing to end
    ],
)
def test_the_last_day_of_an_event_over_several_days(start, end, expected, doubt):
    event = normalize_event(extracted(date=start, end_date=end))
    assert event.end_date == expected
    assert event.doubts == ([doubt] if doubt else [])
