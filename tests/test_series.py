"""Workshop series: a finite program on separate dated sessions ("programa intensivo: domingos 8, 22 y 29 de
noviembre y 6 de diciembre") is ONE event with `sessions`, listed until its last session. Its rules (models), its
normalization, merging, retention, the prompts, the story path and the admin tools' answers. No network."""

import json
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from pa_bailar import config, health, storage, why
from pa_bailar.commands.answers import added_post_markdown, added_story_markdown
from pa_bailar.extraction import _known_list
from pa_bailar.ids import new_event_id
from pa_bailar.merging import find_existing, looks_like_same_event, merge_into
from pa_bailar.models import Session, StoredEvent, StorySession, series_problems
from pa_bailar.normalize import COURSE_DOUBT, normalize_event
from pa_bailar.pipeline import Sweep
from pa_bailar.prompts import EXTRACTION_PROMPT, STORY_PROMPT, TRIAGE_PROMPT
from pa_bailar.stories import resolve_date
from pa_bailar.text import event_dates_label, sessions_label
from tests import test_stories as st
from tests.factories import EVENT_DATE, extracted, make_image, media, stored
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post, read, run

FIRST = date.fromisoformat(EVENT_DATE)
# Four sessions over four weeks, one skipped: 0, 14, 21 and 28 days after the first.
DAYS = [(FIRST + timedelta(days=offset)).isoformat() for offset in (0, 14, 21, 28)]


def sessions(days=DAYS, start="14:00", end="17:00") -> list[Session]:
    return [Session(date=day, start_time=start, end_time=end) for day in days]


def series(
    event_id="intensivo", days=DAYS, title="Programa intensivo de bachata", start="14:00", **details
) -> StoredEvent:
    fields = {"date": days[0], "end_date": days[-1], "start_time": start, "end_time": "17:00"}
    return stored(
        event_id, title=title, event_type="workshop", sessions=sessions(days, start=start), **(fields | details)
    )


@pytest.fixture(autouse=True)
def accounts_and_images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


# ---------- the rules (models.series_problems, StoredEvent) ----------


def test_a_series_follows_its_sessions():
    event = series()
    assert series_problems(event) == []
    assert event.last_day == DAYS[-1] and event.session_dates == DAYS
    assert series_problems(stored()) == []  # not a series: nothing to check
    # Through JSON and back, as events.json stores it.
    [loaded] = storage._events_adapter.validate_python(json.loads(json.dumps([event.model_dump(mode="json")])))
    assert loaded.sessions == event.sessions


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"sessions": sessions(DAYS[:1]), "end_date": None}, "1 sessions"),
        ({"sessions": sessions([DAYS[0], DAYS[2], DAYS[1], DAYS[3]])}, "out of order"),
        ({"sessions": sessions([DAYS[0], DAYS[0], DAYS[2], DAYS[3]])}, "out of order or repeated"),
        ({"sessions": [*sessions(DAYS[:3]), Session(date="2026-02-30", start_time=None, end_time=None)]}, "valid"),
        ({"sessions": sessions(DAYS, start="25:00")}, "bad time"),
        ({"end_date": DAYS[2]}, "first and last sessions' dates"),
        ({"date": DAYS[1]}, "first and last sessions' dates"),
    ],
)
def test_a_series_that_breaks_the_rules_isnt_stored(change, problem):
    fields = series().model_dump() | change
    with pytest.raises(ValidationError, match=problem):
        StoredEvent.model_validate(fields)


def test_at_most_twelve_sessions_within_four_months():
    weekly = [(FIRST + timedelta(weeks=week)).isoformat() for week in range(13)]
    too_many = series().model_dump() | {"sessions": sessions(weekly), "end_date": weekly[-1]}
    with pytest.raises(ValidationError, match="13 sessions"):
        StoredEvent.model_validate(too_many)
    long = [DAYS[0], (FIRST + timedelta(days=config.MAX_SERIES_DAYS)).isoformat()]
    with pytest.raises(ValidationError, match="more than 123 days"):
        StoredEvent.model_validate(series().model_dump() | {"sessions": sessions(long), "end_date": long[-1]})
    longest = [DAYS[0], (FIRST + timedelta(days=config.MAX_SERIES_DAYS - 1)).isoformat()]
    StoredEvent.model_validate(series().model_dump() | {"sessions": sessions(longest), "end_date": longest[-1]})


