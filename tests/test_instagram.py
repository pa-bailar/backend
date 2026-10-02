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
    client._read_usage('{"call_count": 72, "total_time": 10, "total_cputime": 5}')
    assert client.app_usage_percent == 72
    client._read_usage("not json")
    assert client.app_usage_percent == 72  # an odd header is ignored
