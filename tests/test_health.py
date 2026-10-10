"""Sweep health checks: rules over the run and the runs before it."""

from datetime import date, datetime, timedelta

from pa_bailar import config, health
from pa_bailar.health import RunRecord
from pa_bailar.instagram_usage import ReadsSummary
from pa_bailar.pipeline import AccountStats, RunStats
from tests.factories import media, stored

TODAY = date(2026, 10, 2)


def record(**changes) -> RunRecord:
    """A run where nothing went wrong, with `changes`."""
    base = {
        "finished_at": "2026-10-02T12:00:00-05:00",
        "accounts": 2,
        "failed_accounts": [],
        "skipped_accounts": [],
        "posts_analyzed": 3,
        "events_new": 1,
        "events_merged": 0,
        "pending": 0,
        "post_errors": 0,
        "provisional": 0,
        "rate_limited": False,
        "out_of_time": False,
        "gemini_requests": {},
    }
    return RunRecord(**(base | changes))


def stats_with(**accounts: AccountStats) -> RunStats:
    stats = RunStats()
    stats.by_account = dict(accounts)
    return stats


def recent() -> AccountStats:
    return AccountStats(latest_post=(TODAY - timedelta(days=2)).isoformat())


def check(run: RunRecord, history: list[RunRecord] | None = None, stats: RunStats | None = None):
    return health.check(run, history or [], stats or stats_with(academia=recent()), TODAY)


def levels(findings: list[health.Finding]) -> dict[str, str]:
    return {finding.key: finding.level for finding in findings}


def test_a_healthy_run_has_nothing_to_report():
    assert check(record()) == []
    assert "Nothing to look at" in health.report_markdown([], [])


def test_an_account_failing_once_is_a_notice_and_three_runs_in_a_row_a_warning():
    failing = record(failed_accounts=["academia"])
    assert levels(check(failing)) == {"fetch:academia": "notice"}
    assert levels(check(failing, [record(), failing, failing])) == {"fetch:academia": "warning"}
    assert levels(check(failing, [failing, record(), failing])) == {"fetch:academia": "notice"}  # not in a row


def test_rate_limits_time_budget_and_post_errors_become_warnings_when_they_repeat():
    bad = record(rate_limited=True, out_of_time=True, post_errors=2, skipped_accounts=["otra"])
    assert levels(check(bad)) == {"rate-limit": "notice", "time-budget": "notice", "post-errors": "notice"}
    assert levels(check(bad, [bad, bad])) == {
        "rate-limit": "warning",
        "time-budget": "warning",
        "post-errors": "warning",
    }


def test_a_backlog_going_down_is_fine_but_a_stuck_one_is_a_warning():
    going_down = [record(pending=30), record(pending=20), record(pending=10)]
    assert levels(check(record(pending=5), going_down)) == {"pending": "notice"}
    stuck = [record(pending=30), record(pending=31), record(pending=29)]
    assert levels(check(record(pending=30), stuck)) == {"backlog-stuck": "warning"}


def test_a_week_of_posts_without_events_is_a_warning():
    quiet = [record(events_new=0, posts_analyzed=1)] * (health.QUIET_RUNS - 1)
    assert levels(check(record(events_new=0, posts_analyzed=1), quiet)) == {"no-events": "warning"}
    # Too few posts to say anything, or one event in the week: fine.
    assert check(record(events_new=0, posts_analyzed=0), [record(events_new=0, posts_analyzed=0)] * 13) == []
    assert check(record(events_new=0), [*quiet[1:], record(events_merged=1)]) == []


def test_accounts_without_recent_posts_are_noticed():
    old = AccountStats(latest_post=(TODAY - timedelta(days=health.INACTIVE_DAYS)).isoformat())
    stats = stats_with(vieja=old, vacia=AccountStats(), caida=AccountStats(fetch_failed=True), activa=recent())
    assert levels(check(record(), stats=stats)) == {"inactive:vieja": "notice", "inactive:vacia": "notice"}


