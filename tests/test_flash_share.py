"""Flash's few daily requests: shared between the sweeps of a quota day, and spent on the soonest events first (the
owner, 6 Oct 2026)."""

from datetime import UTC, datetime, timedelta

import pytest

from pa_bailar import config, gemini
from pa_bailar.gemini import QuotaExhaustedError
from pa_bailar.pipeline.sweep import flash_reserve, later_sweeps_in_quota_day, upgrade_urgency
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
        (bogota(6, 2), 3),  # past Pacific midnight (2:00 Bogotá), a run by hand: the day's three sweeps are later
        (bogota(6, 2, 40), 2),  # the 3:00 sweep a little early: itself, then 6:30 and 21:00
        (
            bogota(6, 20, 5),
            1,
        ),  # a run by hand before the evening's: it keeps its share (it took it all at a 60' margin)
        (bogota(6, 3, 10), 2),  # the 3:00 sweep, first of the quota day
        (bogota(6, 1, 30), 0),  # before Pacific midnight: the quota day of yesterday's sweeps, all done
    ],
)
def test_the_later_sweeps_of_the_quota_day(now, later):
    assert later_sweeps_in_quota_day(now.astimezone(UTC)) == later


@pytest.mark.parametrize(
    ("now", "reserve"),
    [
        (bogota(10, 3, 10), 2 / 3),  # the first sweep of the quota day leaves the 6:30 and 21:00 ones a third each
        (bogota(10, 6, 40), 1 / 3),  # the 6:30 one leaves the evening's third
        (bogota(10, 21, 5), 0),  # the evening's is the last: what's left is its own
        (bogota(10, 13), 1 / 3),  # a manual run at midday leaves the evening its third
        # The Pacific's winter (from 1 Nov): the quota day starts at 3:00 Bogotá sharp, and cron-job.org's 3:00 call (on
        # the minute, the run seconds to minutes after) is in it; a run just before is still in the day before, whose
        # sweeps are all done.
        (datetime(2026, 11, 15, 3, 5, tzinfo=config.BOGOTA_TZ), 2 / 3),
        (datetime(2026, 11, 15, 2, 50, tzinfo=config.BOGOTA_TZ), 0),
    ],
)
def test_each_sweep_leaves_the_later_ones_an_equal_share_of_flash(now, reserve):
    assert flash_reserve(now.astimezone(UTC)) == pytest.approx(reserve)


def test_three_sweeps_split_flash_in_thirds_and_pass_on_what_they_leave(tmp_path, monkeypatch):
    """Each Flash model's daily budget (18 usable of 20) split by the three sweeps' reserves: 6 each at most, 12 of
    the two models' 36 per sweep; what one leaves unused, the next can take."""
    monkeypatch.setattr(config, "GEMINI_USAGE_FILE", tmp_path / "usage.json")
    model = config.FLASH_MODELS[0]

    def spend(used: int, reserve: float) -> int:
        """How many requests a sweep with this reserve can make after `used`."""
        pool = gemini.ModelPool("unused-key", client=object())
        pool._used[model] = used
        pool.reserve((model,), reserve)
        made = 0
        while pool.has_budget(model):
            pool._used[model] += 1
            made += 1
        return made

    assert gemini.daily_budget(model) == 18
    assert (spend(0, 2 / 3), spend(6, 1 / 3), spend(12, 0)) == (6, 6, 6)
    assert spend(2, 1 / 3) == 10  # the 3:00 sweep used 2: the 6:30 one may take its other 4 too


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
    monkeypatch.setattr("pa_bailar.pipeline.sweep.later_sweeps_in_quota_day", lambda now: 2)
    extractor = FakeExtractor({})
    run(FakeInstagram({"academia": [], "otra": []}), extractor)
    assert extractor.flash_reserved == pytest.approx(2 / 3)  # the first of the quota day's three sweeps
