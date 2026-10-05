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


def test_only_concerts_and_festivals_for_partner_dancing_count():
    # Oct 2026: a concert promoter's EDM festival and pop concerts came out as events.
    for prompt in (TRIAGE_PROMPT, EXTRACTION_PROMPT):
        assert "concerts and music festivals that aren't for social or partner dancing" in prompt
        assert "electronic (EDM, techno, house)" in prompt
        assert "A concert or festival counts only when it's for social or partner dancing" in prompt
        assert "a salsa orchestra's concert, or a dance festival with socials and" in prompt  # these still count


def test_a_post_that_only_mentions_an_event_in_passing_doesnt_announce_it():
    # Review finding: a song release mentioning a concert was linked to it (same_as) and moved its date.
    for prompt in (TRIAGE_PROMPT, EXTRACTION_PROMPT):
        assert "only mentions an event in passing" in prompt
    assert "never link (same_as) a post that only" in EXTRACTION_PROMPT
