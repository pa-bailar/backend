"""Flash's second opinion on the triage (17 Oct 2026): Flash-Lite's "no" was final, and 119 posts were ruled out in a
week without anyone knowing how many were events. At a run's end, with what Flash has left after the upgrades, Flash
reads a few of the posts the triage ruled out this run, and the run counts how often the triage was wrong."""

from datetime import UTC, datetime, timedelta

from pa_bailar import config, health, storage
from pa_bailar.models import PostAnalysis, ProcessedPost
from pa_bailar.pipeline.sweep import MISSED_BY_TRIAGE, RuledOut, second_opinion_order
from tests.factories import extracted
from tests.test_health import check as health_check
from tests.test_health import record as run_record
from tests.test_sweep import (
    FakeExtractor,
    FakeInstagram,
    event_post,
    post,
    read,
    run,
    two_accounts_and_fake_images,  # noqa: F401  (autouse: two accounts, images offline)
)
from tests.test_upgrades import FlashFor, day, flash_reads, on_record, provisional

NO_EVENT = PostAnalysis(is_event_post=False, reason="un tutorial de pasos", events=[])


def records() -> dict:
    return read(config.PROCESSED_POSTS_FILE)


def test_an_event_the_triage_ruled_out_is_found_by_flash_and_stored_as_any_flash_reading():
    instagram = FakeInstagram({"academia": [post("tutorial")], "otra": []})
    extractor = FakeExtractor({"tutorial": event_post("tutorial", title="Social de salsa")}, not_events={"tutorial"})

    stats = run(instagram, extractor)

    assert extractor.extracted_posts == ["tutorial"]
    assert (stats.triage_checked, stats.triage_misses) == (1, 1)
    # The post was counted once (ruled out by the triage), its event as new.
    assert (stats.posts_analyzed, stats.posts_triaged_out, stats.events_new) == (1, 1, 1)
    events = read(config.EVENTS_FILE)
    assert [event["title"] for event in events] == ["Social de salsa"]
    checked = records()["tutorial"]
    assert (checked["outcome"], checked["model"], checked["provisional"]) == ("event", "fake-flash", False)
    assert checked["triage_checked"] is True and checked["event_ids"] == [events[0]["id"]]
    assert stats.changes[events[0]["id"]].detail == MISSED_BY_TRIAGE  # the admin page's history says why
    run_ = health.record_of(stats, ["academia", "otra"])
    assert (run_.triage_checked, run_.triage_misses) == (1, 1)


def test_flash_agreeing_is_counted_and_the_post_is_not_checked_again():
    instagram = FakeInstagram({"academia": [post("tutorial")], "otra": []})

    stats = run(instagram, FakeExtractor({"tutorial": NO_EVENT}, not_events={"tutorial"}))

    assert (stats.triage_checked, stats.triage_misses) == (1, 0)
    checked = records()["tutorial"]
    assert (checked["outcome"], checked["model"], checked["triage_checked"]) == ("not_event", "fake-flash", True)
    assert read(config.EVENTS_FILE) == []

    again = FakeExtractor({}, not_events={"tutorial"})  # would fail on a second read
    stats = run(instagram, again)
    assert again.attempts == [] and stats.triage_checked == 0


def test_an_event_already_past_agrees_with_the_triage():
    """The triage's "no" includes posts whose events all ended: Flash finding one isn't a miss."""
    instagram = FakeInstagram({"academia": [post("recuerdo")], "otra": []})
    past = event_post("recuerdo", date=day(-3))

    stats = run(instagram, FakeExtractor({"recuerdo": past}, not_events={"recuerdo"}))

    assert (stats.triage_checked, stats.triage_misses) == (1, 0)
    assert records()["recuerdo"]["outcome"] == "discarded" and read(config.EVENTS_FILE) == []


def test_no_second_opinion_when_flash_cant_be_used():
    instagram = FakeInstagram({"academia": [post("tutorial")], "otra": []})
    extractor = FakeExtractor({"tutorial": event_post("tutorial")}, not_events={"tutorial"}, flash_available=False)

    stats = run(instagram, extractor)

    assert extractor.attempts == [] and stats.triage_checked == 0
    assert records()["tutorial"]["model"] == "fake-lite" and records()["tutorial"]["triage_checked"] is False


def test_no_second_opinion_after_the_runs_time(monkeypatch):
    instagram = FakeInstagram({"academia": [post("tutorial")], "otra": []})
    extractor = FakeExtractor({"tutorial": event_post("tutorial")}, not_events={"tutorial"})
    monkeypatch.setattr("pa_bailar.pipeline.Sweep._upgrade_by_urgency", lambda self: setattr(self, "started", 0))

    stats = run(instagram, extractor)

    assert extractor.attempts == [] and stats.triage_checked == 0 and stats.out_of_time


