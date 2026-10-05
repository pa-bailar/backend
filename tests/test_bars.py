"""Bars and accounts limited to some styles (accounts.txt `bar`, `solo:…`, account_options): the line's syntax, the
free caption filter before Gemini, the prompts' extra rules, the events' `bar` tag and a bar's first sweep. No
network."""

import pytest

from pa_bailar import config, storage
from pa_bailar.account_options import AccountOptions, mentions_focus, parse_line
from pa_bailar.models import PostAnalysis
from pa_bailar.prompts import BAR_RULES, EXTRACTION_PROMPT, TRIAGE_PROMPT, account_rules
from tests.factories import extracted, make_image
from tests.test_prompts import CONTEXT
from tests.test_sweep import FakeExtractor, FakeInstagram, post, read, run


@pytest.fixture(autouse=True)
def bars_and_images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text(
        "academia\n# Salsa bars\nsalsabar    bar\nclub   bar solo:salsa,bachata\n", encoding="utf-8"
    )
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


def captioned(post_id: str, caption: str) -> dict:
    return {**post(post_id), "caption": caption}


def one_event(post_id: str, title: str = "Aniversario") -> PostAnalysis:
    return PostAnalysis(is_event_post=True, reason="", events=[extracted(title=title)])


# ---------- accounts.txt ----------


def test_a_line_is_the_name_then_bar_and_its_styles():
    assert parse_line("galeriacafelibro") == ("galeriacafelibro", AccountOptions())
    assert parse_line("@salsabar   bar") == ("salsabar", AccountOptions(bar=True))
    assert parse_line("club bar solo:salsa,bachata") == ("club", AccountOptions(bar=True, focus=("salsa", "bachata")))
    assert parse_line("# a comment") is None and parse_line("   ") is None
    assert parse_line("salsabar  bar   # salsa bar, live music") == ("salsabar", AccountOptions(bar=True))
    assert storage.read_accounts() == ["academia", "salsabar", "club"]  # names only, as before


@pytest.mark.parametrize("line", ["club barr", "club solo:reggaeton", "club solo:"])
def test_a_typo_fails_loudly_instead_of_sweeping_without_limits(line):
    with pytest.raises(ValueError, match="accounts.txt, @club"):
        parse_line(line)


def test_the_caption_filter_ignores_accents_and_case():
    assert mentions_focus("Noche de BACHATÁ sensual", ("salsa", "bachata"))
    assert mentions_focus("Viernes salsero con orquesta", ("salsa", "bachata"))
    assert not mentions_focus("Perreo hasta el amanecer 🔥", ("salsa", "bachata"))
    assert not mentions_focus(None, ("salsa",))
    assert mentions_focus(None, ())  # no focus: every post goes on


# ---------- the prompts ----------


def test_only_marked_accounts_get_extra_rules_and_others_keep_the_same_prompt():
    assert account_rules(False, ()) == ""
    assert "BAR or club" not in TRIAGE_PROMPT.format(**CONTEXT)
    bar = account_rules(True, ())
    assert "BAR or club" in bar and "regular nights are NOT events" in bar
    both = account_rules(True, ("salsa", "bachata"))
    assert both.startswith(BAR_RULES) and "Only events for dancing salsa or bachata count" in both
    for prompt in (
        TRIAGE_PROMPT.format(**{**CONTEXT, "account_rules": both}),
        EXTRACTION_PROMPT.format(**{**CONTEXT, "account_rules": both}, known_events="(none)"),
    ):
        assert "BAR or club" in prompt and "salsa or bachata" in prompt


# ---------- the sweep ----------


def test_a_limited_accounts_post_without_its_styles_never_reaches_gemini():
    perreo, salsa = captioned("p1", "Perreo hasta abajo este viernes"), captioned("p2", "Noche de salsa con orquesta")
    extractor = FakeExtractor({"p2": one_event("p2", "Orquesta en vivo")})
    run(FakeInstagram({"academia": [], "salsabar": [], "club": [perreo, salsa]}), extractor)
    assert "p1" not in extractor.rules_seen  # no triage, no extraction
    record = storage.load_processed_posts()["p1"]
    assert record.outcome == "not_event" and record.model == "-" and "salsa ni bachata" in record.reason
    assert "BAR or club" in extractor.rules_seen["p2"] and "salsa or bachata" in extractor.rules_seen["p2"]


def test_bar_events_are_tagged_and_other_accounts_get_the_usual_prompt():
    instagram = FakeInstagram(
        {"academia": [captioned("a1", "Taller")], "salsabar": [captioned("b1", "Aniversario")], "club": []}
    )
    extractor = FakeExtractor({"a1": one_event("a1", "Taller de salsa"), "b1": one_event("b1", "Aniversario del bar")})
    run(instagram, extractor)
    assert extractor.rules_seen["a1"] == ""
    events = {event["title"]: event for event in read(config.EVENTS_FILE)}
    assert events["Aniversario del bar"]["bar"] is True and events["Taller de salsa"]["bar"] is False


def test_marking_an_account_as_a_bar_later_tags_its_stored_events():
    run(
        FakeInstagram({"academia": [captioned("a1", "Taller")], "salsabar": [], "club": []}),
        FakeExtractor({"a1": one_event("a1", "Taller de salsa")}),
    )
    config.ACCOUNTS_FILE.write_text("academia bar\n", encoding="utf-8")
    run(FakeInstagram({"academia": []}), FakeExtractor({}))
    assert [event["bar"] for event in read(config.EVENTS_FILE)] == [True]


def test_a_bars_first_sweep_is_a_regular_one():
    instagram = FakeInstagram({"academia": [], "salsabar": [], "club": []})
    run(instagram, FakeExtractor({}))
    assert instagram.limits["academia"] == [config.BACKFILL_POSTS]  # a new academy: the deeper first sweep
    assert instagram.limits["salsabar"] == [config.POSTS_PER_ACCOUNT]  # a bar: its old posts are past nights
    assert storage.load_account_state()["salsabar"].backfill_done
