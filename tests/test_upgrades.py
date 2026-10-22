"""Flash re-reads the lighter models' readings beyond the accounts' turns (17 Oct 2026): since read-ahead (#189) the
6:30 sweep usually reads no account, so its share of Flash went unused while provisional posts waited, and a
provisional post older than the lookback was never fetched again."""

from datetime import timedelta

import pytest

from pa_bailar import config, health, storage
from pa_bailar.models import ProcessedPost
from pa_bailar.pipeline.common import caption_hash
from pa_bailar.pipeline.sweep import upgrade_read_depth, waiting_for_flash
from tests.factories import media, stored
from tests.test_sweep import (
    FakeExtractor,
    FakeInstagram,
    event_post,
    post,
    read,
    run,
    two_accounts_and_fake_images,  # noqa: F401  (autouse: two accounts, images offline)
)

NOW = config.now_bogota()


def day(offset: int) -> str:
    return (NOW.date() + timedelta(days=offset)).isoformat()


def account_state(hours_ago: float) -> dict:
    return {
        "first_seen": "2026-01-01",
        "backfill_done": True,
        "last_swept_at": (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds"),
        "latest_post": NOW.date().isoformat(),
    }


def record(
    post_id: str, account: str, read_days_ago: float, provisional: bool = True, events: tuple[str, ...] = ()
) -> ProcessedPost:
    return ProcessedPost(
        account=account,
        permalink=f"https://www.instagram.com/p/{post_id}/",
        processed_at=(NOW - timedelta(days=read_days_ago)).isoformat(timespec="seconds"),
        is_event_post=bool(events),
        reason="",
        model="fake-lite" if provisional else "fake-flash",
        provisional=provisional,
        caption_hash=caption_hash(post(post_id)),
        outcome="event" if events else "not_event",
        event_ids=list(events),
    )


def on_record(*provisional: tuple[str, str, str, float], due: tuple[str, ...] = (), others: dict | None = None):
    """The state a sweep finds: the accounts read an hour ago (not their turn) unless `due`, and these provisional
    posts, each (post id, account, its event's date, days since it was read), with their events on the site."""
    storage.write_json(
        config.ACCOUNT_STATE_FILE,
        {name: account_state(23 if name in due else 1) for name in ("academia", "otra")},
    )
    events, records = [], dict(others or {})
    for post_id, account, date, read_days_ago in provisional:
        events.append(
            stored(f"evento-{post_id}", account, posts=[media(post_id)], title=f"Evento {post_id}", date=date)
        )
        records[post_id] = record(post_id, account, read_days_ago, events=(f"evento-{post_id}",))
    storage.save_events(events)
    storage.save_processed_posts(records)


def flash_reads(*post_ids: str, date: str) -> dict:
    return {
        post_id: event_post(post_id, title=f"Evento {post_id}", date=date, start_time="21:00") for post_id in post_ids
    }


class FlashFor(FakeExtractor):
    """Flash with `requests` left for upgrades (its share of the day)."""

    def __init__(self, requests: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flash_left = requests

    def can_upgrade(self) -> bool:
        return self.flash_left > 0

    def extract(self, account, post, published, images, known_events, allow_provisional=True, rules=""):
        if not allow_provisional:
            self.flash_left -= 1
        return super().extract(account, post, published, images, known_events, allow_provisional, rules)


def provisional(post_id: str) -> bool:
    return read(config.PROCESSED_POSTS_FILE)[post_id]["provisional"]


def test_a_sweep_with_no_account_due_reads_for_flash_the_provisional_posts_of_upcoming_events():
    """17 Oct 2026: the 6:30 sweep read no account, upgraded nothing, and its third of Flash went unused while 32
    provisional posts waited. Such a read isn't the account's turn: nothing else of it is read, its turn stays."""
    on_record(("p1", "academia", day(1), 2))
    before = read(config.ACCOUNT_STATE_FILE)["academia"]
    instagram = FakeInstagram(
        {"academia": [post("nuevo", days_ago=0.1), post("p1", days_ago=2)], "otra": []}, usage=[21]
    )
    extractor = FakeExtractor(flash_reads("p1", date=day(1)))

    stats = run(instagram, extractor, all_accounts=False)

    assert instagram.limits == {"academia": [config.POSTS_PER_ACCOUNT]}
    assert (stats.accounts, stats.upgrade_reads, stats.upgraded) == (0, 1, 1)
    assert not provisional("p1") and read(config.EVENTS_FILE)[0]["start_time"] == "21:00"
    assert extractor.extracted_posts == ["p1"] and "nuevo" not in read(config.PROCESSED_POSTS_FILE)  # not its turn
    after = read(config.ACCOUNT_STATE_FILE)["academia"]
    for turn_field in ("last_swept_at", "latest_post", "backfill_done"):  # the evening sweep keeps its accounts
        assert after[turn_field] == before[turn_field]
    record_ = health.record_of(stats, ["academia", "otra"])
    assert (record_.accounts, record_.read_accounts, record_.upgrade_reads) == (0, [], 1)
    assert stats.instagram_reads is not None and stats.instagram_reads.accounts == 1  # its cost, like any read


def test_the_soonest_event_gets_flash_first_up_to_its_share():
    on_record(("lejos", "academia", day(12), 2), ("cerca", "otra", day(1), 2))
    instagram = FakeInstagram({"academia": [post("lejos")], "otra": [post("cerca")]})
    analyses = flash_reads("lejos", date=day(12)) | flash_reads("cerca", date=day(1))

    stats = run(instagram, FlashFor(1, analyses), all_accounts=False)

    assert list(instagram.limits) == ["otra"]  # no read for a post Flash couldn't re-read
    assert stats.upgraded == 1 and not provisional("cerca") and provisional("lejos")


def test_a_read_for_flash_waits_its_turn_behind_a_sooner_post_the_turn_fetched_and_goes_before_a_later_one():
    on_record(("tarde", "academia", day(12), 2), ("pronto", "otra", day(1), 2), due=("academia",))
    instagram = FakeInstagram({"academia": [post("tarde")], "otra": [post("pronto")]})
    analyses = flash_reads("tarde", date=day(12)) | flash_reads("pronto", date=day(1))

    stats = run(instagram, FlashFor(1, analyses), all_accounts=False)

    assert (stats.accounts, stats.upgrade_reads) == (1, 1)
    assert instagram.limits == {"academia": [config.POSTS_PER_ACCOUNT], "otra": [config.POSTS_PER_ACCOUNT]}
    assert not provisional("pronto") and provisional("tarde")


def older_than_the_lookback(due: tuple[str, ...]) -> tuple[FakeInstagram, int]:
    """La-33's night of 21 Nov, read on 3 Oct: a provisional post of an upcoming event, 14 days old, with 12 posts
    read since. The read reaches back to it: those 13 and the margin."""
    others = {f"n{i}": record(f"n{i}", "academia", i, provisional=False) for i in range(1, 13)}
    on_record(("viejo", "academia", day(35), 14), due=due, others=others)
    posts = [post(f"n{i}", days_ago=i) for i in range(1, 13)] + [post("viejo", days_ago=14)]
    posts += [post(f"antes{i}", days_ago=15 + i) for i in range(10)]
    return FakeInstagram({"academia": posts, "otra": []}), 13 + config.UPGRADE_READ_MARGIN_POSTS


@pytest.mark.parametrize("due", [(), ("academia",)], ids=["beyond its turn", "in its turn"])
def test_a_provisional_post_older_than_the_lookback_is_reached(due):
    instagram, depth = older_than_the_lookback(due)

    stats = run(instagram, FakeExtractor(flash_reads("viejo", date=day(35))), all_accounts=False)

    assert instagram.limits == {"academia": [depth]}
    assert stats.upgraded == 1 and not provisional("viejo")
    assert stats.upgrade_reads == (0 if due else 1)


def test_past_events_stories_and_unfollowed_accounts_are_not_read_for():
    on_record(
        ("pasado", "academia", day(-2), 2),
        ("story-0123456789abcdef", "otra", day(1), 2),  # no read returns a story
        ("ajeno", "desconocida", day(1), 2),  # not in accounts.txt (FakeInstagram would fail reading it)
    )
    instagram = FakeInstagram({"academia": [post("pasado")], "otra": []})

    stats = run(instagram, FakeExtractor(flash_reads("pasado", date=day(-2))), all_accounts=False)

    assert instagram.limits == {} and stats.upgrade_reads == 0


def test_waiting_for_flash_keeps_upcoming_events_soonest_first_and_skips_stories_and_public_ids():
    lighter_reads = [media(post_id) for post_id in ("soon-post", "story-0123456789abcdef", "public-abc")]
    events = {
        "soon": stored("soon", posts=lighter_reads, date=day(1)),
        "later": stored("later", posts=[media("later-post")], date=day(9)),
        "past": stored("past", posts=[media("past-post")], date=day(-3)),
    }
    posts = {
        "later-post": record("later-post", "academia", 1, events=("later",)),
        "soon-post": record("soon-post", "academia", 1, events=("soon",)),
        "past-post": record("past-post", "academia", 1, events=("past",)),
        "flash-post": record("flash-post", "academia", 1, provisional=False, events=("soon",)),
        "story-0123456789abcdef": record("story", "academia", 1, events=("soon",)),
        "public-abc": record("public-abc", "otra", 1, events=("soon",)),
    }
    assert waiting_for_flash(posts, events, day(0)) == {"academia": ["soon-post", "later-post"]}


def test_reads_for_flash_stop_at_the_cap(monkeypatch):
    monkeypatch.setattr(config, "UPGRADE_READS_PER_RUN", 1)
    on_record(("lejos", "academia", day(12), 2), ("cerca", "otra", day(1), 2))
    instagram = FakeInstagram({"academia": [post("lejos")], "otra": [post("cerca")]})
    analyses = flash_reads("lejos", date=day(12)) | flash_reads("cerca", date=day(1))

    stats = run(instagram, FakeExtractor(analyses), all_accounts=False)

    assert list(instagram.limits) == ["otra"] and stats.upgrade_reads == 1


def test_reads_for_flash_stop_before_instagrams_forecast_without_marking_the_run_stopped():
    on_record(("cerca", "otra", day(1), 2))
    instagram = FakeInstagram({"academia": [], "otra": [post("cerca")]})
    instagram.app_usage_percent = config.INSTAGRAM_USAGE_CEILING - 2  # the next read could pass the ceiling

    stats = run(instagram, FakeExtractor(flash_reads("cerca", date=day(1))), all_accounts=False)

    assert instagram.limits == {} and stats.upgrade_reads == 0
    assert not stats.rate_limited and stats.instagram_stop is None  # no account of a turn waited for it


def test_no_read_for_flash_when_flash_cant_upgrade():
    on_record(("cerca", "otra", day(1), 2))
    instagram = FakeInstagram({"academia": [], "otra": [post("cerca")]})

    stats = run(instagram, FakeExtractor(flash_reads("cerca", date=day(1)), flash_available=False), all_accounts=False)

    assert instagram.limits == {} and stats.upgrade_reads == 0 and provisional("cerca")


def test_a_post_the_read_doesnt_return_is_counted_and_left_as_read():
    on_record(("borrado", "otra", day(1), 2))
    instagram = FakeInstagram({"academia": [], "otra": [post("otro")]})

    stats = run(instagram, FakeExtractor({}), all_accounts=False)

    assert instagram.limits == {"otra": [config.POSTS_PER_ACCOUNT]}  # read once, no loop
    assert (stats.upgrade_reads, stats.upgrade_misses, stats.upgraded) == (1, 1, 0) and provisional("borrado")


def test_a_read_for_flash_goes_back_to_the_oldest_post_within_bounds():
    records = [record(f"r{i}", "academia", i) for i in range(80)]
    oldest = records[7].processed_at
    assert upgrade_read_depth(records, oldest) == 8 + config.UPGRADE_READ_MARGIN_POSTS
    assert upgrade_read_depth(records, records[0].processed_at) == config.POSTS_PER_ACCOUNT  # at least a turn's
    assert upgrade_read_depth(records, records[-1].processed_at) == config.UPGRADE_READ_MAX_POSTS


# ---------- posts not worth a read (22 Oct 2026) ----------


def set_misses(post_id: str, misses: int) -> None:
    records = storage.load_processed_posts()
    records[post_id].upgrade_misses = misses
    storage.save_processed_posts(records)


def misses(post_id: str) -> int:
    return read(config.PROCESSED_POSTS_FILE)[post_id]["upgrade_misses"]


def test_a_post_the_reads_never_return_is_given_up_after_a_few():
    """@salsaysonoficial's reel was "not among its last 16 posts" in each of the 15 sweeps of 17-22 Oct 2026, each
    time a read for Flash (1-2% of Instagram's hour). Now it's given up after UPGRADE_MISSES_BEFORE_GIVING_UP."""
    on_record(("perdido", "otra", day(2), 2))
    instagram = FakeInstagram({"academia": [], "otra": [post("otro")]})

    for n in range(1, config.UPGRADE_MISSES_BEFORE_GIVING_UP + 1):
        stats = run(instagram, FakeExtractor({}), all_accounts=False)
        assert (stats.upgrade_reads, stats.upgrade_misses, misses("perdido")) == (1, 1, n)

    stats = run(instagram, FakeExtractor({}), all_accounts=False)
    assert (stats.upgrade_reads, stats.upgrade_misses) == (0, 0)
    assert len(instagram.limits["otra"]) == config.UPGRADE_MISSES_BEFORE_GIVING_UP and provisional("perdido")


def test_a_given_up_post_a_turns_read_finds_is_still_upgraded():
    on_record(("perdido", "otra", day(2), 2), due=("otra",))
    set_misses("perdido", config.UPGRADE_MISSES_BEFORE_GIVING_UP)
    instagram = FakeInstagram({"academia": [], "otra": [post("perdido", days_ago=2)]})

    stats = run(instagram, FakeExtractor(flash_reads("perdido", date=day(2))), all_accounts=False)

    assert (stats.accounts, stats.upgrade_reads, stats.upgraded) == (1, 0, 1) and not provisional("perdido")


def test_a_post_found_again_starts_its_count_over():
    on_record(("vuelve", "otra", day(2), 2), due=("otra",))
    set_misses("vuelve", 2)
    instagram = FakeInstagram({"academia": [], "otra": [post("vuelve", days_ago=2)]})

    run(instagram, FlashFor(0, flash_reads("vuelve", date=day(2))), all_accounts=False)  # found, no Flash to upgrade

    assert misses("vuelve") == 0 and provisional("vuelve")


def test_records_from_before_the_count_load_with_none():
    storage.write_json(
        config.PROCESSED_POSTS_FILE,
        {"viejo": {"account": "a", "permalink": "x", "processed_at": "2026-10-01T10:00:00-05:00",
                   "is_event_post": True, "reason": "", "model": "m", "provisional": True}},
    )  # fmt: skip
    assert storage.load_processed_posts()["viejo"].upgrade_misses == 0


def merged_reel(flyer_provisional: bool) -> None:
    """A night announced by a flyer and, merged into it, a reel read provisionally (@salsaysonoficial, 17-22 Oct)."""
    storage.write_json(
        config.ACCOUNT_STATE_FILE, {name: account_state(1) for name in ("academia", "otra")}
    )  # not their turn
    storage.save_events([stored("noche", "otra", posts=[media("flyer"), media("reel")], date=day(2))])
    storage.save_processed_posts(
        {
            "flyer": record("flyer", "otra", 3, provisional=flyer_provisional, events=("noche",)),
            "reel": record("reel", "otra", 2, events=("noche",)),
        }
    )


def test_a_post_whose_events_flash_read_through_another_post_is_not_read_for():
    merged_reel(flyer_provisional=False)
    instagram = FakeInstagram({"academia": [], "otra": [post("reel")]})

    stats = run(instagram, FakeExtractor(flash_reads("reel", date=day(2))), all_accounts=False)

    assert instagram.limits == {} and stats.upgrade_reads == 0 and provisional("reel")


def test_a_post_whose_events_only_lighter_models_read_is_still_read_for():
    merged_reel(flyer_provisional=True)
    instagram = FakeInstagram({"academia": [], "otra": [post("flyer"), post("reel")]})

    stats = run(instagram, FakeExtractor(flash_reads("flyer", "reel", date=day(2))), all_accounts=False)

    assert instagram.limits == {"otra": [config.POSTS_PER_ACCOUNT]} and stats.upgrade_reads == 1


def test_waiting_for_flash_skips_given_up_posts_and_events_flash_read_elsewhere():
    events = {
        "noche": stored("noche", posts=[media("flyer"), media("reel")], date=day(2)),
        "taller": stored("taller", posts=[media("perdido")], date=day(3)),
    }
    posts = {
        "flyer": record("flyer", "otra", 3, provisional=False, events=("noche",)),
        "reel": record("reel", "otra", 2, events=("noche",)),
        "perdido": record("perdido", "otra", 2, events=("taller",)),
    }
    assert waiting_for_flash(posts, events, day(0)) == {"otra": ["perdido"]}
    posts["perdido"].upgrade_misses = config.UPGRADE_MISSES_BEFORE_GIVING_UP
    assert waiting_for_flash(posts, events, day(0)) == {}
    posts["flyer"].provisional = True  # only lighter readings of the night: the reel may correct it
    assert waiting_for_flash(posts, events, day(0)) == {"otra": ["flyer", "reel"]}


def test_in_the_turn_such_a_post_comes_after_every_other():
    """A turn's read fetches it anyway: Flash goes to it only when nothing else waits (it may still find the reel isn't
    that night, and take it off)."""
    merged_reel(flyer_provisional=False)
    on_record(("lejos", "otra", day(9), 2), due=("otra",), others=storage.load_processed_posts())
    events = storage.load_events() + [stored("noche", "otra", posts=[media("flyer"), media("reel")], date=day(2))]
    storage.save_events(events)
    instagram = FakeInstagram({"academia": [], "otra": [post("reel"), post("lejos")]})
    analyses = flash_reads("reel", date=day(2)) | flash_reads("lejos", date=day(9))

    extractor = FlashFor(1, analyses)
    stats = run(instagram, extractor, all_accounts=False)
    assert extractor.extracted_posts == ["lejos"] and stats.upgraded == 1 and provisional("reel")

    extractor = FlashFor(1, analyses)
    run(instagram, extractor)  # its turn again
    assert extractor.extracted_posts == ["reel"]  # when nothing else waits
