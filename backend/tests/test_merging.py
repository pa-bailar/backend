"""The same event announced by several posts (flyer, video, reminder) becomes one event."""

from pabailar.merging import detach_post, find_existing, looks_like_same_event, merge_into
from tests.factories import extracted, media, stored

# ---------- matching ----------


def test_gemini_link_wins_even_when_details_differ():
    event = stored("flyer-0", title="Social Espacio Seguro", start_time="20:00")
    candidate = extracted(same_as="flyer-0", title="Ven y baila este sábado", start_time=None, date="2026-10-11")
    assert find_existing([event], "academia", candidate) is event


def test_gemini_link_to_another_account_is_ignored():
    event = stored("flyer-0", account="otra")
    assert find_existing([event], "academia", extracted(same_as="flyer-0", date="2026-12-01")) is None


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
    assert find_existing([stored()], "academia", extracted(date="2026-11-01")) is None


# ---------- merging ----------


def test_merge_adds_the_post_and_puts_images_before_videos():
    event = stored(posts=[media("video", "VIDEO", "2026-09-28T10:00:00+0000")])
    merged = merge_into(event, extracted(), media("flyer", "IMAGE", "2026-09-30T10:00:00+0000"))
    assert [m.post_id for m in merged.media] == ["flyer", "video"]
    assert merged.id == event.id


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