# ---------- normalization ----------


def test_sessions_are_sorted_without_repeats_and_set_the_events_days_and_times():
    gemini = [
        Session(date=DAYS[2], start_time=None, end_time=None),
        Session(date=DAYS[0], start_time="2:00", end_time=None),
        Session(date=DAYS[1], start_time=None, end_time=None),
        Session(date=DAYS[0], start_time="15:00", end_time=None),  # the same day twice
        Session(date=DAYS[3], start_time=None, end_time=None),
        Session(date="sábado", start_time=None, end_time=None),  # not a date
    ]
    event = normalize_event(extracted(date=None, start_time="14:00", end_time="17:00", sessions=gemini))
    assert [session.date for session in event.sessions or []] == DAYS
    assert (event.date, event.end_date) == (DAYS[0], DAYS[-1])
    assert (event.sessions or [])[0].start_time == "02:00"  # its own time
    assert (event.sessions or [])[1].start_time == "14:00" and (event.sessions or [])[1].end_time == "17:00"  # common
    assert (event.start_time, event.end_time) == ("02:00", "17:00")  # the first session's
    assert event.weekday == ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][FIRST.weekday()]
    StoredEvent(**event.model_dump(exclude={"image_index", "same_as"}), id="x", account="a", media=[media()])


def test_one_session_or_days_in_a_row_arent_a_series():
    one = normalize_event(extracted(sessions=sessions(DAYS[:1])))
    assert one.sessions is None and one.date == EVENT_DATE and one.end_date is None
    in_a_row = [(FIRST + timedelta(days=offset)).isoformat() for offset in range(3)]
    congress = normalize_event(extracted(event_type="congress", sessions=sessions(in_a_row)))
    assert congress.sessions is None
    assert (congress.date, congress.end_date) == (in_a_row[0], in_a_row[-1])  # an event over several days


def test_too_many_sessions_or_too_long_is_a_course():
    weekly = [(FIRST + timedelta(weeks=week)).isoformat() for week in range(13)]
    course = normalize_event(extracted(sessions=sessions(weekly)))
    assert course.is_recurring and course.sessions is None and COURSE_DOUBT in course.doubts
    long = [DAYS[0], (FIRST + timedelta(days=150)).isoformat()]
    assert normalize_event(extracted(sessions=sessions(long))).is_recurring


def test_multi_day_events_are_unchanged():
    last = (FIRST + timedelta(days=2)).isoformat()
    event = normalize_event(extracted(event_type="congress", end_date=last))
    assert (event.date, event.end_date, event.sessions) == (EVENT_DATE, last, None)
    far = (FIRST + timedelta(days=20)).isoformat()
    assert normalize_event(extracted(end_date=far)).end_date is None  # still at most a week without sessions


# ---------- merging ----------


def test_a_post_about_one_session_merges_into_the_series_and_keeps_its_sessions():
    event = series(venue="Academia X")
    reminder = extracted(title="Intensivo: sesión 3", date=DAYS[2], start_time="14:00")
    assert find_existing([event], "academia", reminder, "reminder") is event
    merged = merge_into(event, reminder, media("reminder", published="2026-12-01T12:00:00+0000"))
    assert merged.sessions == event.sessions and (merged.date, merged.end_date) == (DAYS[0], DAYS[-1])
    assert [m.post_id for m in merged.media] == ["reminder", "p1"]
    StoredEvent.model_validate(merged.model_dump())
    # The same venue and time, with another title, is that session too.
    same_place = extracted(title="Domingo de bachata", venue="Academia X", date=DAYS[1], start_time="14:00")
    assert looks_like_same_event(event, "academia", same_place)


