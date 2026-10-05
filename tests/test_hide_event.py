"""Hiding an event by hand ("Ocultar", Sweep.hide_event), whatever it came from, and the "Series nuevas" list that
offers it (status.new_series): the inbox, the sweep with fakes, the status. No network."""

from datetime import datetime, timedelta
from urllib.parse import quote

import pytest

from pa_bailar import config, inbox, status, storage, why
from pa_bailar.commands.admin import answer
from pa_bailar.commands.answers import hidden_event_markdown
from pa_bailar.models import PostAnalysis
from pa_bailar.pipeline import AddPostError, Sweep
from tests.factories import EVENT_DATE, event_id, extracted, make_image
from tests.test_series import DAYS, series, sessions
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post, read, run

SERIES_TITLE = "Programa intensivo"
SERIES_ID = event_id(SERIES_TITLE)


@pytest.fixture(autouse=True)
def accounts_and_images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    monkeypatch.setattr(config, "PRIVATE_DIR", isolated_files / "private")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


def series_post(post_id: str):
    return event_post(post_id, title=SERIES_TITLE, event_type="workshop", sessions=sessions())


def sweep_with(posts: list[dict], analyses: dict) -> Sweep:
    return Sweep(
        lookback_days=7, instagram=FakeInstagram({"academia": posts, "otra": []}), extractor=FakeExtractor(analyses)
    )


# ---------- the inbox ----------


@pytest.mark.parametrize(
    ("text", "event"),
    [
        ("/ocultar programa-intensivo-8-nov", "programa-intensivo-8-nov"),
        ("/ocultar https://pa-bailar.github.io/evento/programa-intensivo-8-nov/", "programa-intensivo-8-nov"),
        ("### Acción\n\nOcultar evento\n\n### Evento\n\nsocial-24-oct\n\n_Desde la página._", "social-24-oct"),
    ],
)
def test_the_inbox_reads_hide_event(text, event):
    request = inbox.parse(text)
    assert (request.action, request.event) == ("hide-event", event)
    reply, done = answer(request)
    assert event in reply and not done  # the sweep workflow does it


def test_the_inbox_still_reads_hide_story_and_refuses_what_isnt_an_id():
    assert inbox.parse("/ocultar story-0123456789abcdef").action == "hide-story"
    assert inbox.parse("/ocultar Programa Intensivo").action == "help"
    assert inbox.parse("/ocultar").action == "help"
    assert inbox.parse("### Acción\n\nOcultar evento\n\n### Evento\n\n_No response_").action == "help"


# ---------- the sweep: hidden, and never published again from the same posts ----------


def test_hiding_a_series_from_a_post_takes_it_off_and_later_sweeps_leave_it_off():
    p1 = post("p1", days_ago=3)
    run(FakeInstagram({"academia": [p1], "otra": []}), FakeExtractor({"p1": series_post("p1")}))
    assert [event["id"] for event in read(config.EVENTS_FILE)] == [SERIES_ID]

    hidden = sweep_with([p1], {}).hide_event(SERIES_ID)
    assert read(config.EVENTS_FILE) == [] and not list(config.FLYERS_DIR.glob("*.webp"))
    assert storage.load_processed_posts()["p1"].outcome == "hidden"
    assert SERIES_ID in storage.load_hidden_events()
    assert "Quité del sitio" in hidden_event_markdown(hidden) and "4 sesiones" in hidden_event_markdown(hidden)
    assert sweep_with([p1], {}).hide_event(SERIES_ID).already

    # Next sweep: the caption was edited (read again), a reminder of one session, and a genuinely new event.
    p1["caption"] = "caption editado"
    reminder = post("p2", days_ago=2)
    new = post("p3", days_ago=1)
    analyses = {
        "p1": series_post("p1"),
        "p2": event_post("p2", title="Intensivo: sesión 3", date=DAYS[2], start_time="14:00"),
        "p3": event_post("p3", title="Social de Halloween", date=EVENT_DATE, start_time="21:00"),
    }
    run(FakeInstagram({"academia": [p1, reminder, new], "otra": []}), FakeExtractor(analyses))
    assert [event["title"] for event in read(config.EVENTS_FILE)] == ["Social de Halloween"]
    processed = storage.load_processed_posts()
    assert processed["p1"].outcome == "hidden" and processed["p2"].outcome == "hidden"
    assert processed["p3"].outcome == "event"


