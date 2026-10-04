"""The same event announced by several posts (flyer, video, reminder) becomes one event."""

from datetime import date, timedelta

from pa_bailar import storage
from pa_bailar.merging import (
    detach_post,
    find_existing,
    looks_like_same_event,
    looks_like_shared_event,
    merge_into,
    ordered_media,
)
from tests.factories import EVENT_DATE, extracted, media, stored

OTHER_DATE = (date.fromisoformat(EVENT_DATE) + timedelta(days=1)).isoformat()  # never the sample event's date

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
    assert not looks_like_same_event(event, "academia", extracted(start_time="20:00", date=OTHER_DATE))
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


# ---------- the same event from two accounts (an organizer and its venue, collaborators) ----------


def test_an_organizer_and_its_venue_posting_the_same_social_merge():
    """Sept 19, 2026: @distritosocialbog listed Bachatamanía's social, and @bachatamania_bogota posted it too."""
    venue_post = stored(
        account="distritosocialbog",
        title="Bachatamanía - Clase y social 100% bachata",
        start_time="20:30",
        organizer="Bachatamanía",
    )
    organizer_post = extracted(
        title="Social de amor y amistad 100% Bachata",
        start_time="20:30",
        venue="Distrito Social",
        organizer="Bachatamaniá Bogotá",
    )
    assert find_existing([venue_post], "bachatamania_bogota", organizer_post, "new-post") is venue_post


def test_a_congress_shared_by_its_collaborators_merges():
    congress = stored(account="levelupbfc", title="Level Up Bachata Fusion Congress", organizer="LuDance")
    assert looks_like_shared_event(congress, "ludancestudios", extracted(title="Congreso Level Up Bachata Fusion"))
    assert looks_like_shared_event(congress, "otra", extracted(title="Level Up Fusion Congress 2026"))


def test_different_events_on_the_same_night_stay_apart():
    social = stored(account="academia", title="Social de salsa", start_time="20:00", venue="Casa Latina")
    # Two academies' socials at the same time: common words only, no venue in common.
    assert not looks_like_shared_event(social, "otra", extracted(title="Social de salsa caleña", start_time="20:00"))
    # Different venues, even naming each other.
    assert not looks_like_shared_event(
        social,
        "otra",
        extracted(title="Social de salsa", start_time="20:00", venue="Salsa Camará", organizer="Academia"),
    )
    # Different times, even with the same title.
    assert not looks_like_shared_event(social, "otra", extracted(title="Social de salsa", start_time="22:00"))
    # Another date.
    assert not looks_like_shared_event(
        social, "otra", extracted(title="Social de salsa", start_time="20:00", date=OTHER_DATE)
    )
    # The same account is the other rule's job (looks_like_same_event).
    assert not looks_like_shared_event(social, "academia", extracted(title="Social de salsa", start_time="20:00"))


def test_a_city_name_in_a_title_doesnt_name_an_account():
    social = stored(account="academia", title="Gran social Bogotá", start_time="20:00")
    assert not looks_like_shared_event(social, "bogotadanceclub", extracted(title="Noche Bogotá", start_time="20:00"))


def test_the_same_account_rule_comes_first():
    mine = stored("p1-0", account="academia", start_time="20:00", title="Social")
    theirs = stored(
        "p2-0", account="otra", start_time="20:00", title="Social", organizer="Academia", posts=[media("p2")]
    )
    assert find_existing([theirs, mine], "academia", extracted(start_time="20:00"), "new-post") is mine


# ---------- events over several days ----------

FESTIVAL = {"title": "Distrito Social Aniversario", "date": "2026-10-31", "end_date": "2026-11-02"}


def test_a_post_about_a_teacher_of_a_festival_joins_the_festival():
    """Sept 2026: @distritosocialbog presented each teacher of its festival; one became two false events."""
    festival = stored(account="distritosocialbog", start_time="20:00", **FESTIVAL)
    teacher = extracted(title="Distrito Social Aniversario - Juanita Quintero", date="2026-11-01", start_time="15:00")
    assert find_existing([festival], "distritosocialbog", teacher, "teacher-post") is festival

    merged = merge_into(festival, teacher, media("teacher-post", published="2026-10-20T12:00:00+0000"))
    assert (merged.date, merged.end_date, merged.start_time) == ("2026-10-31", "2026-11-02", "20:00")
    assert merged.title == "Distrito Social Aniversario"


def test_other_events_during_a_festival_weekend_stay_apart():
    festival = stored(start_time="20:00", **FESTIVAL)
    # The same account's social on one of its nights, even at the same time: not the festival.
    assert not looks_like_same_event(festival, "academia", extracted(title="Social de bachata", date="2026-11-01"))
    assert not looks_like_same_event(
        festival, "academia", extracted(title="Noche de salsa", date="2026-10-31", start_time="20:00")
    )
    # The festival announced again: the same title, on any of its days.
    assert looks_like_same_event(
        festival, "academia", extracted(title="distrito social aniversario", date="2026-11-01")
    )
    # After its last day: another event.
    assert not looks_like_same_event(festival, "academia", extracted(title=FESTIVAL["title"], date="2026-11-03"))


def test_a_congress_posted_by_two_accounts_merges_across_its_days():
    congress = stored(
        account="levelupbfc", title="Level Up Bachata Fusion Congress", date="2026-11-13", end_date="2026-11-15"
    )
    collaborator = extracted(title="Congreso Level Up Bachata Fusion", date="2026-11-14", start_time="10:00")
    assert looks_like_shared_event(congress, "ludancestudios", collaborator)
    ranged = extracted(title="Level Up Fusion Congress", date="2026-11-13", end_date="2026-11-15", start_time="18:00")
    assert looks_like_shared_event(
        stored(account="levelupbfc", title=congress.title, date="2026-11-13", start_time="20:00"), "otra", ranged
    )


