"""The prompts sent to Gemini: they format, and carry the rules the sweep relies on (no network)."""

from pa_bailar.prompts import EXTRACTION_PROMPT, TRIAGE_PROMPT

CONTEXT = {"account": "profe_x", "published": "2026-10-04 Sunday", "today": "2026-10-04 Sunday", "caption": "{x}"}


def test_prompts_format_with_the_post_context():
    assert "@profe_x" in TRIAGE_PROMPT.format(**CONTEXT)
    assert "@profe_x" in EXTRACTION_PROMPT.format(**CONTEXT, known_events="(none)")


def test_events_in_another_city_dont_count_but_no_city_means_bogota():
    # Teachers and artists are followed too, and they travel: their workshops elsewhere aren't Bogotá events.
    for prompt in (TRIAGE_PROMPT, EXTRACTION_PROMPT):
        assert "events in another city or country, when the post says so" in prompt
        assert "With no city stated, the event is in Bogotá." in prompt
