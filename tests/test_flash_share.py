"""Flash's few daily requests: shared between the sweeps of a quota day, and spent on the soonest events first (the
owner, 6 Oct 2026)."""

from datetime import UTC, datetime, timedelta

import pytest

from pa_bailar import config, gemini
from pa_bailar.gemini import QuotaExhaustedError
from pa_bailar.pipeline.sweep import later_sweeps_in_quota_day, upgrade_urgency
from tests.factories import stored
from tests.test_sweep import (
    FakeExtractor,
    FakeInstagram,
    event_post,
    post,
    read,
    run,
    two_accounts_and_fake_images,  # noqa: F401  (autouse: two accounts, images offline)
)


def bogota(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=config.BOGOTA_TZ)


@pytest.mark.parametrize(
    ("now", "later"),
    [
        (bogota(6, 6, 35), 1),  # the morning sweep: the evening's is the same Pacific day
        (bogota(6, 6, 0), 1),  # started a bit early: it's still the 6:30 one, not a later one
        (bogota(6, 13), 1),  # a manual run at midday leaves the evening its share
        (bogota(6, 21, 5), 0),  # the evening sweep: the next one (6:30) is the next Pacific day
        (bogota(6, 2), 2),  # past Pacific midnight (2:00 Bogotá): both of today's sweeps are to come
    ],
)
def test_the_later_sweeps_of_the_quota_day(now, later):
    assert later_sweeps_in_quota_day(now.astimezone(UTC)) == later


def test_a_reserve_leaves_part_of_a_models_budget_for_later_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "usage.json")
    pool = gemini.ModelPool("unused-key", client=object())
    model = "gemini-3.8-flash"
    pool.reserve((model,), 0.5)
    half = gemini.daily_budget(model) // 2
    pool._used[model] = half - 1
    assert pool.has_budget(model)
    pool._used[model] = half
    assert not pool.has_budget(model)


def test_the_soonest_upcoming_event_comes_first_and_posts_without_one_last():
    today = "2026-10-06"
    events = {
        "tomorrow": stored("tomorrow", date="2026-10-07"),
        "next-week": stored("next-week", date="2026-10-13"),
        "under-way": stored("under-way", date="2026-10-04", end_date="2026-10-08"),
        "past": stored("past", date="2026-10-01"),
    }
    assert upgrade_urgency(["under-way"], events, today) == (0, today)
    assert upgrade_urgency(["next-week", "tomorrow"], events, today) == (0, "2026-10-07")
    assert upgrade_urgency(["past"], events, today) == (1, "")
    assert upgrade_urgency([], events, today) == (1, "")
    assert upgrade_urgency(["gone"], events, today) == (1, "")


class OneFlashLeft(FakeExtractor):
    """Flash with a single request left for upgrades."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flash_left = 1

    def can_upgrade(self) -> bool:
        return self.flash_left > 0

    def extract(self, account, post, published, images, known_events, allow_provisional=True, rules=""):
        if not allow_provisional:  # an upgrade
            if self.flash_left <= 0:
                raise QuotaExhaustedError("flash out of quota")
            self.flash_left -= 1
            self.extracted_posts.append(post["id"])
            return self.analyses[post["id"]], "fake-flash", False
        return super().extract(account, post, published, images, known_events, allow_provisional, rules)


def test_the_last_flash_request_goes_to_the_soonest_event_not_the_first_account():
    soon = (config.now_bogota() + timedelta(days=1)).date().isoformat()
    later = (config.now_bogota() + timedelta(days=12)).date().isoformat()
    instagram = FakeInstagram({"academia": [post("far")], "otra": [post("near")]})
    analyses = {
        "far": event_post("far", title="Taller lejano", date=later),
        "near": event_post("near", title="Social de mañana", date=soon),
    }
    run(instagram, FakeExtractor(analyses, flash_available=False))  # both read by Flash-Lite: provisional
    processed = read(config.PROCESSED_POSTS_FILE)
    assert processed["far"]["provisional"] and processed["near"]["provisional"]

    extractor = OneFlashLeft(analyses, flash_available=False)
    stats = run(instagram, extractor)
    processed = read(config.PROCESSED_POSTS_FILE)
    assert stats.upgraded == 1
    assert processed["near"]["provisional"] is False  # "otra" is read second, but its event is tomorrow
    assert processed["far"]["provisional"] is True  # waits for a later run


def test_a_sweep_leaves_the_later_sweeps_their_share_of_flash(monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.sweep.later_sweeps_in_quota_day", lambda now: 1)
    extractor = FakeExtractor({})
    run(FakeInstagram({"academia": [], "otra": []}), extractor)
    assert extractor.flash_reserved == 0.5
