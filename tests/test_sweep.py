"""End-to-end sweep with fake Instagram and Gemini: no network, no quota."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from pa_bailar import config, storage
from pa_bailar.commands.sweep import summary_markdown
from pa_bailar.gemini import ExtractionError, QuotaExhaustedError, RejectedRequestError
from pa_bailar.ids import new_event_id
from pa_bailar.instagram import InstagramError
from pa_bailar.models import PostAnalysis, ProcessedPost, Triage
from pa_bailar.pipeline import Sweep
from tests.factories import EVENT_DATE, event_id, extracted, make_image, media, stored

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
        self.rules_seen: dict[str, str] = {}  # post id → the account's extra prompt rules (prompts.account_rules)

    def can_extract_with_flash(self) -> bool:
        return self.flash_available

    def can_analyze(self) -> bool:
        return not self.out_of_quota

    def models_unavailable(self) -> list[str]:
        return list(self.unavailable)

    def requests_this_run(self) -> dict[str, int]:
        return {"fake-flash": len(self.extracted_posts)}

    def triage(self, account, post, published, images, rules=""):
        self.rules_seen[post["id"]] = rules
        if self.out_of_quota:
            raise QuotaExhaustedError("no quota")
        return Triage(is_event_post=post["id"] not in self.not_events, reason="triage"), "fake-lite"

    def extract(self, account, post, published, images, known_events, allow_provisional=True, rules=""):
        if self.out_of_quota:
            raise QuotaExhaustedError("no quota")
        if post["id"] in self.failing:
            raise ExtractionError("every model failed")
        if post["id"] in self.rejected:
            raise RejectedRequestError("400 bad image")
        self.known_seen[post["id"]] = [event.id for event in known_events]
        self.rules_seen[post["id"]] = rules
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
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


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

    monkeypatch.setattr("pa_bailar.pipeline.common.save_flyers", broken_disk)
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


def test_dormant_accounts_take_their_turn_once_a_week():
    dormant = config.DORMANT_AFTER_DAYS + 5
    assert turn({"academia": swept(100, latest_post_days_ago=dormant), "otra": swept(3)}) == []  # 4 days: not yet
    assert turn({"academia": swept(170, latest_post_days_ago=dormant), "otra": swept(3)}) == ["academia"]


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


# ---------- review fixes: a broken Gemini key, a cancelled event ----------


def test_a_gemini_key_that_doesnt_work_stops_the_run_without_marking_posts(monkeypatch):
    from pa_bailar.gemini import GeminiKeyError

    extractor = FakeExtractor({"p1": event_post("p1")})

    def broken_key(*args, **kwargs):
        raise GeminiKeyError("API key expired")

    monkeypatch.setattr(extractor, "triage", broken_key)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        run(FakeInstagram({"academia": [post("p1")], "otra": []}), extractor)
    assert "p1" not in storage.load_processed_posts()  # read again once the key is replaced


def test_an_edited_caption_is_extracted_again_without_the_filter_and_a_cancelled_event_leaves_the_site():
    first = post("p1")
    run(FakeInstagram({"academia": [first], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    assert len(read(config.EVENTS_FILE)) == 1

    cancelled = {**first, "caption": "CANCELADO: nos vemos el próximo mes"}
    no_event = PostAnalysis(is_event_post=False, reason="Cancelado", events=[])
    # The filter would call it "not an event" too: skipping it means the extraction decides, and detaches.
    extractor = FakeExtractor({"p1": no_event}, not_events={"p1"})
    run(FakeInstagram({"academia": [cancelled], "otra": []}), extractor)
    assert extractor.extracted_posts == ["p1"]
    assert read(config.EVENTS_FILE) == []


def test_an_edited_caption_of_a_post_recorded_before_outcomes_existed_skips_the_filter():
    """Older records have no outcome: one Gemini called an event post had events, and gets the extraction."""
    first = post("p1")
    run(FakeInstagram({"academia": [first], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    records = read(config.PROCESSED_POSTS_FILE)
    records["p1"]["outcome"] = None
    config.PROCESSED_POSTS_FILE.write_text(json.dumps(records), encoding="utf-8")

    cancelled = {**first, "caption": "CANCELADO"}
    extractor = FakeExtractor({"p1": PostAnalysis(is_event_post=False, reason="Cancelado", events=[])}, {"p1"})
    run(FakeInstagram({"academia": [cancelled], "otra": []}), extractor)
    assert extractor.extracted_posts == ["p1"] and read(config.EVENTS_FILE) == []


# ---------- Gemini's quota and network ----------


def test_a_post_waits_when_the_filter_is_out_of_quota_instead_of_spending_flash(monkeypatch):
    extractor = FakeExtractor({"p1": event_post("p1")})

    def lite_out_of_quota(*args, **kwargs):
        raise QuotaExhaustedError("no quota left today (gemini-3.5-flash-lite)")

    monkeypatch.setattr(extractor, "triage", lite_out_of_quota)
    stats = run(FakeInstagram({"academia": [post("p1")], "otra": []}), extractor)
    assert extractor.extracted_posts == [] and stats.pending == 1 and stats.errors == 0
    assert "p1" not in storage.load_processed_posts()


def test_a_network_timeout_leaves_the_post_pending(monkeypatch):
    extractor = FakeExtractor({"p1": event_post("p1")})

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(extractor, "triage", timeout)  # the filter unavailable: the extraction decides
    monkeypatch.setattr(extractor, "extract", timeout)
    stats = run(FakeInstagram({"academia": [post("p1")], "otra": []}), extractor)
    assert stats.pending == 1 and "p1" not in storage.load_processed_posts()


# ---------- events over several days ----------


def test_events_stored_before_end_dates_existed_still_load():
    event = stored().model_dump(mode="json")
    del event["end_date"]
    config.EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.EVENTS_FILE.write_text(json.dumps([event]), encoding="utf-8")
    [loaded] = storage.load_events()
    assert loaded.end_date is None and loaded.last_day == loaded.date


def test_an_event_over_several_days_keeps_its_first_day_in_its_id_and_expires_after_its_last_day():
    last_day = (datetime.fromisoformat(EVENT_DATE) + timedelta(days=2)).date().isoformat()
    analysis = event_post("p1", title="Congreso de bachata", event_type="congress", end_date=last_day)
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": analysis}))
    [event] = read(config.EVENTS_FILE)
    assert event["id"] == event_id("Congreso de bachata")  # its first day, like any event's
    assert (event["date"], event["end_date"]) == (EVENT_DATE, last_day)


def test_past_events_expire_by_their_last_day():
    retention = config.EVENT_RETENTION_DAYS
    ended_recently = stored(
        "ended-recently", date=days_ago_date(retention + 2), end_date=days_ago_date(retention - 1), posts=[media("a")]
    )
    ended_long_ago = stored(
        "ended-long-ago", date=days_ago_date(retention + 4), end_date=days_ago_date(retention + 1), posts=[media("b")]
    )
    storage.save_events([ended_recently, ended_long_ago])
    stats = run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))
    assert [event.id for event in storage.load_events()] == ["ended-recently"] and stats.events_expired == 1


def test_a_congress_under_way_is_still_a_known_event_for_new_posts():
    congress = stored("congreso", date=days_ago_date(2), end_date=days_ago_date(-2), posts=[media("old")])
    storage.save_events([congress])
    extractor = FakeExtractor({"p1": event_post("p1", same_as="congreso")})
    run(FakeInstagram({"academia": [post("p1", days_ago=0)], "otra": []}), extractor)
    assert extractor.known_seen["p1"] == ["congreso"]


def test_an_accounts_latest_post_is_dated_in_bogota():
    """Instagram's times are UTC: a post at 9 p.m. in Bogotá is that day's, not the next."""
    evening = (config.now_bogota() - timedelta(days=2)).replace(hour=21, minute=0, second=0, microsecond=0)
    late = {**post("p1"), "timestamp": evening.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000")}
    stats = run(FakeInstagram({"academia": [late], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    assert stats.by_account["academia"].latest_post == evening.date().isoformat()
    assert storage.load_account_state()["academia"].latest_post == evening.date().isoformat()


# ---------- Gemini's same_as link needs a day in common (review finding) ----------


def test_a_same_as_link_to_another_day_never_moves_the_event_and_is_flagged():
    later = (datetime.fromisoformat(EVENT_DATE) + timedelta(days=20)).date().isoformat()
    concert = event_post("flyer", title="Concierto de salsa", date=later, start_time="21:00")
    # A newer post (a song release that mentions the concert) linked to it, dated this week.
    release = event_post("song", title="Lanzamiento", same_as=new_event_id("Concierto de salsa", later, set()))
    instagram = FakeInstagram({"academia": [post("song", days_ago=1), post("flyer", days_ago=3)], "otra": []})
    run(instagram, FakeExtractor({"flyer": concert, "song": release}))

    events = {event["title"]: event for event in read(config.EVENTS_FILE)}
    assert events["Concierto de salsa"]["date"] == later  # not moved to the newer post's date
    assert [m["post_id"] for m in events["Concierto de salsa"]["media"]] == ["flyer"]
    assert events["Lanzamiento"]["date"] == EVENT_DATE
    assert any("cambio de fecha" in doubt for doubt in events["Lanzamiento"]["doubts"])


# ---------- only upcoming events in Bogotá (review finding) ----------


def test_an_orchestras_tour_post_read_in_a_new_accounts_first_sweep_publishes_nothing():
    """4 Oct: a new account's 30-day first sweep read a tour post of 17 Sep, and two past concerts abroad (CDMX on
    18 Sep, Veracruz on 19 Sep) came out as events."""
    tour = PostAnalysis(
        is_event_post=True,
        reason="gira por México",
        events=[
            extracted(title="Concierto en CDMX", event_type="concert", date=days_ago_date(16), in_bogota="no"),
            extracted(title="Concierto en Veracruz", event_type="concert", date=days_ago_date(15), in_bogota="no"),
        ],
    )
    stats = run(FakeInstagram({"academia": [post("tour", days_ago=17)], "otra": []}), FakeExtractor({"tour": tour}))
    assert read(config.EVENTS_FILE) == [] and stats.events_discarded == 2
    record = storage.load_processed_posts()["tour"]
    assert (record.outcome, record.detail) == ("discarded", "fuera de Bogotá, ya pasó")


def test_a_new_event_whose_last_day_has_passed_isnt_published():
    passed = event_post("p1", title="Social de ayer", date=days_ago_date(1))
    stats = run(FakeInstagram({"academia": [post("p1", days_ago=3)], "otra": []}), FakeExtractor({"p1": passed}))
    assert read(config.EVENTS_FILE) == [] and stats.events_discarded == 1
    assert storage.load_processed_posts()["p1"].detail == "ya pasó"


def test_an_event_under_way_is_still_published():
    days = {"date": days_ago_date(1), "end_date": days_ago_date(-1)}
    congress = event_post("p1", title="Congreso", event_type="congress", **days)
    run(FakeInstagram({"academia": [post("p1", days_ago=3)], "otra": []}), FakeExtractor({"p1": congress}))
    assert [event["title"] for event in read(config.EVENTS_FILE)] == ["Congreso"]


def test_a_past_event_already_stored_still_takes_its_later_posts_and_rereads():
    yesterday = days_ago_date(1)
    storage.save_events([stored("social-ayer", title="Social", date=yesterday, posts=[media("flyer")])])
    video = event_post("video", title="Social", same_as="social-ayer", date=yesterday)
    run(FakeInstagram({"academia": [post("video", days_ago=2)], "otra": []}), FakeExtractor({"video": video}))
    [event] = read(config.EVENTS_FILE)
    assert sorted(m["post_id"] for m in event["media"]) == ["flyer", "video"]

    # Its own post read again (an edited caption): it keeps its event.
    edited = {**post("video", days_ago=2), "caption": "editado"}
    run(FakeInstagram({"academia": [edited], "otra": []}), FakeExtractor({"video": video}))
    assert sorted(m["post_id"] for m in read(config.EVENTS_FILE)[0]["media"]) == ["flyer", "video"]


def test_an_event_in_another_city_isnt_published_and_an_unknown_city_is_flagged():
    analysis = PostAnalysis(
        is_event_post=True,
        reason="",
        events=[
            extracted(title="Taller en Medellín", in_bogota="no"),
            extracted(title="Social sin ciudad", start_time="21:00", in_bogota="unknown"),
        ],
    )
    stats = run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": analysis}))
    [event] = read(config.EVENTS_FILE)
    assert event["title"] == "Social sin ciudad" and stats.events_discarded == 1
    assert any("Bogotá" in doubt for doubt in event["doubts"])
    assert "in_bogota" not in event  # internal: the stored shape doesn't change


# ---------- a caption edited to "CANCELADO" (review finding) ----------


def cancel(post_dict: dict) -> dict:
    return {**post_dict, "caption": "CANCELADO: lo sentimos"}


CANCELLED = PostAnalysis(is_event_post=False, reason="El evento fue cancelado", events=[])


def test_a_cancelled_flyer_takes_its_event_off_even_when_a_reminder_also_announced_it():
    flyer, reminder = post("flyer", days_ago=3), post("reminder", days_ago=1)
    analyses = {
        "flyer": event_post("flyer", title="Social", start_time="21:00"),
        "reminder": event_post("reminder", title="Recordatorio", same_as=event_id("Social"), start_time="21:00"),
    }
    run(FakeInstagram({"academia": [flyer, reminder], "otra": []}), FakeExtractor(analyses))
    assert len(read(config.EVENTS_FILE)) == 1

    run(FakeInstagram({"academia": [cancel(flyer), reminder], "otra": []}), FakeExtractor({"flyer": CANCELLED}))
    assert read(config.EVENTS_FILE) == []
    records = storage.load_processed_posts()
    assert (records["flyer"].outcome, records["flyer"].detail) == ("discarded", "cancelado")
    assert (records["reminder"].outcome, records["reminder"].event_ids) == ("discarded", [])


def test_another_accounts_post_cancelled_flags_the_event_for_review_instead():
    details = {"title": "Social Timbera", "venue": "Casa Latina", "start_time": "21:00"}
    own, shared = post("own", days_ago=3), post("shared", days_ago=2)
    analyses = {"own": event_post("own", **details), "shared": event_post("shared", **details)}
    run(FakeInstagram({"academia": [own], "otra": [shared]}), FakeExtractor(analyses))
    [event] = read(config.EVENTS_FILE)
    assert event["account"] == "academia" and len(event["media"]) == 2

    run(FakeInstagram({"academia": [own], "otra": [cancel(shared)]}), FakeExtractor({"shared": CANCELLED}))
    [event] = storage.load_events()
    assert [media.post_id for media in event.media] == ["own"]
    assert event.confidence == "low" and any("cancelado" in doubt for doubt in event.doubts)
    from pa_bailar import health

    assert health.review_reasons(event)


def test_a_post_read_again_without_events_for_another_reason_leaves_the_others_events_alone():
    flyer, reminder = post("flyer", days_ago=3), post("reminder", days_ago=1)
    analyses = {
        "flyer": event_post("flyer", title="Social", start_time="21:00"),
        "reminder": event_post("reminder", title="Recordatorio", same_as=event_id("Social"), start_time="21:00"),
    }
    run(FakeInstagram({"academia": [flyer, reminder], "otra": []}), FakeExtractor(analyses))
    recap = PostAnalysis(is_event_post=False, reason="Es un resumen de fotos", events=[])
    edited = {**flyer, "caption": "Fotos"}
    run(FakeInstagram({"academia": [edited, reminder], "otra": []}), FakeExtractor({"flyer": recap}))
    [event] = read(config.EVENTS_FILE)
    assert [m["post_id"] for m in event["media"]] == ["reminder"]