def test_other_events_on_a_session_day_or_between_sessions_stay_apart():
    event = series(venue="Academia X")
    social = extracted(title="Social de bachata", date=DAYS[1], start_time="20:00", venue="Academia X")
    assert not looks_like_same_event(event, "academia", social)
    between = (FIRST + timedelta(days=7)).isoformat()  # inside first → last, but no session that day
    assert not looks_like_same_event(event, "academia", extracted(title=event.title, date=between))
    assert not looks_like_same_event(event, "otra", extracted(title=event.title, date=DAYS[1]))  # another account


def test_two_series_of_one_account_merge_only_when_they_are_the_same_program():
    level_1 = series("nivel-1", title="Intensivo de salsa Nivel 1", start="10:00")
    level_2 = extracted(title="Intensivo de salsa Nivel 2", date=DAYS[0], sessions=sessions(start="12:00"))
    assert not looks_like_same_event(level_1, "academia", level_2)  # same Sundays, other time
    other = extracted(title="Taller de heels", date=DAYS[0], sessions=sessions(start="10:00"))
    assert not looks_like_same_event(level_1, "academia", other)  # same days and time, another program
    elsewhere = [(FIRST + timedelta(days=offset)).isoformat() for offset in (1, 8, 15)]
    assert not looks_like_same_event(level_1, "academia", extracted(title=level_1.title, sessions=sessions(elsewhere)))
    again = extracted(title="intensivo de salsa nivel 1", date=DAYS[0], sessions=sessions(start="10:00"))
    assert looks_like_same_event(level_1, "academia", again)


def test_the_newest_post_sets_the_sessions_and_an_older_flyer_completes_a_session():
    event = series()
    moved = [*DAYS[:3], (FIRST + timedelta(days=35)).isoformat()]  # the last session moved a week
    newer = normalize_event(extracted(title=event.title, sessions=sessions(moved)))
    merged = merge_into(event, newer, media("newer", published="2026-12-01T12:00:00+0000"))
    assert merged.session_dates == moved and merged.end_date == moved[-1]
    StoredEvent.model_validate(merged.model_dump())

    one_session = stored("sesion", title="Intensivo", date=DAYS[1], start_time="14:00", posts=[media("new")])
    program = normalize_event(extracted(title="Programa intensivo", sessions=sessions()))
    completed = merge_into(one_session, program, media("old", published="2026-01-01T12:00:00+0000"))
    assert completed.session_dates == DAYS and (completed.date, completed.end_date) == (DAYS[0], DAYS[-1])
    assert completed.title == "Intensivo"  # the rest keeps its first value
    StoredEvent.model_validate(completed.model_dump())


def test_a_newer_post_moving_a_series_to_one_day_drops_its_sessions():
    moved = (FIRST + timedelta(days=3)).isoformat()  # not one of its sessions (Gemini linked it: same_as)
    one_day = extracted(title="Intensivo de un día", date=moved)
    merged = merge_into(series(), one_day, media("newer", published="2026-12-01T12:00:00+0000"))
    assert merged.sessions is None and merged.end_date is None and merged.date == moved
    StoredEvent.model_validate(merged.model_dump())
    # A newer post about one of its sessions leaves its days as they are.
    session = merge_into(series(), extracted(date=DAYS[0]), media("newer", published="2026-12-01T12:00:00+0000"))
    assert session.session_dates == DAYS


# ---------- the sweep: stored, listed until its last session ----------


def test_a_series_post_becomes_one_event_named_after_its_first_session():
    analysis = event_post("p1", title="Programa intensivo", event_type="workshop", sessions=sessions())
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": analysis}))
    [event] = read(config.EVENTS_FILE)
    assert event["id"] == new_event_id("Programa intensivo", DAYS[0], set())  # its first session's day
    assert (event["date"], event["end_date"]) == (DAYS[0], DAYS[-1])
    assert event["sessions"] == [{"date": day, "start_time": "14:00", "end_time": "17:00"} for day in DAYS]


