"""Sweep health checks: rules over the run and the runs before it."""

from datetime import date, timedelta

from pa_bailar import health
from pa_bailar.health import RunRecord
from pa_bailar.pipeline import AccountStats, RunStats
from tests.factories import stored

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
