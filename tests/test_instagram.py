"""Instagram errors and usage: what's a rate limit, what's an account Business Discovery can't see."""

from pa_bailar.instagram import InstagramClient, InstagramError, is_not_visible, is_rate_limited


def test_rate_limits_are_not_mistaken_for_personal_accounts():
    app_limit = InstagramError("(#4) Application request limit reached", code=4)
    assert is_rate_limited(app_limit) and not is_not_visible(app_limit)
    personal = InstagramError("Invalid user id", code=110)
    assert is_not_visible(personal) and not is_rate_limited(personal)
    network = InstagramError("request failed: timeout")
    assert not is_not_visible(network) and not is_rate_limited(network)


def test_app_usage_header_is_read_as_the_highest_percent():
    client = InstagramClient("token", "123")
    client._read_usage('{"call_count": 72, "total_time": 10, "total_cputime": 5}', None)
    assert client.app_usage_percent == 72
    client._read_usage("not json", None)
    assert client.app_usage_percent == 72  # an odd header is ignored


def test_the_business_use_case_header_instagram_sends_now_is_read_too():
    client = InstagramClient("token", "123")
    business = (
        '{"1251651414708598": [{"type": "instagram", "call_count": 12, "total_cputime": 3, "total_time": 40,'
        ' "estimated_time_to_regain_access": 0}]}'
    )
    client._read_usage(None, business)
    assert client.app_usage_percent == 40
    client._read_usage(None, None)
    assert client.app_usage_percent == 40  # no header: the last value stays


def test_each_measure_and_the_runs_peak_are_kept():
    """Which of Meta's measures a run peaked on (calls, CPU time, total time) decides what to change (7 Oct 2026)."""
    client = InstagramClient("token", "123")
    reading = '{{"1": [{{"type": "instagram", "call_count": {}, "total_cputime": {}, "total_time": {}}}]}}'
    client._read_usage(None, reading.format(20, 40, 30))
    client._read_usage(None, reading.format(31, 90, 77))
    client._read_usage(None, reading.format(1, 2, 3))  # the window drained
    assert client.app_usage_percent == 3 and client.usage_detail == {
        "call_count": 1,
        "total_cputime": 2,
        "total_time": 3,
    }
    assert client.peak_usage_percent == 90
    assert client.peak_usage_detail == {"call_count": 31, "total_cputime": 90, "total_time": 77}


def test_access_tokens_never_reach_error_text():
    from pa_bailar.instagram import redact

    text = "HTTPSConnectionPool: Max retries with url: /v26.0/1?fields=x&access_token=EAAB123secret (Caused by…)"
    assert "EAAB123secret" not in redact(text) and "access_token=***" in redact(text)


def test_the_app_secret_and_exchanged_tokens_never_reach_error_text():
    from pa_bailar.instagram import redact

    text = "/oauth/access_token?grant_type=fb_exchange_token&client_secret=s3cr3t&fb_exchange_token=EAAshort"
    assert "s3cr3t" not in redact(text) and "EAAshort" not in redact(text)
    assert "client_secret=***" in redact(text) and "grant_type=fb_exchange_token" in redact(text)


def test_refresh_token_errors_never_show_the_secrets(monkeypatch):
    import pytest
    import requests

    from pa_bailar.commands import refresh_token

    def unreachable(url, params, timeout):
        raise requests.ConnectionError(f"Max retries with url: {url}?client_secret={params['client_secret']}")

    monkeypatch.setattr(refresh_token.requests, "get", unreachable)
    with pytest.raises(SystemExit) as raised:
        refresh_token.graph_get("oauth/access_token", client_secret="s3cr3t")
    assert "s3cr3t" not in str(raised.value) and "client_secret=***" in str(raised.value)


def test_a_timestamp_written_like_the_api_reads_back_the_same():
    from datetime import datetime

    from pa_bailar import config
    from pa_bailar.instagram import api_timestamp, published_at

    moment = datetime(2026, 10, 4, 18, 30, 5, tzinfo=config.BOGOTA_TZ)
    assert api_timestamp(moment) == "2026-10-04T23:30:05+0000"
    assert published_at({"timestamp": api_timestamp(moment)}) == moment