def test_the_newest_post_updates_the_last_day_and_a_post_without_one_never_clears_it():
    congress = stored(
        date="2026-11-13", end_date="2026-11-15", posts=[media("flyer", published="2026-10-01T12:00:00+0000")]
    )
    extended = merge_into(
        congress,
        extracted(date="2026-11-13", end_date="2026-11-16"),
        media("new", published="2026-10-05T12:00:00+0000"),
    )
    assert extended.end_date == "2026-11-16"
    reminder = merge_into(congress, extracted(date="2026-11-13"), media("new", published="2026-10-05T12:00:00+0000"))
    assert (reminder.date, reminder.end_date) == ("2026-11-13", "2026-11-15")


def test_an_event_stored_on_its_first_day_gets_its_last_day_from_any_post():
    congress = stored(date="2026-11-13", posts=[media("flyer", published="2026-10-05T12:00:00+0000")])
    older = extracted(date="2026-11-13", end_date="2026-11-15")
    assert merge_into(congress, older, media("old", published="2026-10-01T12:00:00+0000")).end_date == "2026-11-15"


def test_a_rescheduled_date_drops_a_last_day_that_no_longer_fits():
    congress = stored(
        date="2026-11-13", end_date="2026-11-15", posts=[media("flyer", published="2026-10-01T12:00:00+0000")]
    )
    same_as = extracted(same_as=congress.id, date="2026-11-27")  # moved: one day, as posted
    merged = merge_into(congress, same_as, media("new", published="2026-10-05T12:00:00+0000"))
    assert (merged.date, merged.end_date) == ("2026-11-27", None)


def test_an_older_post_with_a_range_never_moves_a_newer_one_day_event():
    """A newer post says 14 Nov; an older one, analyzed after it, says 13–15 Nov: the event stays as posted
    last, instead of a mix of both (14–15 Nov)."""
    event = stored(date="2026-11-14", posts=[media("new", published="2026-10-05T12:00:00+0000")])
    older = extracted(date="2026-11-13", end_date="2026-11-15")
    merged = merge_into(event, older, media("old", published="2026-10-01T12:00:00+0000"))
    assert (merged.date, merged.end_date) == ("2026-11-14", None)


def test_an_event_moved_to_one_earlier_day_drops_its_old_last_day():
    congress = stored(
        date="2026-11-13", end_date="2026-11-15", posts=[media("flyer", published="2026-10-01T12:00:00+0000")]
    )
    moved = extracted(date="2026-11-10")  # one day, before the old range: not one of its days
    merged = merge_into(congress, moved, media("new", published="2026-10-05T12:00:00+0000"))
    assert (merged.date, merged.end_date) == ("2026-11-10", None)


def test_the_newest_range_replaces_both_days():
    congress = stored(
        date="2026-11-13", end_date="2026-11-15", posts=[media("flyer", published="2026-10-01T12:00:00+0000")]
    )
    moved = extracted(date="2026-11-20", end_date="2026-11-22")
    merged = merge_into(congress, moved, media("new", published="2026-10-05T12:00:00+0000"))
    assert (merged.date, merged.end_date) == ("2026-11-20", "2026-11-22")


# ---------- different events that only look alike across accounts ----------


def test_two_accounts_halloween_parties_stay_apart():
    party = stored(account="academia", title="Fiesta de Halloween 2026", start_time="21:00", venue="Casa Latina")
    other = extracted(title="Halloween Party 2026", start_time="21:00")
    assert not looks_like_shared_event(party, "otra", other)
    assert find_existing([party], "otra", other, "new-post") is None


def test_two_congresses_on_the_same_days_stay_apart():
    bachata = stored(account="bachatacol", title="Bachata Congress 2026", date="2026-11-13", end_date="2026-11-15")
    salsa = extracted(title="Salsa Congress 2026", date="2026-11-14", end_date="2026-11-16")
    assert not looks_like_shared_event(bachata, "salsacol", salsa)


def test_two_festivals_on_overlapping_days_stay_apart():
    casinea = stored(account="casineafest", title="Festival Casinea 2026", date="2026-11-13", end_date="2026-11-16")
    tango = extracted(title="Festival de Tango 2026", date="2026-11-15", start_time="19:00")
    assert not looks_like_shared_event(casinea, "tangobogota", tango)
    # The festival's collaborator naming it still joins it.
    teacher = extracted(title="Casinea 2026: taller con Juan", date="2026-11-14", start_time="15:00")
    assert looks_like_shared_event(casinea, "academia", teacher)


def test_titles_alone_merge_two_accounts_only_at_the_same_venue():
    gala = stored(account="academia", title="Gala Estrellas del Caribe", date="2026-11-14", venue="Teatro Colsubsidio")
    same_venue = extracted(title="Estrellas del Caribe: la gala", date="2026-11-14", venue="Teatro Colsubsidio")
    assert looks_like_shared_event(gala, "otra", same_venue)
    no_venue = extracted(title="Estrellas del Caribe: la gala", date="2026-11-14")
    assert not looks_like_shared_event(gala, "otra", no_venue)


def test_the_same_party_at_the_same_venue_and_time_still_merges_across_accounts():
    party = stored(account="academia", title="Fiesta de Halloween", start_time="21:00", venue="Casa Latina")
    venue_post = extracted(title="Halloween Party", start_time="21:00", venue="Casa Latina")
    assert looks_like_shared_event(party, "casalatina_bar", venue_post)
