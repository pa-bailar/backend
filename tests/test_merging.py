"""The same event announced by several posts (flyer, video, reminder) becomes one event."""

from pa_bailar import storage
from pa_bailar.merging import detach_post, find_existing, looks_like_same_event, merge_into, ordered_media
from tests.factories import extracted, media, stored

# ---------- matching ----------


def test_gemini_link_wins_even_when_details_differ():
    event = stored("flyer-0", title="Social Espacio Seguro", start_time="20:00")
    candidate = extracted(same_as="flyer-0", title="Ven y baila este sábado", start_time=None, date="2026-10-11")
    assert find_existing([event], "academia", candidate, "new-post") is event


def test_gemini_link_to_another_account_is_ignored():
    event = stored("flyer-0", account="otra")
    assert find_existing([event], "academia", extracted(same_as="flyer-0", date="2026-12-01"), "new-post") is None


def test_events_from_the_same_post_never_merge():
    """A schedule can list two different events on the same day and time."""
    first = stored("p1-0", start_time="20:00", posts=[media("p1")])
    assert find_existing([first], "academia", extracted(start_time="20:00", title="Otro"), "p1") is None
    assert find_existing([first], "academia", extracted(same_as="p1-0"), "p1") is None


def test_rules_match_same_account_date_and_time():
    event = stored(start_time="20:00")
    assert looks_like_same_event(event, "academia", extracted(start_time="20:00", title="Otro título"))
    assert not looks_like_same_event(event, "academia", extracted(start_time="18:00"))
    assert not looks_like_same_event(event, "academia", extracted(start_time="20:00", date="2026-10-11"))
    assert not looks_like_same_event(event, "otra", extracted(start_time="20:00"))


def test_rules_compare_titles_when_a_time_is_missing():
    event = stored(title="Social Halloween")
    assert looks_like_same_event(event, "academia", extracted(title="social  halloween"))
    assert not looks_like_same_event(event, "academia", extracted(title="Taller de Heels"))


def test_unrelated_event_is_new():
    assert find_existing([stored()], "academia", extracted(date="2026-11-01"), "new-post") is None


# ---------- merging ----------


def test_merge_adds_the_post_and_puts_images_before_videos():
    event = stored(posts=[media("video", "VIDEO", "2026-09-28T10:00:00+0000")])
    merged = merge_into(event, extracted(), media("flyer", "IMAGE", "2026-09-30T10:00:00+0000"))
    assert [m.post_id for m in merged.media] == ["flyer", "video"]
    assert merged.id == event.id


def test_the_latest_flyer_comes_first_and_videos_after_flyers():
    posts = [
        media("old-flyer", published="2026-10-01T12:00:00+0000"),
        media("video", "VIDEO", published="2026-10-05T12:00:00+0000"),
        media("new-flyer", "CAROUSEL_ALBUM", published="2026-10-03T12:00:00+0000"),
        media("old-video", "VIDEO", published="2026-10-02T12:00:00+0000"),
    ]
    assert [m.post_id for m in ordered_media(posts)] == ["new-flyer", "old-flyer", "video", "old-video"]


def test_saved_events_follow_the_post_order():
    posts = [media("old", published="2026-10-01T12:00:00+0000"), media("new", published="2026-10-03T12:00:00+0000")]
    storage.save_events([stored(posts=posts)])
    assert [m.post_id for m in storage.load_events()[0].media] == ["new", "old"]


def test_merge_fills_missing_details_but_keeps_known_ones():
    event = stored(title="Social", start_time=None, venue="Academia")
    merged = merge_into(event, extracted(title="Otro", start_time="20:00", venue="Otro lugar"), media("p2"))
    assert merged.title == "Social" and merged.venue == "Academia"
    assert merged.start_time == "20:00"


def test_merging_the_same_post_twice_does_not_duplicate_it():
    event = stored(posts=[media("p1")])
    assert len(merge_into(event, extracted(), media("p1")).media) == 1


# ---------- re-analysis ----------


def test_detach_removes_the_post_and_drops_events_left_without_posts():
    shared = stored("a", posts=[media("p1"), media("p2")])
    only_p1 = stored("b", posts=[media("p1")])
    result = detach_post([shared, only_p1], "p1")
    assert [e.id for e in result] == ["a"]
    assert [m.post_id for m in result[0].media] == ["p2"]


# ---------- updates from later posts ----------


def test_a_later_post_corrects_date_time_and_prices_but_keeps_the_title():
    flyer = stored(
        title="Social Espacio Seguro", start_time="20:00", posts=[media("flyer", published="2026-10-01T12:00:00+0000")]
    )
    update = extracted(title="¡Cambio de hora!", start_time="21:00", prices=[{"label": "General", "amount_cop": 20000}])
    merged = merge_into(flyer, update, media("update", published="2026-10-05T12:00:00+0000"))
    assert merged.start_time == "21:00" and merged.prices[0].amount_cop == 20000
    assert merged.title == "Social Espacio Seguro"


def test_a_missing_venue_is_filled_in_by_a_later_post():
    flyer = stored(venue=None, address=None, posts=[media("flyer", published="2026-10-01T12:00:00+0000")])
    reminder = extracted(venue="Escuela del Mambo", address="Calle 1 # 2-3")
    merged = merge_into(flyer, reminder, media("reminder", published="2026-10-05T12:00:00+0000"))
    assert (merged.venue, merged.address) == ("Escuela del Mambo", "Calle 1 # 2-3")


def test_an_older_post_analyzed_again_never_overrides_newer_details():
    event = stored(start_time="21:00", posts=[media("update", published="2026-10-05T12:00:00+0000")])
    old_flyer = extracted(start_time="20:00")
    merged = merge_into(event, old_flyer, media("flyer", published="2026-10-01T12:00:00+0000"))
    assert merged.start_time == "21:00"
