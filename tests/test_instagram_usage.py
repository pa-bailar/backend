"""What each Instagram read costs and when the sweep stops reading (instagram_usage.py), and what the client measures
per call (instagram.py): Meta's time and the usage after it, each header apart."""

import pytest

from pa_bailar import instagram
from pa_bailar.instagram import APP_HEADER, BUSINESS_HEADER, CallReading, InstagramClient, usage_by_header
from pa_bailar.instagram_usage import ReadCosts

APP = '{"call_count": 28, "total_time": 41, "total_cputime": 25}'
BUSINESS = '{"1": [{"type": "instagram", "call_count": 3, "total_cputime": 2, "total_time": 7}]}'


def call(percent: int, header: str = APP_HEADER, seconds: float = 1.6) -> CallReading:
    return CallReading(seconds, {header: {"total_time": percent, "call_count": 1}})


def test_each_header_is_kept_apart():
    """Meta has used each header (3 and 8 Oct 2026): merged, a read's cost could compare one with the other."""
    usage = usage_by_header(APP, BUSINESS)
    assert usage == {
        APP_HEADER: {"call_count": 28, "total_time": 41, "total_cputime": 25},
        BUSINESS_HEADER: {"call_count": 3, "total_cputime": 2, "total_time": 7},
    }
    reading = CallReading(2.0, usage)
    assert reading.header == APP_HEADER and reading.percent == 41
    assert usage_by_header("not json", BUSINESS) == {BUSINESS_HEADER: usage[BUSINESS_HEADER]}
    assert CallReading(1.0, {}).header is None and CallReading(1.0, {}).percent is None


def test_the_client_measures_each_call(monkeypatch):
    class Answer:
        headers = {"x-app-usage": APP}

        def json(self):
            return {"username": "pa.bailar"}

    clock = iter([100.0, 104.3])
    monkeypatch.setattr(instagram.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(instagram.requests, "get", lambda url, params, timeout: Answer())
    client = InstagramClient("token", "123")
    client.check_token()
    assert client.last_call is not None
    assert client.last_call.seconds == pytest.approx(4.3) and client.last_call.header == APP_HEADER
    assert client.app_usage_percent == 41


def test_before_the_first_cost_the_default_is_expected():
    costs = ReadCosts(ceiling=98, first_cost=4, window=5)
    assert costs.expected_cost() == 4
    assert costs.stop_reason(94) is None and costs.stop_reason(95) == "forecast" and costs.stop_reason(98) == "ceiling"
    first = costs.record("a", call(40))
    assert first.cost is None and costs.expected_cost() == 4  # the first read has nothing before it


def test_the_forecast_is_the_highest_of_the_last_few_reads():
    costs = ReadCosts(ceiling=98, first_cost=4, window=3)
    for percent in (10, 19, 20, 21, 22):  # +9, then +1 three times: the 9 leaves the window
        costs.record("a", call(percent))
    assert costs.expected_cost() == 1
    costs.record("b", call(15))  # older calls left the rolling hour: a negative cost, never a negative forecast
    assert costs.reads[-1].cost == -7 and costs.expected_cost() == 1


def test_a_change_of_header_has_no_cost():
    costs = ReadCosts()
    costs.record("a", call(40, APP_HEADER))
    read = costs.record("b", call(5, BUSINESS_HEADER))
    assert read.before is None and read.cost is None
    assert "5% (X-Business-Use-Case-Usage)" in read.line()
    read = costs.record("c", call(42, APP_HEADER))
    assert read.cost == 2 and read.line() == "Instagram: 1.6 s, 40→42% (+2, X-App-Usage)"


def test_the_summary():
    costs = ReadCosts()
    assert costs.summary() is None
    for account, percent, seconds in (("a", 10, 1.0), ("b", 12, 2.0), ("c", 18, 6.0), ("d", 19, 1.5)):
        costs.record(account, call(percent, seconds=seconds))
    summary = costs.summary()
    assert summary is not None
    assert (summary.accounts, summary.median_seconds, summary.max_seconds) == (4, 1.75, 6.0)
    assert summary.mean_cost == 3.0 and summary.max_cost == 6 and summary.max_cost_account == "c"
    assert summary.headers == {APP_HEADER: 4} and summary.expected_cost == 6