def test_hiding_one_event_of_a_post_keeps_its_sibling_on_the_same_day_when_the_post_is_read_again():
    """A post with a workshop at 16:00 and a social at 21:00 the same day: hiding the workshop leaves the social, also
    when the post is read again (an edited caption) (review finding)."""
    p1 = post("p1", days_ago=3)
    two_events = PostAnalysis(
        is_event_post=True,
        reason="",
        events=[
            extracted(title="Taller de bachata", event_type="workshop", start_time="16:00"),
            extracted(title="Social de bachata", start_time="21:00"),
        ],
    )
    run(FakeInstagram({"academia": [p1], "otra": []}), FakeExtractor({"p1": two_events}))
    taller, social = event_id("Taller de bachata"), event_id("Social de bachata")
    sweep_with([p1], {}).hide_event(taller)
    assert storage.load_processed_posts()["p1"].event_ids == [social]

    edited = {**p1, "caption": "caption editado"}
    run(FakeInstagram({"academia": [edited], "otra": []}), FakeExtractor({"p1": two_events}))
    assert [event["id"] for event in read(config.EVENTS_FILE)] == [social]
    assert taller in storage.load_hidden_events()
    reworded = PostAnalysis(  # read again: the workshop reworded, at its time, is still the hidden one
        is_event_post=True,
        reason="",
        events=[extracted(title="Taller", event_type="workshop", start_time="16:00"), *two_events.events[1:]],
    )
    run(FakeInstagram({"academia": [{**p1, "caption": "otra vez"}], "otra": []}), FakeExtractor({"p1": reworded}))
    assert [event["id"] for event in read(config.EVENTS_FILE)] == [social]


def test_adding_one_of_its_posts_by_hand_publishes_it_again_with_its_id():
    p1 = post("p1", days_ago=3)
    run(FakeInstagram({"academia": [p1], "otra": []}), FakeExtractor({"p1": series_post("p1")}))
    sweep_with([p1], {}).hide_event(SERIES_ID)
    added = sweep_with([p1], {"p1": series_post("p1")}).add_post("https://www.instagram.com/p/p1/", "academia")
    assert added.outcome == "event" and [event.id for event in added.events] == [SERIES_ID]
    assert storage.load_hidden_events() == {}


def test_adding_an_unchanged_post_by_hand_brings_back_its_hidden_event_and_keeps_its_sibling():
    """Undoing an "Ocultar" by mistake: the post still announces another event (so its record says "event") and its
    caption is the same, yet Agregar reads it again so the hidden one comes back."""
    p1 = post("p1", days_ago=3)
    two_events = PostAnalysis(
        is_event_post=True,
        reason="",
        events=[
            extracted(title="Taller de bachata", event_type="workshop", start_time="16:00"),
            extracted(title="Social de bachata", start_time="21:00"),
        ],
    )
    run(FakeInstagram({"academia": [p1], "otra": []}), FakeExtractor({"p1": two_events}))
    taller, social = event_id("Taller de bachata"), event_id("Social de bachata")
    sweep_with([p1], {}).hide_event(taller)
    assert storage.load_processed_posts()["p1"].outcome == "event"

    added = sweep_with([p1], {"p1": two_events}).add_post("https://www.instagram.com/p/p1/", "academia")
    assert sorted(event.id for event in added.events) == sorted([taller, social])
    assert sorted(event["id"] for event in read(config.EVENTS_FILE)) == sorted([taller, social])
    assert storage.load_hidden_events() == {}
    # Nothing hidden any more: the same post again isn't read again.
    again = sweep_with([p1], {}).add_post("https://www.instagram.com/p/p1/", "academia")
    assert again.unchanged


def test_the_answer_links_each_post_to_publish_it_again_and_says_how_for_a_story():
    p1 = post("p1", days_ago=3)
    run(FakeInstagram({"academia": [p1], "otra": []}), FakeExtractor({"p1": series_post("p1")}))
    hidden = sweep_with([p1], {}).hide_event(SERIES_ID)
    answer_text = hidden_event_markdown(hidden)
    permalink = hidden.event.media[0].permalink
    assert f"[Publicación]({permalink})" in answer_text
    assert f"{config.ADMIN_URL}/?url={quote(permalink, safe='')}" in answer_text
    assert "historia" not in answer_text
    assert "\n\n**¿Fue por error?**" in answer_text  # its own paragraph
    assert "Volver a publicarla" in hidden_event_markdown(sweep_with([p1], {}).hide_event(SERIES_ID))  # already

    story = hidden.event.media[0].model_copy(update={"media_type": "STORY", "post_id": "story-1"})
    from_story = hidden.event.model_copy(update={"media": [story]})
    text = hidden_event_markdown(type(hidden)(from_story))
    assert "comparte otra vez sus capturas" in text and "Volver a publicarla" not in text