def test_events_without_sessions_store_null():
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    [event] = read(config.EVENTS_FILE)
    assert event["sessions"] is None


def test_a_series_is_kept_until_its_last_session_has_passed_long_enough():
    today = config.now_bogota().date()
    retention = config.EVENT_RETENTION_DAYS

    def ago(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()

    # Two different series (the same title and a day in common would be one: merging.merge_duplicates).
    started_long_ago = series("still", days=[ago(retention + 30), ago(retention + 10), ago(retention - 1)])
    over = series(
        "over", days=[ago(retention + 30), ago(retention + 1)], posts=[media("b")], title="Intensivo de salsa caleña"
    )
    storage.save_events([started_long_ago, over])
    Sweep(lookback_days=7, instagram=FakeInstagram({"academia": [], "otra": []}), extractor=FakeExtractor({})).run()
    assert [event["id"] for event in read(config.EVENTS_FILE)] == ["still"]


def test_known_series_are_listed_with_their_sessions_for_gemini():
    line = _known_list([series()])
    assert f"{DAYS[0]} → {DAYS[-1]} (sessions: {', '.join(DAYS)})" in line


# ---------- the prompts ----------


def test_the_prompts_take_dated_series_and_still_leave_out_open_ended_classes():
    for prompt in (TRIAGE_PROMPT, EXTRACTION_PROMPT, STORY_PROMPT):
        assert "workshop series: ONE finite program" in prompt
        assert "EVERY one of them with its own date written in the post" in prompt
        assert "programa intensivo: domingos 8, 22 y 29 de noviembre y 6 de diciembre" in prompt
        # Open-ended classes and undated programs still don't count.
        assert '"todos los jueves", "cada viernes"' in prompt
        assert '"todos los sábados de noviembre"' in prompt
        assert "have more than 12 sessions or last more than 4 months" in prompt
    assert "or its last session for a workshop series, is today or later" in TRIAGE_PROMPT
    assert "A workshop series with every session dated is an\nevent, not regular classes." in TRIAGE_PROMPT
    assert "is ONE event with sessions: one entry per session" in EXTRACTION_PROMPT
    assert 'Days in a row ("7, 8 y 9 de noviembre") are an event over several days' in EXTRACTION_PROMPT
    assert "A post about one session of a known workshop series" in EXTRACTION_PROMPT
    assert "sessions: only for a workshop series, one entry per session" in STORY_PROMPT


# ---------- stories: sessions worked out in code ----------


def story_series(**fields):
    printed = [StorySession(day=day, month=month, start_time="14:00", end_time=None) for month, day in fields.pop("at")]
    return st.story_event(sessions=printed, **fields)


def test_a_storys_sessions_are_worked_out_from_what_is_printed():
    taken = date(2026, 10, 4)
    event = story_series(at=[(11, 8), (11, 22), (11, 29), (12, 6)], day=8, month=11, weekday="domingo")
    resolved = resolve_date(event, taken, taken)
    assert [day for day, _ in resolved.sessions] == [
        date(2026, 11, 8),
        date(2026, 11, 22),
        date(2026, 11, 29),
        date(2026, 12, 6),
    ]
    assert (resolved.start, resolved.end) == (date(2026, 11, 8), date(2026, 12, 6))
    assert resolved.year_inferred and not resolved.weekday_mismatch
    # Shared after its first sessions: still this year's series, not next year's.
    later = resolve_date(event, date(2026, 11, 23), date(2026, 11, 23))
    assert later.start == date(2026, 11, 8) and later.end == date(2026, 12, 6)


def test_a_storys_sessions_across_the_new_year_and_without_their_month():
    taken = date(2026, 12, 1)
    across = resolve_date(story_series(at=[(12, 20), (1, 3), (1, 10)]), taken, taken)
    assert [day for day, _ in across.sessions] == [date(2026, 12, 20), date(2027, 1, 3), date(2027, 1, 10)]
    inherited = resolve_date(story_series(at=[(12, 13), (None, 20), (None, 3)]), taken, taken)
    assert [day for day, _ in inherited.sessions] == [date(2026, 12, 13), date(2026, 12, 20), date(2027, 1, 3)]
    wrong_day = resolve_date(
        story_series(at=[(11, 8), (11, 23)], weekday="domingo"), date(2026, 10, 4), date(2026, 10, 4)
    )
    assert wrong_day.weekday_mismatch and any("lunes" in note for note in wrong_day.notes)


def test_a_story_with_a_series_publishes_one_event_with_its_sessions():
    first = st.EVENT_DAY
    days = [first + timedelta(days=offset) for offset in (0, 14, 21)]
    event = story_series(
        at=[(day.month, day.day) for day in days], title="Intensivo de bachata", day=first.day, month=first.month
    )
    extractor = st.FakeStoryExtractor(st.analysis(events=[event]))
    added = Sweep(lookback_days=7, instagram=st.FakeInstagram({"salsa.club"}), extractor=extractor).add_story(
        st.shots(1)
    )
    assert added.outcome == "event"
    [stored_event] = storage.load_events()
    assert stored_event.session_dates == [day.isoformat() for day in days]
    assert (stored_event.date, stored_event.end_date) == (days[0].isoformat(), days[-1].isoformat())
    assert stored_event.start_time == "14:00"
    label = sessions_label([day.isoformat() for day in days])
    assert f"· {label} · 2:00 p. m." in added_story_markdown(added)


def test_a_story_whose_last_session_passed_isnt_published():
    today = config.now_bogota().date()
    days = [today - timedelta(days=offset) for offset in (21, 14, 7)]
    event = story_series(
        at=[(day.month, day.day) for day in days], year=days[0].year, day=days[0].day, month=days[0].month
    )
    extractor = st.FakeStoryExtractor(st.analysis(events=[event]))
    added = Sweep(lookback_days=7, instagram=st.FakeInstagram({"salsa.club"}), extractor=extractor).add_story(
        st.shots(1)
    )
    assert added.past and storage.load_events() == []


# ---------- the admin tools' answers ----------


def test_sessions_labels():
    assert (
        sessions_label(["2026-11-08", "2026-11-22", "2026-11-29", "2026-12-06"]) == "4 sesiones: 8, 22, 29 nov y 6 dic"
    )
    assert sessions_label(["2026-11-08", "2026-11-15", "2026-11-22"]) == "3 sesiones: 8, 15 y 22 nov"
    assert sessions_label(["2026-12-29", "2027-01-05"]) == "2 sesiones: 29 dic 2026 y 5 ene 2027"
    assert event_dates_label("2026-11-13", "2026-11-15") == "13–15 nov 2026"  # not a series: as before
    assert event_dates_label("2026-11-08", "2026-12-06", ["2026-11-08", "2026-12-06"]) == "2 sesiones: 8 nov y 6 dic"


def test_answers_show_the_sessions():
    event = series()
    label = sessions_label(DAYS)
    assert label in added_post_markdown(_added(event))
    storage.write_json(config.EVENTS_FILE, [event.model_dump(mode="json")])
    record = {
        "account": "academia",
        "permalink": "https://www.instagram.com/p/p1/",
        "processed_at": "2026-10-02T21:05:00-05:00",
        "is_event_post": True,
        "reason": "Anuncia un intensivo",
        "model": "gemini-3.8-flash",
        "outcome": "event",
        "event_ids": [event.id],
    }
    files = {"processed_posts.json": {"p1": record}}
    result = why.diagnose("https://www.instagram.com/p/p1/", read=lambda name, default: files.get(name, default))
    assert result.verdict == "Está en el sitio." and result.events[0]["date"] == label
    low = series(confidence="low", doubts=["fecha"])
    assert label in health.report_markdown([], [low])


def _added(event: StoredEvent):
    from pa_bailar.pipeline import AddedPost

    return AddedPost("academia", False, "https://www.instagram.com/p/p1/", "event", "", "fake-flash", False, [event])
