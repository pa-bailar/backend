"""Readable event ids (the events' URLs)."""

from pa_bailar.ids import MAX_TITLE_LENGTH, new_event_id, slugify


def test_slug_is_lowercase_ascii_words():
    assert slugify("¡Social de HALLOWEEN! · Bachata & Salsa Caleña") == "social-de-halloween-bachata-salsa-calena"


def test_id_is_title_then_day_and_month():
    assert new_event_id("Salsa Freestyle con Renato Palacios", "2026-10-03", set()) == (
        "salsa-freestyle-con-renato-palacios-3-oct"
    )


def test_taken_ids_get_a_number():
    taken = {"social-24-oct", "social-24-oct-2"}
    assert new_event_id("Social", "2026-10-24", taken) == "social-24-oct-3"


def test_long_titles_are_cut_at_a_word():
    title = "Gran aniversario de la academia con invitados internacionales y orquesta en vivo"
    event_id = new_event_id(title, "2026-12-05", set())
    assert event_id.endswith("-5-dic")
    title_part = event_id.removesuffix("-5-dic")
    assert len(title_part) <= MAX_TITLE_LENGTH and title.lower().startswith(title_part.replace("-", " "))


def test_title_without_letters_still_gets_an_id():
    assert new_event_id("🔥🔥", "2026-01-09", set()) == "9-ene"