def test_events_with_low_confidence_or_date_doubts_are_listed_for_review():
    future = (TODAY + timedelta(days=5)).isoformat()
    events = [
        stored("fine", date=future, doubts=["No se especifica el precio"]),
        stored("unsure", date=future, confidence="medium"),
        stored("wrong-day", date=future, doubts=["El folleto dice viernes 24, pero ese DÍA es sábado"]),
        stored("past", date=(TODAY - timedelta(days=1)).isoformat(), confidence="low"),
    ]
    assert [event.id for event in health.events_to_review(events, TODAY)] == ["unsure", "wrong-day"]
    report = health.report_markdown([], health.events_to_review(events, TODAY))
    assert "Events to review" in report and "wrong-day" not in report  # listed by title, linked to the post


def test_the_fingerprint_changes_only_when_the_warnings_do():
    warning = health.Finding("warning", "fetch:academia", "@academia couldn't be read in the last 3 runs")
    same_warning_new_count = health.Finding(
        "warning", "fetch:academia", "@academia couldn't be read in the last 4 runs"
    )
    notice = health.Finding("notice", "pending", "5 posts wait")
    assert health.fingerprint([warning]) == health.fingerprint([same_warning_new_count, notice])
    assert health.fingerprint([warning]) != health.fingerprint([])


def test_the_history_keeps_the_latest_runs():
    health.save_history([record(posts_analyzed=n) for n in range(health.HISTORY_RUNS + 5)])
    history = health.load_history()
    assert len(history) == health.HISTORY_RUNS and history[-1].posts_analyzed == health.HISTORY_RUNS + 4


def test_handles_in_the_report_never_mention_github_users():
    finding = health.Finding("warning", "fetch:zafradance", "@zafradance couldn't be read")
    event = stored("e", date=(TODAY + timedelta(days=1)).isoformat(), title="Social con @djsalsa", confidence="low")
    report = health.report_markdown([finding], [event])
    assert "@zafradance" not in report and "@djsalsa" not in report and "@academia" not in report
    assert "@⁠zafradance" in report  # reads the same, but isn't a mention


def test_an_account_read_every_other_run_still_warns_after_three_failed_tries():
    """Each account is read about once a day: the runs that didn't try it don't break the streak."""
    failing = record(failed_accounts=["academia"], read_accounts=["otra"])
    other_turn = record(read_accounts=["otra"])  # academia wasn't its turn
    history = [failing, other_turn, failing, other_turn]
    assert levels(check(failing, history)) == {"fetch:academia": "warning"}
    read_fine = record(read_accounts=["academia"])
    assert levels(check(failing, [failing, read_fine, failing])) == {"fetch:academia": "notice"}


def test_events_over_several_days_are_reviewed_until_their_last_day():
    under_way = stored(
        "under-way",
        date=(TODAY - timedelta(days=1)).isoformat(),
        end_date=(TODAY + timedelta(days=1)).isoformat(),
        confidence="medium",
    )
    assert [event.id for event in health.events_to_review([under_way], TODAY)] == ["under-way"]


def test_a_congress_or_festival_on_a_single_day_is_reviewed():
    future = (TODAY + timedelta(days=5)).isoformat()
    last_day = (TODAY + timedelta(days=7)).isoformat()
    events = [
        stored("one-day", title="Level Up Congress", date=future, event_type="congress"),
        stored("festival", date=future, end_date=last_day, event_type="festival"),
        stored("social", date=future, event_type="social"),
    ]
    assert [event.id for event in health.events_to_review(events, TODAY)] == ["one-day"]
    report = health.report_markdown([], health.events_to_review(events, TODAY))
    assert f"{future} · [Level Up Congress]" in report and health.SINGLE_DAY_DOUBT in report


def test_an_event_maybe_outside_bogota_is_listed_for_review():
    from pa_bailar.normalize import CITY_DOUBT

    future = (TODAY + timedelta(days=5)).isoformat()
    events = [stored("unknown-city", date=future, doubts=[CITY_DOUBT]), stored("fine", date=future)]
    assert [event.id for event in health.events_to_review(events, TODAY)] == ["unknown-city"]


