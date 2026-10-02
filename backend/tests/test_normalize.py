"""Gemini output is cleaned before it is stored, because the frontend relies on these formats."""

import pytest

from pabailar.models import Price
from pabailar.normalize import normalize_event, normalize_styles, parse_iso_date, parse_time
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


def test_styles_are_lowercase_trimmed_and_unique():
    assert normalize_styles(["Salsa", " salsa ", "Salsa  Caleña", "", "bachata"]) == [
        "salsa",
        "salsa caleña",
        "bachata",
    ]


def test_invalid_start_time_is_dropped_and_noted_as_a_doubt():
    event = normalize_event(extracted(start_time="9pm"))
    assert event.start_time is None
    assert any("9pm" in doubt for doubt in event.doubts)


def test_invalid_date_becomes_none_so_the_event_is_not_published():
    assert normalize_event(extracted(date="sábado")).date is None


def test_negative_prices_are_removed():
    prices = [Price(label="General", amount_cop=20000), Price(label="Error", amount_cop=-1)]
    assert [p.label for p in normalize_event(extracted(prices=prices)).prices] == ["General"]
