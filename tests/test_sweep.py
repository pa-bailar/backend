"""End-to-end sweep with fake Instagram and Gemini: no network, no quota."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from pa_bailar import config, storage
from pa_bailar.commands.sweep import summary_markdown
from pa_bailar.gemini import ExtractionError, QuotaExhaustedError, RejectedRequestError
from pa_bailar.instagram import InstagramError
from pa_bailar.models import PostAnalysis, ProcessedPost, Triage
from pa_bailar.pipeline import Sweep
from tests.factories import event_id, extracted, make_image, media, stored

FLYER_URL = "https://cdn.example/flyer.jpg"
VIDEO_THUMB_URL = "https://cdn.example/video.jpg"


def ago(days: float) -> str:
    """Instagram-style timestamp `days` before now, so tests don't age out of the sweep windows."""
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+0000")


def post(post_id: str, media_type: str = "IMAGE", days_ago: float = 2) -> dict:
    url = {"media_url": FLYER_URL} if media_type == "IMAGE" else {"thumbnail_url": VIDEO_THUMB_URL}
    return {
        "id": post_id,
        "media_type": media_type,
        "timestamp": ago(days_ago),
        "permalink": f"https://www.instagram.com/p/{post_id}/",
        "caption": "caption",
        **url,
    }


class FakeInstagram:
    def __init__(self, posts_by_account: dict[str, list[dict] | Exception]):
        self.posts_by_account = posts_by_account
        self.limits: dict[str, list[int]] = {}

    def check_token(self) -> str:
        return "me"

    def fetch_recent_posts(self, account: str, limit: int = config.POSTS_PER_ACCOUNT) -> list[dict]:
        self.limits.setdefault(account, []).append(limit)
        result = self.posts_by_account[account]
        if isinstance(result, Exception):
            raise result
        return result[:limit]


class FakeExtractor:
    """Prepared answers per post id. Triage says "event" unless the post id is in `not_events`."""

    def __init__(
        self,
        analyses: dict[str, PostAnalysis],
        not_events: set[str] = frozenset(),
        flash_available: bool = True,
        out_of_quota: bool = False,
        rejected: frozenset[str] = frozenset(),
        failing: frozenset[str] = frozenset(),
        unavailable: tuple[str, ...] = (),
    ):
        self.analyses = analyses
        self.not_events = not_events
        self.flash_available = flash_available
        self.out_of_quota = out_of_quota
        self.rejected = rejected  # post ids Gemini refuses (e.g. an image it can't read)
        self.failing = failing  # post ids where every model fails (busy, bad answers): an error, retried
        self.unavailable = unavailable  # models Gemini says this key can't use
        self.known_seen: dict[str, list[str]] = {}
        self.extracted_posts: list[str] = []

    def can_extract_with_flash(self) -> bool:
        return self.flash_available

    def can_analyze(self) -> bool:
        return not self.out_of_quota

    def models_unavailable(self) -> list[str]:
        return list(self.unavailable)

    def requests_this_run(self) -> dict[str, int]:
        return {"fake-flash": len(self.extracted_posts)}

    def triage(self, account, post, published, images):
        if self.out_of_quota:
            raise QuotaExhaustedError("no quota")
        return Triage(is_event_post=post["id"] not in self.not_events, reason="triage"), "fake-lite"

    def extract(self, account, post, published, images, known_events, allow_provisional=True):
        if self.out_of_quota:
            raise QuotaExhaustedError("no quota")
        if post["id"] in self.failing:
            raise ExtractionError("every model failed")
        if post["id"] in self.rejected:
            raise RejectedRequestError("400 bad image")
        self.known_seen[post["id"]] = [event.id for event in known_events]
        self.extracted_posts.append(post["id"])
        if self.flash_available:
            return self.analyses[post["id"]], "fake-flash", False
        if not allow_provisional:
            raise QuotaExhaustedError("flash out of quota")
        return self.analyses[post["id"]], "fake-lite", True


@pytest.fixture(autouse=True)
def two_accounts_and_fake_images(isolated_files, monkeypatch):
    """On top of the shared isolation (conftest.py): two accounts, and images without the network."""
    config.ACCOUNTS_FILE.write_text("academia\n# comment\n@otra\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.download_image", lambda url: make_image())