def test_a_hidden_event_stays_off_even_if_the_data_pr_that_hid_it_never_merged():
    storage.save_events([series(SERIES_ID)])
    sweep_with([], {}).hide_event(SERIES_ID)
    storage.save_events([series(SERIES_ID)])  # the site's data, still with it
    Sweep(lookback_days=7, instagram=FakeInstagram({"academia": [], "otra": []}), extractor=FakeExtractor({})).run()
    assert read(config.EVENTS_FILE) == []


def test_another_events_post_keeps_its_other_events_and_hidden_ones_are_forgotten_when_long_past():
    storage.save_events([series(SERIES_ID), series("otro", days=DAYS[1:3], title="Taller de heels")])
    sweep_with([], {}).hide_event(SERIES_ID)
    assert [event.id for event in storage.load_events()] == ["otro"]
    with pytest.raises(AddPostError, match="No encontré el evento"):
        sweep_with([], {}).hide_event("no-existe")
    hidden = storage.load_hidden_events()
    long_ago = (config.now_bogota().date() - timedelta(days=config.EVENT_RETENTION_DAYS + 5)).isoformat()
    hidden[SERIES_ID].event = hidden[SERIES_ID].event.model_copy(
        update={"date": long_ago, "end_date": None, "sessions": None}
    )
    storage.save_hidden_events(hidden)
    Sweep(lookback_days=7, instagram=FakeInstagram({"academia": [], "otra": []}), extractor=FakeExtractor({})).run()
    assert storage.load_hidden_events() == {}


def test_why_says_a_hidden_post_was_taken_off_by_hand():
    record = {
        "account": "academia",
        "permalink": "https://www.instagram.com/p/p1/",
        "processed_at": "2026-10-02T21:05:00-05:00",
        "is_event_post": True,
        "reason": "",
        "model": "x",
        "outcome": "hidden",
    }
    files = {"processed_posts.json": {"p1": record}}
    result = why.diagnose("https://www.instagram.com/p/p1/", read=lambda name, default: files.get(name, default))
    assert result.verdict.startswith("No está en el sitio a propósito") and result.suggestion == "add-post"


# ---------- "Series nuevas" in the status ----------

NOW = config.now_bogota()


def processed_at(days_ago: float, *event_ids: str) -> dict:
    return {
        "account": "academia",
        "permalink": "https://www.instagram.com/p/x/",
        "processed_at": (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds"),
        "is_event_post": True,
        "reason": "",
        "model": "x",
        "outcome": "event",
        "event_ids": list(event_ids),
    }


def collect(processed: dict) -> dict:
    files = {"processed_posts.json": processed}
    return status.collect(now=NOW, instagram=None, read=lambda name, default: files.get(name, default))


def test_new_series_are_listed_for_two_weeks_with_what_hiding_needs():
    from tests.factories import media

    recent = series("reciente", posts=[media("a"), media("story-0123456789abcdef", media_type="STORY")])
    recent.media[1].permalink = "https://www.instagram.com/academia/"
    older = series("antigua", title="Ciclo de tango")
    one_day = series("social").model_copy(update={"sessions": None, "end_date": None})  # not a series
    past_days = [(NOW.date() - timedelta(days=offset)).isoformat() for offset in (10, 3)]
    over = series("terminada", days=past_days)
    storage.save_events([recent, older, one_day, over])
    result = collect(
        {
            "a": processed_at(2, "reciente", "social"),
            "b": processed_at(config.NEW_SERIES_DAYS + 1, "antigua"),
            "c": processed_at(1, "terminada"),
        }
    )
    [item] = result["new_series"]
    assert item["id"] == "reciente" and item["account"] == "academia"
    assert item["sessions"].startswith("4 sesiones: ")
    assert item["url"] == f"{config.SITE_URL}/evento/reciente/"
    assert [source["kind"] for source in item["sources"]] == ["post", "story"]
    text = status.markdown(result)
    assert "### Series nuevas (revisar)" in text
    assert "`/ocultar reciente`" in text and "`@academia`" in text  # no GitHub mention
    assert "[historia](https://www.instagram.com/academia/)" in text


def test_without_new_series_the_status_says_nothing_about_them():
    storage.save_events([series("antigua")])
    result = collect({"b": processed_at(30, "antigua")})
    assert result["new_series"] == [] and "Series nuevas" not in status.markdown(result)


def test_a_series_whose_records_were_forgotten_goes_by_its_posts_date():
    from tests.factories import media

    published = (NOW - timedelta(days=1)).astimezone(config.BOGOTA_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")
    storage.save_events([series("sin-registro", posts=[media("z", published=published)])])
    assert [item["id"] for item in collect({})["new_series"]] == ["sin-registro"]
    assert datetime.fromisoformat(collect({})["new_series"][0]["first_published"]) <= NOW
