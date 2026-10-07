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


def test_a_post_the_filter_left_out_is_read_once_its_words_name_a_style(monkeypatch):
    """The filter's words grew (the audit of 7 Oct 2026: "salsoteca"): a post it left out before, still in the window,
    is filtered again with the new words and read, without its caption changing. One it still leaves out costs
    nothing."""
    salsoteca, perreo = captioned("s1", "SALSOTECA este viernes 🔥"), captioned("s2", "Perreo hasta abajo")
    instagram = FakeInstagram({"academia": [], "salsabar": [], "club": [salsoteca, perreo]})
    monkeypatch.setattr("pa_bailar.pipeline.sweep.mentions_focus", lambda caption, focus: False)  # the old words
    run(instagram, FakeExtractor({}))
    assert storage.load_processed_posts()["s1"].reason.endswith("(la cuenta es solo para esos estilos)")
    monkeypatch.setattr("pa_bailar.pipeline.sweep.mentions_focus", mentions_focus)  # today's words
    extractor = FakeExtractor({"s1": one_event("s1", "Salsoteca")})
    run(instagram, extractor)
    assert "s1" in extractor.extracted_posts and "s2" not in extractor.rules_seen
    assert [event["title"] for event in read(config.EVENTS_FILE)] == ["Salsoteca"]


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


# ---------- review findings (5 Oct 2026) ----------


def test_an_edited_caption_of_a_post_with_events_is_read_again_even_without_its_styles():
    """A published salsa night whose caption becomes "CANCELADO…": the extraction decides (and can take it down),
    not the free filter, which would leave the event up under a "not an event" record."""
    instagram = FakeInstagram({"academia": [], "salsabar": [], "club": [captioned("c1", "Noche de salsa con La-33")]})
    run(instagram, FakeExtractor({"c1": one_event("c1", "La-33 en vivo")}))
    instagram.posts_by_account["club"] = [captioned("c1", "CANCELADO el concierto de La-33")]
    extractor = FakeExtractor({"c1": PostAnalysis(is_event_post=False, reason="cancelado", events=[])})
    run(instagram, extractor)
    assert "c1" in extractor.extracted_posts  # read again, not filtered
    assert read(config.EVENTS_FILE) == []


def test_a_bar_post_added_by_hand_keeps_being_read_as_it_is():
    """Added by hand while Flash was out (provisional), then upgraded by a sweep: still without the bar's rules, so
    the upgrade can't drop what the owner chose to publish."""
    from pa_bailar.pipeline import Sweep

    night = captioned("b1", "Viernes de salsa con DJ residente")
    instagram = FakeInstagram({"academia": [], "salsabar": [night], "club": []})
    lite = FakeExtractor({"b1": one_event("b1", "Viernes de salsa")}, flash_available=False)
    Sweep(lookback_days=7, instagram=instagram, extractor=lite).add_post(night["permalink"], "salsabar")
    assert storage.load_processed_posts()["b1"].by_hand
    flash = FakeExtractor({"b1": one_event("b1", "Viernes de salsa")})
    run(instagram, flash)
    assert flash.rules_seen["b1"] == ""  # the upgrade read it without BAR_RULES
    assert [event["title"] for event in read(config.EVENTS_FILE)] == ["Viernes de salsa"]


def test_fancy_font_captions_still_name_their_styles():
    assert mentions_focus("𝐍𝐎𝐂𝐇𝐄 𝐃𝐄 𝐒𝐀𝐋𝐒𝐀 🔥", ("salsa",))
    assert mentions_focus("𝗕𝗔𝗖𝗛𝗔𝗧𝗔 sensual", ("bachata",))
    assert mentions_focus("𝓢𝓪𝓵𝓼𝓪 en vivo", ("salsa",))


# ---------- review fixes (2): the real accounts.txt, one source for the style words ----------


def test_the_real_accounts_file_parses(monkeypatch):
    """A typo in a `bar` or `solo:` line fails here, in CI, instead of stopping the sweep."""
    from pathlib import Path

    monkeypatch.setattr(config, "ACCOUNTS_FILE", Path(__file__).parents[1] / "accounts.txt")
    options = storage.read_account_options()
    assert len(options) > 50 and any(option.bar for option in options.values())
    assert len(storage.read_accounts()) == len(set(storage.read_accounts()))  # no account twice


def test_every_word_that_names_a_focus_style_passes_its_filter():
    """The filter and the safeguards (normalize.styles_in_text) share their words: a caption that names a style for one
    names it for the other, so a `solo:salsa` account never drops a post the safeguards would read as salsa."""
    from pa_bailar.account_options import FOCUS_KEYWORDS
    from pa_bailar.normalize import TEXT_STYLE_WORDS, style_family

    for word, style in TEXT_STYLE_WORDS.items():
        if (family := style_family(style)) in FOCUS_KEYWORDS:
            assert mentions_focus(f"Esta noche {word} en vivo", (family,)), word
    old_words = {"salsa": ("salser", "timba", "casino", "son cubano", "pachanga", "boogaloo", "mambo")}
    old_words |= {"bachata": ("bachatero",), "kizomba": ("semba", "urban kiz"), "tango": ("milonga",)}
    for style, words in old_words.items():  # the hand-written list before: still found
        assert all(mentions_focus(word, (style,)) for word in words), style


