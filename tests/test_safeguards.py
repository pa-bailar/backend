"""Safeguards for readings by a lighter model (Oct 2026 measurement: Flash-Lite against Flash on every post Flash
had read): styles filled in from the text or the account when they come back empty, and a review doubt on posts
with several events read only by a lighter model. No network."""

import pytest

from pa_bailar import config, health
from pa_bailar.models import PostAnalysis, StoredEvent
from pa_bailar.normalize import MULTI_DOUBT, styles_in_text
from tests.factories import extracted, make_image
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


def test_lite_only_mode_marks_them_too(monkeypatch):
    monkeypatch.setattr(config, "LITE_ONLY", True)
    run(FakeInstagram({"academia": [post("p1")]}), FakeExtractor({"p1": two_events()}))
    assert all(MULTI_DOUBT in event["doubts"] for event in read(config.EVENTS_FILE))