def run(instagram, extractor, days=7, all_accounts=True):
    """A sweep. Tests read every account (consecutive sweeps), except the ones about whose turn it is."""
    return Sweep(lookback_days=days, instagram=instagram, extractor=extractor, all_accounts=all_accounts).run()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def event_post(post_id: str, **details) -> PostAnalysis:
    return PostAnalysis(is_event_post=True, reason="", events=[extracted(**details)])


# ---------- same event, several posts ----------


def test_flyer_then_video_of_the_same_event_become_one_event_with_two_posts():
    instagram = FakeInstagram({"academia": [post("video", "VIDEO", days_ago=1), post("flyer", days_ago=3)], "otra": []})
    extractor = FakeExtractor(
        {
            "flyer": event_post("flyer", title="Social", start_time="20:00"),
            "video": event_post("video", title="Ven a bailar", same_as=event_id("Social"), start_time=None),
        }
    )

    stats = run(instagram, extractor)

    events = read(config.EVENTS_FILE)
    assert len(events) == 1
    assert [m["post_id"] for m in events[0]["media"]] == ["flyer", "video"]
    assert events[0]["title"] == "Social" and events[0]["start_time"] == "20:00"
    assert extractor.known_seen["video"] == [event_id("Social")]  # Gemini was told about the earlier event
    assert (stats.events_new, stats.events_merged) == (1, 1)


# ---------- what gets published ----------


def test_recurring_and_undated_events_are_not_published():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    analysis = PostAnalysis(
        is_event_post=True,
        reason="",
        events=[extracted(title="Clase", is_recurring=True), extracted(title="Sin fecha", date="sábado")],
    )
    stats = run(instagram, FakeExtractor({"p1": analysis}))
    assert read(config.EVENTS_FILE) == []
    assert stats.events_discarded == 2


def test_posts_ruled_out_by_triage_never_reach_flash():
    instagram = FakeInstagram({"academia": [post("tutorial"), post("flyer")], "otra": []})
    extractor = FakeExtractor({"flyer": event_post("flyer")}, not_events={"tutorial"})
    stats = run(instagram, extractor)
    assert extractor.extracted_posts == ["flyer"]
    assert stats.posts_triaged_out == 1 and stats.posts_analyzed == 2


def test_processed_posts_are_not_sent_to_gemini_again():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1")}))

    second = FakeExtractor({})  # would raise KeyError if asked about p1 again
    stats = run(instagram, second)
    assert stats.posts_analyzed == 0 and second.extracted_posts == []


# ---------- new accounts ----------


def test_new_account_gets_a_deeper_first_sweep_then_the_regular_one():
    old_post = post("old", days_ago=20)  # outside the regular 7 days, inside the 30-day first sweep
    instagram = FakeInstagram({"academia": [post("recent"), old_post], "otra": []})
    extractor = FakeExtractor({"recent": event_post("recent"), "old": event_post("old", title="Mensual")})

    first = run(instagram, extractor)
    assert instagram.limits["academia"] == [config.BACKFILL_POSTS]
    assert sorted(extractor.extracted_posts) == ["old", "recent"]
    assert first.by_account["academia"].backfill is True
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["backfill_done"] is True

    run(instagram, FakeExtractor({}))
    assert instagram.limits["academia"] == [config.BACKFILL_POSTS, config.POSTS_PER_ACCOUNT]


def test_new_account_stays_new_while_posts_are_pending():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    stats = run(instagram, FakeExtractor({}, out_of_quota=True))

    assert stats.pending == 1 and stats.by_account["academia"].pending == 1
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["backfill_done"] is False
    assert "p1" not in storage.load_processed_posts()  # retried on the next run

    run(instagram, FakeExtractor({"p1": event_post("p1")}))
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["backfill_done"] is True


def test_accounts_in_their_regular_sweep_go_before_new_accounts():
    run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))  # both finish their first sweep
    config.ACCOUNTS_FILE.write_text("nueva\nacademia\notra\n", encoding="utf-8")
    instagram = FakeInstagram({"nueva": [], "academia": [], "otra": []})

    run(instagram, FakeExtractor({}))
    assert list(instagram.limits) == ["academia", "otra", "nueva"]  # fetch order


# ---------- quota fallbacks ----------


