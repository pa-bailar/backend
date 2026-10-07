"""Safeguards for readings by a lighter model (Oct 2026 measurement: Flash-Lite against Flash on every post Flash
had read): styles filled in from the text or the account when they come back empty, and a review doubt on posts
with several events read only by a lighter model. No network."""

import pytest

from pa_bailar import config, health
from pa_bailar.merging import merge_into
from pa_bailar.models import PostAnalysis, StoredEvent
from pa_bailar.normalize import GUESSED_STYLES_DOUBT, MULTI_DOUBT, normalize_style, styles_in_text
from tests.factories import extracted, make_image, media, stored
from tests.test_sweep import FakeExtractor, FakeInstagram, post, read, run


@pytest.fixture(autouse=True)
def images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text("academia\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


def test_styles_named_in_a_text():
    assert styles_in_text("Noche de SALSA y bachata 🔥") == ["salsa", "bachata"]
    assert styles_in_text("Taller de salsa en línea (on2)") == ["salsa en línea"]
    assert styles_in_text("𝐊𝐈𝐙𝐎𝐌𝐁𝐀 social") == ["kizomba"]
    assert styles_in_text("Ellos son los mejores, la fiesta del año") == []  # "son", "la": plain words


def captioned(post_id: str, caption: str, days_ago: float = 2) -> dict:
    return {**post(post_id, days_ago=days_ago), "caption": caption}


def test_an_event_without_styles_gets_the_ones_its_caption_names():
    p1 = captioned("p1", "Gran social de bachata este sábado")
    run(
        FakeInstagram({"academia": [p1]}),
        FakeExtractor(
            {"p1": PostAnalysis(is_event_post=True, reason="", events=[extracted(title="Gran social", styles=[])])}
        ),
    )
    assert read(config.EVENTS_FILE)[0]["styles"] == ["bachata"]


def test_otherwise_the_accounts_usual_style_and_never_over_the_models_own():
    posts = [captioned(f"p{i}", "Social", days_ago=5 - i) for i in range(4)]
    analyses = {
        f"p{i}": PostAnalysis(
            is_event_post=True,
            reason="",
            events=[
                extracted(title=f"Social {i}", date=f"2027-01-0{i + 1}", styles=["bachata sensual"] if i < 3 else [])
            ],
        )
        for i in range(4)
    }
    run(FakeInstagram({"academia": posts}), FakeExtractor(analyses))
    styles = {event["title"]: event["styles"] for event in read(config.EVENTS_FILE)}
    assert styles["Social 3"] == ["bachata sensual"]  # the account's usual one (3 of 3)
    assert styles["Social 0"] == ["bachata sensual"]  # the model's own, untouched


def two_events() -> PostAnalysis:
    return PostAnalysis(
        is_event_post=True,
        reason="",
        events=[
            extracted(title="Taller A", start_time="15:00", styles=["salsa"]),
            extracted(title="Taller B", start_time="16:00", styles=["salsa"]),
        ],
    )


def test_several_events_read_by_a_lighter_model_are_listed_for_review():
    run(FakeInstagram({"academia": [post("p1")]}), FakeExtractor({"p1": two_events()}, flash_available=False))
    events = [StoredEvent(**event) for event in read(config.EVENTS_FILE)]
    assert all(MULTI_DOUBT in event.doubts for event in events)
    assert all(MULTI_DOUBT in health.review_reasons(event) for event in events)


def test_flash_reading_several_events_adds_no_doubt_and_its_upgrade_clears_it():
    instagram = FakeInstagram({"academia": [post("p1")]})
    run(instagram, FakeExtractor({"p1": two_events()}, flash_available=False))
    run(instagram, FakeExtractor({"p1": two_events()}))  # the provisional reading upgraded with Flash
    assert all(MULTI_DOUBT not in event["doubts"] for event in read(config.EVENTS_FILE))


def test_flash_reading_an_event_another_post_shares_clears_the_doubt_too():
    """Review finding: a reminder merged into one of the events kept the doubt after Flash re-read both posts."""
    p1, p2 = post("p1", days_ago=3), post("p2", days_ago=1)  # p2: a reminder of Taller A
    reminder = PostAnalysis(is_event_post=True, reason="", events=[extracted(title="Taller A", start_time="15:00")])
    instagram = FakeInstagram({"academia": [p1, p2]})
    run(instagram, FakeExtractor({"p1": two_events(), "p2": reminder}, flash_available=False))
    assert all(MULTI_DOUBT in event["doubts"] for event in read(config.EVENTS_FILE))
    run(instagram, FakeExtractor({"p1": two_events(), "p2": reminder}))  # both upgraded with Flash
    events = read(config.EVENTS_FILE)
    assert len(events) == 2 and all(MULTI_DOUBT not in event["doubts"] for event in events)


def test_a_lighter_reading_merged_in_keeps_the_doubt():
    p1, p2 = post("p1", days_ago=3), post("p2", days_ago=1)
    reminder = PostAnalysis(is_event_post=True, reason="", events=[extracted(title="Taller A", start_time="15:00")])
    run(
        FakeInstagram({"academia": [p1, p2]}),
        FakeExtractor({"p1": two_events(), "p2": reminder}, flash_available=False),
    )
    taller_a = next(event for event in read(config.EVENTS_FILE) if event["title"] == "Taller A")
    assert len(taller_a["media"]) == 2 and MULTI_DOUBT in taller_a["doubts"]


def test_guessed_styles_are_marked_and_give_way_to_a_reading_of_them():
    flyer = captioned("flyer", "Social de bachata y salsa", days_ago=3)
    video = captioned("video", "Nos vemos", days_ago=1)
    analyses = {
        "flyer": PostAnalysis(is_event_post=True, reason="", events=[extracted(title="Social", styles=[])]),
        "video": PostAnalysis(is_event_post=True, reason="", events=[extracted(title="Social", styles=["kizomba"])]),
    }
    instagram = FakeInstagram({"academia": [flyer]})
    run(instagram, FakeExtractor(analyses))
    [event] = read(config.EVENTS_FILE)
    assert event["styles"] == ["bachata", "salsa"] and GUESSED_STYLES_DOUBT in event["doubts"]

    instagram.posts_by_account["academia"] = [flyer, video]  # a later post whose reading gives the styles
    run(instagram, FakeExtractor(analyses))
    [event] = read(config.EVENTS_FILE)
    assert event["styles"] == ["kizomba"] and GUESSED_STYLES_DOUBT not in event["doubts"]


def test_read_styles_never_give_way_to_guessed_ones():
    stored_event = stored(styles=["salsa"])
    guessed = extracted(styles=["bachata"], doubts=[GUESSED_STYLES_DOUBT])
    merged = merge_into(stored_event, guessed, media("p2", published="2026-10-05T12:00:00+0000"))
    assert merged.styles == ["salsa"] and GUESSED_STYLES_DOUBT not in merged.doubts


def test_guessed_styles_dont_make_an_accounts_usual_style():
    posts = [captioned(f"p{i}", "Social de bachata", days_ago=5 - i) for i in range(4)]
    analyses = {
        f"p{i}": PostAnalysis(
            is_event_post=True, reason="", events=[extracted(title=f"Social {i}", date=f"2027-01-0{i + 1}", styles=[])]
        )
        for i in range(4)
    }
    posts[3]["caption"] = "Social"
    run(FakeInstagram({"academia": posts}), FakeExtractor(analyses))
    styles = {event["title"]: event["styles"] for event in read(config.EVENTS_FILE)}
    assert styles["Social 3"] == []  # three guessed "bachata" don't make it the account's usual style


@pytest.mark.parametrize(
    "text",
    [
        "La mejor rumba de Bogotá",
        "Con la orquesta Swing Latino",
        "Este viernes en Mambo Cafe",
        "Noche en el Casino Royal",
        "Street food y transporte urbano gratis",
        "Viene la caleña más bailadora",
        "Ron cubano y timba de la buena",
        "¡Qué pachanga la de anoche!",
    ],
)
def test_words_captions_use_otherwise_name_no_style(text):
    assert styles_in_text(text) == []


def test_the_phrases_that_do_name_those_styles():
    assert styles_in_text("Clase de baile urbano y hip hop") == ["urbano"]
    assert styles_in_text("Danzas urbanas, reggaeton y dancehall") == ["urbano", "dancehall"]
    assert styles_in_text("Rueda de casino y rumba cubana") == ["salsa cubana", "afro"]
    assert styles_in_text("Salsa estilo caleño") == ["salsa caleña"]
    assert styles_in_text("West coast swing social") == ["swing"]
    assert styles_in_text("Noche de boogaloo y salsa brava") == ["salsa"]
    assert styles_in_text("Salsa dura, salsa choke y bugalú") == ["salsa"]
    assert styles_in_text("Taller de salsa estilo cubano") == ["salsa cubana"]


def test_the_words_around_a_style_name_it_too():
    """A caption's words for the style instead of its name (the audit of 7 Oct 2026: these named none)."""
    assert styles_in_text("La mejor rumba salsera de Bogotá") == ["salsa"]  # a salsa party: "rumba" isn't afro here
    assert styles_in_text("SALSOTECA con DJ y homenaje a la Fania") == ["salsa"]
    assert styles_in_text("Clase para bachateros y bachateras") == ["bachata"]
    assert styles_in_text("Taller de Salsa On 2") == ["salsa en línea"]
    assert styles_in_text("Noche de salsa estilo Cali") == ["salsa caleña"]
    assert styles_in_text("Perreo, dembow y afrobeats") == ["urbano", "afro"]
    assert styles_in_text("Milonga del sábado con orquesta típica") == ["tango"]
    assert styles_in_text("Kiz night: semba y tarraxinha") == ["kizomba"]
    assert styles_in_text("Ellos son los mejores") == []  # still a plain word


@pytest.mark.parametrize(
    ("name", "style"),
    [
        ("pachanga", "salsa"),
        ("boogaloo", "salsa"),
        ("bugalú", "salsa"),
        ("Salsa Brava", "salsa"),
        ("salsa dura", "salsa"),
        ("salsa choke", "salsa"),
        ("cubano", "salsa cubana"),
        ("estilo cubano", "salsa cubana"),
        ("salsa estilo cubano", "salsa cubana"),
        ("son cubano", "son"),
        ("guaguancó", "afro"),
        ("rumba cubana", "afro"),
    ],
)
def test_salsas_other_names_map_to_its_family(name, style):
    """The owner, 5 Oct 2026: a model answering one of these gets the salsa family, not "otro"."""
    assert normalize_style(name) == style


def multi(caption: str, *titles: str) -> dict[str, str]:
    """The styles each event of a post with several events, all without styles, gets from `caption`."""
    events = [extracted(title=title, start_time=f"1{n}:00", styles=[]) for n, title in enumerate(titles)]
    run(
        FakeInstagram({"academia": [captioned("p1", caption)]}),
        FakeExtractor({"p1": PostAnalysis(is_event_post=True, reason="", events=events)}),
    )
    return {event["title"]: event["styles"] for event in read(config.EVENTS_FILE)}


def test_several_events_take_their_own_titles_styles_first():
    styles = multi("Este sábado: salsa y bachata", "Taller de bachata sensual", "Taller de salsa", "Social")
    assert styles == {"Taller de bachata sensual": ["bachata sensual"], "Taller de salsa": ["salsa"], "Social": []}


def test_several_events_take_the_captions_styles_only_when_it_names_one_family():
    styles = multi("Salsa en línea y salsa caleña este sábado", "Taller A", "Taller B")
    assert styles == {"Taller A": ["salsa en línea", "salsa caleña"], "Taller B": ["salsa en línea", "salsa caleña"]}


def test_lite_only_mode_marks_them_too(monkeypatch):
    monkeypatch.setattr(config, "LITE_ONLY", True)
    run(FakeInstagram({"academia": [post("p1")]}), FakeExtractor({"p1": two_events()}))
    assert all(MULTI_DOUBT in event["doubts"] for event in read(config.EVENTS_FILE))