def test_every_date_doubt_normalize_writes_lists_the_event_for_review():
    """Review finding: "dura más de una semana: revisar fechas" didn't match the date rule ("fecha", not "fechas")."""
    from pa_bailar.normalize import parse_end_date

    doubts: list[str] = []
    parse_end_date("2026-11-13", "2026-11-30", doubts)  # longer than a week
    parse_end_date("2026-11-13", "2026-11-10", doubts)  # ends before it starts
    assert len(doubts) == 2
    for doubt in doubts:
        assert health.review_reasons(stored(doubts=[doubt])) == [doubt]


def test_doubts_about_the_day_or_whether_it_happens_list_the_event_for_review():
    """Their other words (the audit of 7 Oct 2026): a month or year guessed, a weekday that doesn't fit, a new date."""
    for doubt in (
        "mes deducido",
        "año deducido",
        "dice sábado, pero el 12 es domingo",
        "evento reprogramado",
        "pospuesto por lluvia",
        "suspendido",
    ):
        assert health.review_reasons(stored(doubts=[doubt])) == [doubt], doubt


def test_two_events_of_an_account_that_day_sharing_a_title_word_are_listed_for_review():
    """What the merging rules couldn't tell (a new pattern) shows in the health report before visitors notice."""
    day = (date.today() + timedelta(days=3)).isoformat()
    a = stored("orquesta-x", posts=[media("p1")], title="Orquesta Candombé en vivo", date=day)
    b = stored("candombe-noche", posts=[media("p2")], title="Noche con Candombé", date=day, start_time="22:00")
    other = stored("otra-cosa", posts=[media("p3")], title="Taller de giros", date=day)
    review = health.events_to_review([a, b, other], date.today())
    assert [event.id for event in review] == ["orquesta-x", "candombe-noche"]
    assert "Noche con Candombé" in health.report_markdown([], review)


def runs_at(*moments: str) -> list[RunRecord]:
    """Runs finishing at these moments of October 2026 ("09T06:45")."""
    return [record(finished_at=f"2026-10-{moment}:00-05:00") for moment in moments]


AT_6_50 = datetime(2026, 10, 10, 6, 50, tzinfo=config.BOGOTA_TZ)


def test_a_scheduled_sweep_that_stopped_coming_is_a_warning():
    """GitHub's schedule never fired here while the repository was private: the 3:00 sweep (9 Oct 2026) missing two
    days in a row is reported, which healthchecks.io can't tell while the other two still run."""
    every_sweep = runs_at("08T03:40", "08T06:50", "08T21:20", "09T03:35", "09T06:45", "09T21:15", "10T06:50")
    assert health.missed_sweeps(every_sweep, AT_6_50) == []
    without_3 = [run for run in every_sweep if "T03" not in run.finished_at]
    assert health.missed_sweeps(without_3, AT_6_50) == ["03:00"]
    assert levels(check(without_3[-1], without_3[:-1])) == {"missed-sweep:03:00": "warning"}
    one_day = runs_at("08T06:50", "08T21:20", "09T06:45", "09T21:15", "10T03:30", "10T06:50")
    assert health.missed_sweeps(one_day, AT_6_50) == []  # missed once only (the first night, say)


def test_a_run_the_quota_stopped_says_why_and_how_its_reads_went():
    reads = ReadsSummary(
        accounts=28, mean_seconds=4.6, median_seconds=4.3, max_seconds=9.3, mean_cost=3.4, max_cost=6,
        max_cost_account="salsa.club",
    )  # fmt: skip
    stopped = record(rate_limited=True, instagram_stop="forecast", instagram_reads=reads, skipped_accounts=["a", "b"])
    (finding,) = check(stopped)
    why = "the next read would have passed 98%; Meta took a median 4.3 s a read, 3.4% of the quota each"
    assert why in finding.text
    assert "2 accounts wait" in finding.text
    (finding,) = check(record(rate_limited=True, instagram_stop="meta"))
    assert "(Meta's own rate limit)" in finding.text


def test_a_sweep_the_history_doesnt_reach_isnt_judged():
    assert health.missed_sweeps(runs_at("10T03:20", "10T06:50"), AT_6_50) == []