def test_provisional_extraction_is_upgraded_when_flash_is_back():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})

    first = run(instagram, FakeExtractor({"p1": event_post("p1", title="Leído por Lite")}, flash_available=False))
    assert first.provisional == 1
    assert read(config.PROCESSED_POSTS_FILE)["p1"]["provisional"] is True
    assert read(config.EVENTS_FILE)[0]["title"] == "Leído por Lite"  # shown right away

    second = run(instagram, FakeExtractor({"p1": event_post("p1", title="Leído por Flash")}))
    assert second.upgraded == 1 and second.events_new == 0
    assert read(config.PROCESSED_POSTS_FILE)["p1"]["provisional"] is False
    events = read(config.EVENTS_FILE)
    assert len(events) == 1 and events[0]["title"] == "Leído por Flash"
    assert events[0]["id"] == event_id("Leído por Lite")  # the URL shared meanwhile keeps working


def test_provisional_posts_wait_while_flash_is_still_out():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1")}, flash_available=False))
    second = FakeExtractor({"p1": event_post("p1")}, flash_available=False)
    run(instagram, second)
    assert second.extracted_posts == []  # no wasted request


# ---------- failures and reporting ----------


def test_one_account_failing_does_not_stop_the_others_and_meta_is_written():
    instagram = FakeInstagram({"academia": InstagramError("not a business account"), "otra": [post("p1")]})
    stats = run(instagram, FakeExtractor({"p1": event_post("p1")}))

    assert stats.failed_accounts == 1 and stats.events_new == 1
    meta = read(config.META_FILE)
    assert meta["schema_version"] == 1 and meta["generated_at"]
    assert meta["accounts"] == ["academia", "otra"]  # every account swept, with or without events
    assert meta["stats"]["by_account"]["academia"]["fetch_failed"] is True
    summary = summary_markdown(stats)
    assert "@academia" in summary and "Gemini requests" in summary


# ---------- retention ----------


def days_ago_date(days: int) -> str:
    return (datetime.now(config.BOGOTA_TZ) - timedelta(days=days)).date().isoformat()


def processed_record(days: int) -> ProcessedPost:
    when = datetime.now(config.BOGOTA_TZ) - timedelta(days=days)
    return ProcessedPost(
        account="academia", permalink="x", processed_at=when.isoformat(timespec="seconds"),
        is_event_post=True, reason="", model="fake-flash",
    )  # fmt: skip


def test_past_events_expire_with_their_flyers_and_old_post_records_are_forgotten():
    old = stored("old-0", posts=[media("old")], date=days_ago_date(config.EVENT_RETENTION_DAYS + 1))
    recent = stored("recent-0", posts=[media("recent")], date=days_ago_date(config.EVENT_RETENTION_DAYS - 1))
    storage.save_events([old, recent])
    config.FLYERS_DIR.mkdir(parents=True)
    for post_id in ("old", "recent"):
        (config.FLYERS_DIR / f"{post_id}-0.webp").write_bytes(b"webp")
    storage.save_processed_posts(
        {"forgotten": processed_record(config.PROCESSED_RETENTION_DAYS + 1), "kept": processed_record(10)}
    )

    stats = run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))

    assert [event.id for event in storage.load_events()] == ["recent-0"]
    assert sorted(path.name for path in config.FLYERS_DIR.iterdir()) == ["recent-0.webp"]
    assert list(storage.load_processed_posts()) == ["kept"]
    assert (stats.events_expired, stats.flyers_removed, stats.processed_forgotten) == (1, 1, 1)


def test_post_records_inside_a_long_manual_lookback_are_kept():
    storage.save_processed_posts({"p": processed_record(config.PROCESSED_RETENTION_DAYS + 5)})
    run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}), days=config.PROCESSED_RETENTION_DAYS + 10)
    assert list(storage.load_processed_posts()) == ["p"]


# ---------- edited captions and the run's time budget ----------