def test_a_salsa_nights_other_words_pass_the_filter_and_a_reggaeton_night_doesnt():
    """The audit of 7 Oct 2026: these posts were dropped before Gemini at the 9 `solo:` accounts, their events lost."""
    salsa_bachata = ("salsa", "bachata")
    for caption in [
        "SALSOTECA este viernes 🔥",
        "Salsotecas de octubre",
        "Noche Fania con DJ Pacho",
        "Soneros en vivo",
        "Orquesta en vivo desde las 9",
        "Bachazouk night",
        "Rumba salsera hasta el amanecer",
    ]:
        assert mentions_focus(caption, salsa_bachata), caption
    assert mentions_focus("Kiz night con DJ invitado", ("kizomba",))
    assert mentions_focus("Para tangueros y tangueras", ("tango",))
    assert not mentions_focus("Noche de reggaeton y dancehall con DJ", salsa_bachata)
    assert not mentions_focus("Halloween party: disfraces y premios", salsa_bachata)


# ---------- a bar's night is a party ("Rumba"), not a dancers' social (the owner, 6 Oct 2026) ----------


def test_the_party_rule_keeps_socials_announced_as_such_and_other_types():
    from pa_bailar.normalize import party_at_a_bar

    assert party_at_a_bar("social", "Halloween en el bar · DJ invitado") == "party"
    assert party_at_a_bar("social", "Gran SOCIAL de bachata con la academia") == "social"
    assert party_at_a_bar("social", "Sociales de salsa todos invitados") == "social"
    # The word's other uses don't make a bar's night a social (bug-squash, 6 Oct 2026).
    assert party_at_a_bar("social", "Halloween con DJ · síguenos en nuestras redes sociales") == "party"
    assert party_at_a_bar("social", "Noche de Halloween en Sonora Social Club") == "party"
    assert party_at_a_bar("social", "Aniversario del bar por una causa social") == "party"
    assert party_at_a_bar("social", "Social de bachata · síguenos en redes sociales") == "social"
    # Its other names stay socials; more of the word's other uses don't (the audit of 7 Oct 2026).
    assert party_at_a_bar("social", "Milonga de tango con orquesta") == "social"
    assert party_at_a_bar("social", "Práctica libre de salsa") == "social"
    assert party_at_a_bar("social", "Viernes en el Club Social") == "party"
    assert party_at_a_bar("social", "Eventos sociales y empresariales: reserva el bar") == "party"
    assert party_at_a_bar("social", "Síguenos en nuestra red social") == "party"
    assert party_at_a_bar("concert", "Orquesta en vivo") == "concert"
    assert party_at_a_bar("workshop", "Taller con invitado") == "workshop"


def test_a_bars_night_read_as_a_social_is_stored_as_a_party_and_an_academys_stays_a_social():
    instagram = FakeInstagram(
        {
            "academia": [captioned("a1", "Fiesta Neón de la academia")],
            "salsabar": [captioned("b1", "Halloween con DJ"), captioned("b2", "Social de bachata con @academia")],
            "club": [],
        }
    )
    extractor = FakeExtractor(
        {
            "a1": one_event("a1", "Fiesta Neón"),
            "b1": one_event("b1", "Halloween en el bar"),
            "b2": one_event("b2", "Noche de bachata"),
        }
    )
    run(instagram, extractor)
    types = {event["title"]: event["event_type"] for event in read(config.EVENTS_FILE)}
    assert types == {"Fiesta Neón": "social", "Halloween en el bar": "party", "Noche de bachata": "social"}


def test_a_bars_social_stored_before_the_type_existed_becomes_a_party_on_the_next_run():
    from tests.factories import media, stored

    old = [
        stored("halloween", account="salsabar", title="Halloween en el bar", bar=True, posts=[media("h1")]),
        stored("social-bachata", account="salsabar", title="Social de bachata", bar=True, posts=[media("s1")]),
        stored("concierto", account="salsabar", title="Orquesta", event_type="concert", bar=True, posts=[media("c1")]),
        stored("fiesta-neon", account="academia", title="Fiesta Neón", posts=[media("f1")]),
    ]
    storage.save_events(old)
    run(FakeInstagram({"academia": [], "salsabar": [], "club": []}), FakeExtractor({}))
    types = {event["id"]: event["event_type"] for event in read(config.EVENTS_FILE)}
    assert types == {"halloween": "party", "social-bachata": "social", "concierto": "concert", "fiesta-neon": "social"}


def test_the_answer_schemas_tell_a_party_from_a_social_like_the_prompt():
    """Bug-squash, 6 Oct 2026: the schema's description still said "social = socials, parties", against the prompt."""
    from pa_bailar.models import EventDetails, StoryEvent

    for model in (EventDetails, StoryEvent):
        description = model.model_fields["event_type"].description or ""
        assert "party = " in description and "social = socials, parties" not in description
