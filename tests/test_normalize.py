"""Gemini output is cleaned before it is stored, because the frontend relies on these formats."""

import pytest

from pa_bailar.models import Price
from pa_bailar.normalize import normalize_event, normalize_style, normalize_styles, parse_iso_date, parse_time
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