def test_an_edited_caption_is_analyzed_again_and_keeps_the_event_url():
    first = post("p1")
    run(FakeInstagram({"academia": [first], "otra": []}), FakeExtractor({"p1": event_post("p1", venue=None)}))
    event_id = read(config.EVENTS_FILE)[0]["id"]

    edited = {**first, "caption": "Ahora con lugar: Escuela del Mambo"}
    extractor = FakeExtractor({"p1": event_post("p1", venue="Escuela del Mambo")})
    stats = run(FakeInstagram({"academia": [edited], "otra": []}), extractor)

    events = read(config.EVENTS_FILE)
    assert stats.reanalyzed == 1 and len(events) == 1
    assert events[0]["venue"] == "Escuela del Mambo" and events[0]["id"] == event_id

    unchanged = run(FakeInstagram({"academia": [edited], "otra": []}), FakeExtractor({}))
    assert unchanged.reanalyzed == 0  # same caption: no Gemini request


def test_posts_analyzed_before_fingerprints_get_one_without_a_new_analysis():
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    records = read(config.PROCESSED_POSTS_FILE)
    records["p1"]["caption_hash"] = None
    config.PROCESSED_POSTS_FILE.write_text(json.dumps(records), encoding="utf-8")

    extractor = FakeExtractor({})
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), extractor)
    assert extractor.extracted_posts == [] and read(config.PROCESSED_POSTS_FILE)["p1"]["caption_hash"]


def test_no_new_gemini_work_starts_after_the_time_budget(monkeypatch):
    monkeypatch.setattr(config, "MAX_RUN_MINUTES", 0)
    extractor = FakeExtractor({"p1": event_post("p1")})
    stats = run(FakeInstagram({"academia": [post("p1")], "otra": []}), extractor)
    assert extractor.extracted_posts == [] and stats.pending == 1
    assert "p1" not in storage.load_processed_posts()  # analyzed on the next run


def test_a_rate_limit_stops_the_sweep_instead_of_spending_more_calls():
    limited = InstagramError("(#4) Application request limit reached", code=4)
    instagram = FakeInstagram({"academia": limited, "otra": [post("p1")]})
    stats = run(instagram, FakeExtractor({"p1": event_post("p1")}))
    assert list(instagram.limits) == ["academia"] and stats.accounts == 1 and stats.failed_accounts == 1


# ---------- posts that can't be processed ----------


def test_a_post_gemini_rejects_is_recorded_once_instead_of_retried_forever():
    instagram = FakeInstagram({"academia": [post("bad")], "otra": []})
    stats = run(instagram, FakeExtractor({}, rejected=frozenset({"bad"})))
    assert stats.errors == 1 and stats.pending == 0
    assert "rechazado" in storage.load_processed_posts()["bad"].reason
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["backfill_done"] is True  # the first sweep can finish

    again = FakeExtractor({}, rejected=frozenset({"bad"}))
    run(instagram, again)
    assert again.extracted_posts == []  # not sent to Gemini again


def test_a_flyer_that_cant_be_saved_leaves_the_post_pending(monkeypatch):
    def broken_disk(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pa_bailar.pipeline._save_flyers", broken_disk)
    stats = run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    assert stats.pending == 1 and "p1" not in storage.load_processed_posts()
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["backfill_done"] is False


def test_an_unexpected_error_loses_one_account_not_the_run():
    class Broken(FakeInstagram):
        def fetch_recent_posts(self, account, limit=config.POSTS_PER_ACCOUNT):
            if account == "academia":
                raise KeyError("business_discovery")
            return super().fetch_recent_posts(account, limit)

    stats = run(Broken({"academia": [], "otra": [post("p1")]}), FakeExtractor({"p1": event_post("p1")}))
    assert stats.errors == 1 and stats.events_new == 1


# ---------- what became of each post (admin why) ----------


def test_each_analyzed_post_records_what_became_of_it():
    posts = [post("new"), post("again", "VIDEO"), post("weekly"), post("tutorial")]
    instagram = FakeInstagram({"academia": posts, "otra": []})
    weekly = PostAnalysis(is_event_post=True, reason="", events=[extracted(title="Clase", is_recurring=True)])
    extractor = FakeExtractor(
        {"new": event_post("new"), "again": event_post("again", same_as=event_id(extracted().title)), "weekly": weekly},
        not_events={"tutorial"},
    )
    run(instagram, extractor)

    records = storage.load_processed_posts()
    assert (records["new"].outcome, records["new"].event_ids) == ("event", [event_id(extracted().title)])
    assert (records["again"].outcome, records["again"].event_ids) == ("merged", [event_id(extracted().title)])
    assert (records["weekly"].outcome, records["weekly"].detail) == ("discarded", "recurrente")
    assert records["tutorial"].outcome == "not_event"


def test_waiting_for_quota_is_not_an_error():
    instagram = FakeInstagram({"academia": [post("p1"), post("p2")], "otra": []})
    stats = run(instagram, FakeExtractor({}, out_of_quota=True))
    assert stats.pending == 2 and stats.errors == 0


def test_posts_where_every_model_fails_are_errors_and_retried():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    stats = run(instagram, FakeExtractor({}, failing=frozenset({"p1"})))
    assert stats.pending == 1 and stats.errors == 1
    assert "p1" not in storage.load_processed_posts()


def test_models_this_key_cant_use_are_reported():
    stats = run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}, unavailable=("gemini-3.8-flash",)))
    assert stats.models_unavailable == ["gemini-3.8-flash"]