def test_at_most_the_cap_the_newest_first(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_CHECKS_PER_RUN", 2)
    ids = [f"t{n}" for n in range(5)]  # t0 the newest
    instagram = FakeInstagram({"academia": [post(i, days_ago=1 + n) for n, i in enumerate(ids)], "otra": []})
    extractor = FlashFor(10, {i: NO_EVENT for i in ids}, not_events=set(ids))

    stats = run(instagram, extractor)

    assert extractor.extracted_posts == ["t0", "t1"] and stats.triage_checked == 2


def test_flash_stops_the_checks_when_it_runs_out():
    ids = ["t0", "t1", "t2"]
    instagram = FakeInstagram({"academia": [post(i, days_ago=1 + n) for n, i in enumerate(ids)], "otra": []})
    extractor = FlashFor(1, {i: NO_EVENT for i in ids}, not_events=set(ids))

    stats = run(instagram, extractor)

    assert extractor.extracted_posts == ["t0"] and stats.triage_checked == 1


def test_the_upgrades_go_first():
    on_record(("p1", "academia", day(1), 2), due=("academia",))
    instagram = FakeInstagram({"academia": [post("p1"), post("tutorial", days_ago=0.5)], "otra": []})
    analyses = flash_reads("p1", date=day(1)) | {"tutorial": event_post("tutorial", title="Otro social")}

    extractor = FlashFor(1, analyses, not_events={"tutorial"})
    stats = run(instagram, extractor, all_accounts=False)
    assert extractor.extracted_posts == ["p1"] and not provisional("p1")
    assert (stats.upgraded, stats.triage_checked) == (1, 0)


def test_what_the_upgrades_leave_goes_to_the_checks():
    on_record(("p1", "academia", day(1), 2), due=("academia",))
    instagram = FakeInstagram({"academia": [post("p1"), post("tutorial", days_ago=0.5)], "otra": []})
    analyses = flash_reads("p1", date=day(1)) | {"tutorial": event_post("tutorial", title="Otro social")}

    extractor = FlashFor(2, analyses, not_events={"tutorial"})
    stats = run(instagram, extractor, all_accounts=False)
    assert extractor.extracted_posts == ["p1", "tutorial"]
    assert (stats.upgraded, stats.triage_checked, stats.triage_misses) == (1, 1, 1)


def test_rule_based_skips_are_not_the_triages_and_never_checked():
    """A focus filter's "no" (accounts.txt `solo:`) is a rule, recorded with model "-": nothing for Flash to check."""
    config.ACCOUNTS_FILE.write_text("academia solo:bachata\notra\n", encoding="utf-8")
    instagram = FakeInstagram({"academia": [post("salsa")], "otra": []})  # its caption names no bachata
    extractor = FakeExtractor({"salsa": event_post("salsa")})

    stats = run(instagram, extractor)

    assert extractor.attempts == [] and stats.triage_checked == 0 and records()["salsa"]["model"] == "-"


def processed(account: str, events: bool) -> ProcessedPost:
    return ProcessedPost(
        account=account,
        permalink="https://www.instagram.com/p/x/",
        processed_at="2026-10-10T10:00:00-05:00",
        is_event_post=events,
        reason="",
        model="m",
        outcome="event" if events else "not_event",
    )


def ruled_out(account: str, hours_ago: float) -> RuledOut:
    published = datetime.now(UTC) - timedelta(hours=hours_ago)
    return RuledOut(account, post(f"{account}-{hours_ago}"), published, [])


def test_accounts_that_post_events_go_first_unproductive_ones_last_the_newest_first_in_each():
    history = [processed("academia", events=True)]
    history += [processed("callada", events=False) for _ in range(config.UNPRODUCTIVE_AFTER_POSTS)]
    items = [ruled_out("callada", 1), ruled_out("nueva", 2), ruled_out("academia", 30), ruled_out("academia", 3)]

    ordered = second_opinion_order(items, history)

    assert [(item.account, item.post["id"]) for item in ordered] == [
        ("academia", "academia-3"),
        ("academia", "academia-30"),
        ("nueva", "nueva-2"),
        ("callada", "callada-1"),
    ]


def test_an_unproductive_accounts_newer_post_waits_behind_a_productive_ones(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_CHECKS_PER_RUN", 1)
    on_record(("p1", "academia", day(1), 2))  # academia has an event on record
    quiet = {f"q{n}": processed("otra", events=False) for n in range(config.UNPRODUCTIVE_AFTER_POSTS)}  # no event
    storage.save_processed_posts(storage.load_processed_posts() | quiet)
    instagram = FakeInstagram({"academia": [post("vieja", days_ago=3)], "otra": [post("nueva", days_ago=0.5)]})
    extractor = FakeExtractor({"vieja": NO_EVENT}, not_events={"vieja", "nueva"})

    stats = run(instagram, extractor)

    assert "nueva" not in extractor.extracted_posts and "vieja" in extractor.extracted_posts
    assert stats.triage_checked == 1


def test_repeated_misses_become_a_health_notice():
    def keys(run_, history):
        return {finding.key: finding.level for finding in health_check(run_, history)}

    history = [run_record(triage_checked=3, triage_misses=1)]
    missed = run_record(triage_checked=2, triage_misses=1)
    assert keys(missed, history)["triage-misses"] == "notice"
    assert "triage-misses" not in keys(missed, [])  # one miss may be bad luck
    assert "triage-misses" not in keys(run_record(triage_checked=3), history)  # only on a run that missed one
    old = [run_record(triage_checked=3, triage_misses=1)] + [run_record()] * config.TRIAGE_MISS_RUNS
    assert "triage-misses" not in keys(missed, old)  # out of the window


def test_a_several_events_reading_keeps_each():
    instagram = FakeInstagram({"academia": [post("agenda")], "otra": []})
    agenda = PostAnalysis(
        is_event_post=True,
        reason="",
        events=[extracted(title="Social", date=day(2)), extracted(title="Taller", date=day(3), event_type="workshop")],
    )

    stats = run(instagram, FakeExtractor({"agenda": agenda}, not_events={"agenda"}))

    assert stats.triage_misses == 1 and len(records()["agenda"]["event_ids"]) == 2
