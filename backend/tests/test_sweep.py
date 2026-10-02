"""End-to-end sweep with fake Instagram and Gemini: no network, no quota."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from pabailar import config, storage
from pabailar.extraction import ExtractionError
from pabailar.instagram import InstagramError
from pabailar.models import PostAnalysis, ProcessedPost, Triage
from pabailar.pipeline import Sweep
from run_pipeline import summary_markdown
from tests.factories import extracted, make_image, media, stored

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
    ):
        self.analyses = analyses
        self.not_events = not_events
        self.flash_available = flash_available
        self.out_of_quota = out_of_quota
        self.known_seen: dict[str, list[str]] = {}
        self.extracted_posts: list[str] = []

    def can_extract_with_flash(self) -> bool:
        return self.flash_available

    def requests_this_run(self) -> dict[str, int]:
        return {"fake-flash": len(self.extracted_posts)}

    def triage(self, account, post, published, images):
        if self.out_of_quota:
            raise ExtractionError("no quota")
        return Triage(is_event_post=post["id"] not in self.not_events, reason="triage"), "fake-lite"

    def extract(self, account, post, published, images, known_events, allow_provisional=True):
        if self.out_of_quota:
            raise ExtractionError("no quota")
        self.known_seen[post["id"]] = [event.id for event in known_events]
        self.extracted_posts.append(post["id"])
        if self.flash_available:
            return self.analyses[post["id"]], "fake-flash", False
        if not allow_provisional:
            raise ExtractionError("flash out of quota")
        return self.analyses[post["id"]], "fake-lite", True


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "FLYERS_DIR", tmp_path / "data" / "flyers")
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "data" / "events.json")
    monkeypatch.setattr(config, "META_FILE", tmp_path / "data" / "meta.json")
    monkeypatch.setattr(config, "PROCESSED_POSTS_FILE", tmp_path / "state" / "processed_posts.json")
    monkeypatch.setattr(config, "ACCOUNT_STATE_FILE", tmp_path / "state" / "accounts.json")
    accounts = tmp_path / "accounts.txt"
    accounts.write_text("academia\n# comment\n@otra\n", encoding="utf-8")
    monkeypatch.setattr(config, "ACCOUNTS_FILE", accounts)
    monkeypatch.setattr("pabailar.pipeline.download_image", lambda url: make_image())
    return tmp_path


def run(instagram, extractor, days=7):
    return Sweep(lookback_days=days, instagram=instagram, extractor=extractor).run()


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
            "video": event_post("video", title="Ven a bailar", same_as="flyer-0", start_time=None),
        }
    )

    stats = run(instagram, extractor)

    events = read(config.EVENTS_FILE)
    assert len(events) == 1
    assert [m["post_id"] for m in events[0]["media"]] == ["flyer", "video"]
    assert events[0]["title"] == "Social" and events[0]["start_time"] == "20:00"
    assert extractor.known_seen["video"] == ["flyer-0"]  # Gemini was told about the earlier event
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