# ---------- Instagram's quota ----------


def test_the_sweep_stops_before_instagrams_limit():
    instagram = FakeInstagram({"academia": [], "otra": []})
    instagram.app_usage_percent = config.INSTAGRAM_USAGE_STOP
    stats = run(instagram, FakeExtractor({}))
    assert stats.rate_limited and stats.accounts == 0


# ---------- whose turn it is: each account about once a day ----------


def swept(hours_ago: float, latest_post_days_ago: int = 1) -> dict:
    now = config.now_bogota()
    return {
        "first_seen": "2026-01-01",
        "backfill_done": True,
        "last_swept_at": (now - timedelta(hours=hours_ago)).isoformat(timespec="seconds"),
        "latest_post": (now - timedelta(days=latest_post_days_ago)).date().isoformat(),
    }


def turn(states: dict, accounts: str = "academia\notra\n") -> list[str]:
    """The accounts a scheduled sweep reads, in order, given each one's state."""
    config.ACCOUNTS_FILE.write_text(accounts, encoding="utf-8")
    storage.write_json(config.ACCOUNT_STATE_FILE, states)
    instagram = FakeInstagram({name: [] for name in accounts.split()})
    run(instagram, FakeExtractor({}), all_accounts=False)
    return list(instagram.limits)


def test_an_account_is_read_once_a_day():
    assert turn({"academia": swept(21), "otra": swept(3)}) == ["academia"]  # otra was read this morning
    assert turn({"academia": swept(3), "otra": swept(3)}) == []


def test_the_longest_waiting_go_first():
    assert turn({"academia": swept(25), "otra": swept(60)}) == ["otra", "academia"]


def test_quiet_accounts_take_their_turn_every_other_day_but_never_drop_out():
    quiet = config.QUIET_AFTER_DAYS + 5
    assert turn({"academia": swept(30, latest_post_days_ago=quiet), "otra": swept(30)}) == ["otra"]
    assert turn({"academia": swept(50, latest_post_days_ago=quiet), "otra": swept(3)}) == ["academia"]


def test_reading_an_account_starts_its_next_turn():
    assert turn({"academia": swept(30), "otra": swept(30)}) == ["academia", "otra"]
    assert turn(storage.read_json(config.ACCOUNT_STATE_FILE, {})) == []  # just read: their turn is tomorrow


def test_each_sweep_reads_its_share_and_the_rest_go_first_next_time(monkeypatch):
    monkeypatch.setattr(config, "EXTRA_ACCOUNTS_PER_RUN", 0)
    names = [f"a{i}" for i in range(6)]
    accounts = "\n".join(names) + "\n"
    states = {name: swept(30 + i) for i, name in enumerate(names)}  # a5 waited longest
    first = turn(states, accounts)
    assert first == ["a5", "a4", "a3"]  # half: two sweeps a day
    second = turn(storage.read_json(config.ACCOUNT_STATE_FILE, {}), accounts)
    assert second == ["a2", "a1", "a0"]


def test_an_account_instagrams_limit_didnt_reach_stays_due():
    states = {"academia": swept(30), "otra": swept(30)}
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    storage.write_json(config.ACCOUNT_STATE_FILE, states)
    limited = InstagramError("(#4) Application request limit reached", code=4)
    stats = run(FakeInstagram({"academia": limited, "otra": []}), FakeExtractor({}), all_accounts=False)
    assert stats.rate_limited
    assert turn(storage.read_json(config.ACCOUNT_STATE_FILE, {})) == ["academia", "otra"]
