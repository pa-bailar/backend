"""End-to-end sweep with fake Instagram and Gemini: no network, no quota."""

import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from pa_bailar import config, storage
from pa_bailar.commands.sweep import summary_markdown
from pa_bailar.external import ExternalReport
from pa_bailar.gemini import ExtractionError, QuotaExhaustedError, RejectedRequestError, UnreadableAnswerError
from pa_bailar.ids import new_event_id
from pa_bailar.instagram import InstagramError
from pa_bailar.models import PostAnalysis, ProcessedPost, Triage
from pa_bailar.pipeline import Sweep, unproductive_accounts
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
        # Instagram's quota as the real client reads it (PostSource): now, and the run's peak with its measures.
        self.app_usage_percent = 0
        self.peak_usage_percent = 0
        self.peak_usage_detail: dict[str, int] = {}

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
        unreadable: frozenset[str] = frozenset(),
    ):
        self.analyses = analyses
        self.not_events = not_events
        self.flash_available = flash_available
        self.out_of_quota = out_of_quota
        self.rejected = rejected  # post ids Gemini refuses (e.g. an image it can't read)
        self.failing = failing  # post ids where every model fails (busy, bad answers): an error, retried
        self.unavailable = unavailable  # models Gemini says this key can't use
        self.unreadable = unreadable  # post ids no model gives valid JSON for
        self.attempts: list[str] = []  # every extraction asked for, answered or not
        self.known_seen: dict[str, list[str]] = {}
        self.extracted_posts: list[str] = []
        self.rules_seen: dict[str, str] = {}  # post id → the account's extra prompt rules (prompts.account_rules)
        self.flash_back_at: float | None = None  # flash_ready_at(): when busy Flash answers again; None: no quota

    def can_extract_with_flash(self) -> bool:
        return self.flash_available

    def reserve_flash(self, share: float) -> None:
        self.flash_reserved = share

    def can_upgrade(self) -> bool:
        return self.flash_available

    def flash_ready_at(self) -> float | None:
        return self.flash_back_at

    def can_analyze(self) -> bool:
        return not self.out_of_quota

    def models_unavailable(self) -> list[str]:
        return list(self.unavailable)

    def external_report(self) -> ExternalReport:
        return ExternalReport()

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
        self.attempts.append(post["id"])
        if post["id"] in self.unreadable:
            raise UnreadableAnswerError("no valid JSON")
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


def test_an_upgrade_counts_what_flash_changed_in_a_lighter_reading():
    """How the backup reads hold up on new posts (the owner, 7 Oct 2026): each upgrade of an event only a lighter
    model read is compared field by field, and the run records it."""
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    lite = event_post("p1", title="Social de salsa", start_time="20:00", styles=["salsa"])
    run(instagram, FakeExtractor({"p1": lite}, flash_available=False))
    flash = event_post("p1", title="Social de salsa", start_time="21:00", styles=["salsa", "bachata"])
    stats = run(instagram, FakeExtractor({"p1": flash}))
    assert stats.upgraded == 1
    assert stats.upgrade_changes == {"compared": 1, "dropped": 0, "start_time": 1, "styles": 1}
    from pa_bailar import health

    assert health.record_of(stats, []).upgrade_changes["start_time"] == 1  # what run_history.json keeps


def test_an_upgrade_that_agrees_counts_as_compared_only():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    same = event_post("p1", title="Social de salsa", start_time="20:00")
    run(instagram, FakeExtractor({"p1": same}, flash_available=False))
    assert run(instagram, FakeExtractor({"p1": same})).upgrade_changes == {"compared": 1, "dropped": 0}


def busy_flash_at_the_upgrades(monkeypatch, back_in: float | None) -> tuple[FakeExtractor, list[float]]:
    """A run whose upgrades find Flash paused as busy, back `back_in` seconds later (None: out of quota). The wait
    is recorded, not slept, and Flash answers after it."""
    extractor = FakeExtractor({"p1": event_post("p1", title="Leído por Flash")}, flash_available=False)
    extractor.flash_back_at = None if back_in is None else time.monotonic() + back_in
    waits: list[float] = []

    def wait(seconds: float) -> None:
        waits.append(seconds)
        extractor.flash_available = True

    monkeypatch.setattr("pa_bailar.pipeline.sweep.time.sleep", wait)
    return extractor, waits


def test_upgrades_wait_once_for_flash_busy_a_moment_ago(monkeypatch):
    """7 Oct 2026, 21:09: every Flash model paused as busy, 34 upgrades given up, 21 of the run's 30 minutes left."""
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1", title="Leído por Lite")}, flash_available=False))
    extractor, waits = busy_flash_at_the_upgrades(monkeypatch, back_in=60)
    second = run(instagram, extractor)
    assert len(waits) == 1 and 0 < waits[0] <= 60
    assert second.upgraded == 1 and read(config.EVENTS_FILE)[0]["title"] == "Leído por Flash"


def test_upgrades_dont_wait_for_flash_out_of_quota_or_past_the_runs_time(monkeypatch):
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1", title="Leído por Lite")}, flash_available=False))
    for back_in in (None, config.MAX_RUN_MINUTES * 60.0):  # no budget left today; back after the run's end
        extractor, waits = busy_flash_at_the_upgrades(monkeypatch, back_in)
        assert run(instagram, extractor).upgraded == 0 and waits == []


def test_flash_corrects_an_event_only_lighter_models_read_even_when_two_posts_announce_it():
    """@elgocepagano posted its October calendar twice; Flash-Lite titled every night "Salsoteca DC - …" (the act of
    one night). A title keeps its first value (merge_into), so Flash re-reading either post merged into the other's
    event and kept the wrong title (the weekend check, 7 Oct 2026). Now Flash's details win while every other post of
    the event was read by a lighter model."""
    instagram = FakeInstagram({"academia": [post("flyer", days_ago=3), post("reel", "VIDEO", days_ago=2)], "otra": []})
    wrong = {"title": "Salsoteca DC - Acere", "venue": None}
    run(instagram, FakeExtractor({p: event_post(p, **wrong) for p in ("flyer", "reel")}, flash_available=False))
    events = read(config.EVENTS_FILE)
    assert len(events) == 1 and events[0]["title"] == "Salsoteca DC - Acere"

    right = {"title": "Acere", "venue": "El Goce Pagano"}
    stats = run(instagram, FakeExtractor({p: event_post(p, **right) for p in ("flyer", "reel")}))
    assert stats.upgraded == 2
    events = read(config.EVENTS_FILE)
    assert len(events) == 1 and (events[0]["title"], events[0]["venue"]) == ("Acere", "El Goce Pagano")
    assert events[0]["id"] == event_id("Salsoteca DC - Acere")  # the URL shared meanwhile keeps working


def test_flash_reading_another_start_time_than_lite_corrects_the_event_and_keeps_its_url():
    """Review of 7 Oct 2026: Flash-Lite read the doors (18:00), Flash the show (23:00). The rules saw two start times,
    so Flash's re-read made a new event beside the old one, and once both posts were re-read the event had a new id:
    links shared meanwhile broke. A post's re-read is the event it announced before, on its day."""
    instagram = FakeInstagram({"academia": [post("flyer", days_ago=3), post("reel", "VIDEO", days_ago=2)], "otra": []})
    lite = {"title": "Acere", "start_time": "18:00"}
    run(instagram, FakeExtractor({p: event_post(p, **lite) for p in ("flyer", "reel")}, flash_available=False))
    first_id = read(config.EVENTS_FILE)[0]["id"]

    flash = {"title": "Acere", "start_time": "23:00"}
    run(instagram, FakeExtractor({p: event_post(p, **flash) for p in ("flyer", "reel")}))
    events = read(config.EVENTS_FILE)
    assert len(events) == 1 and events[0]["start_time"] == "23:00"
    assert events[0]["id"] == first_id


def test_flash_splitting_a_lighter_models_merged_workshops_keeps_them_apart():
    """The fallback above takes the one event a post announced on its day: three workshops Flash-Lite merged into one
    stay three when Flash reads them, the first keeping the event's URL."""
    instagram = FakeInstagram({"academia": [post("flyer", days_ago=3), post("reel", "VIDEO", days_ago=2)], "otra": []})
    merged = {p: event_post(p, title="Workshops Pro Fondos", start_time="15:00") for p in ("flyer", "reel")}
    run(instagram, FakeExtractor(merged, flash_available=False))
    first_id = read(config.EVENTS_FILE)[0]["id"]

    hours = [("Reguetón", "15:00"), ("Sabroseo", "16:00"), ("Coreografía", "17:00")]
    three = [extracted(title=title, start_time=hour) for title, hour in hours]
    split = {p: PostAnalysis(is_event_post=True, reason="", events=three) for p in ("flyer", "reel")}
    run(instagram, FakeExtractor(split))
    events = sorted(read(config.EVENTS_FILE), key=lambda event: event["start_time"])
    assert [event["title"] for event in events] == ["Reguetón", "Sabroseo", "Coreografía"]
    assert events[0]["id"] == first_id and all(len(event["media"]) == 2 for event in events)


@pytest.mark.parametrize("flash_hours", [("15:00", "21:00"), ("16:00", "22:00")])
def test_flash_listing_a_posts_events_in_another_order_keeps_each_events_url(flash_hours):
    """The bug-squash pass of 8 Oct 2026: a workshop and a social the same day in one post, read by Flash-Lite, then by
    Flash listing them the other way round. The first one on the date took the id the post's first event had: each
    event got the other's URL (and visitors' saved events swapped), and the audit counted both as changed."""
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    workshop = {"title": "Taller de bachata", "event_type": "workshop", "start_time": "15:00"}
    social = {"title": "Social de bachata", "event_type": "social", "start_time": "21:00"}
    lite = PostAnalysis(is_event_post=True, reason="", events=[extracted(**workshop), extracted(**social)])
    run(instagram, FakeExtractor({"p1": lite}, flash_available=False))

    workshop["start_time"], social["start_time"] = flash_hours
    flash = PostAnalysis(is_event_post=True, reason="", events=[extracted(**social), extracted(**workshop)])
    stats = run(instagram, FakeExtractor({"p1": flash}))
    ids = {event["title"]: event["id"] for event in read(config.EVENTS_FILE)}
    assert ids == {title: event_id(title) for title in ("Taller de bachata", "Social de bachata")}
    assert stats.upgrade_changes["compared"] == 2 and "title" not in stats.upgrade_changes


def test_a_flash_read_keeps_its_title_when_flash_upgrades_a_reminder_of_the_same_event():
    """The first known title stays when it came from Flash: a reminder's caption doesn't rename the flyer's event."""
    flyer = post("flyer", days_ago=3)
    run(FakeInstagram({"academia": [flyer], "otra": []}), FakeExtractor({"flyer": event_post("flyer", title="Social")}))
    instagram = FakeInstagram({"academia": [post("reminder", days_ago=1), flyer], "otra": []})
    reminder = event_post("reminder", title="¡Este sábado!", same_as=event_id("Social"))
    run(instagram, FakeExtractor({"reminder": reminder}, flash_available=False))

    stats = run(instagram, FakeExtractor({"reminder": reminder}))
    assert stats.upgraded == 1
    events = read(config.EVENTS_FILE)
    assert len(events) == 1 and events[0]["title"] == "Social"


class BreaksOnUpgrade(FakeExtractor):
    """An unexpected error re-reading a provisional post with Flash (e.g. a malformed answer)."""

    def extract(self, account, post, published, images, known_events, allow_provisional=True, rules=""):
        if not allow_provisional:
            raise ValueError("unexpected")
        return super().extract(account, post, published, images, known_events, allow_provisional, rules)


def test_an_unexpected_error_in_an_upgrade_loses_that_upgrade_not_the_run():
    """Upgrades run after every account since #126, outside the accounts' loop and its safety net: an error there
    ended the run before its records (meta.json, the health record) were written (the bug-squash pass, 6 Oct 2026)."""
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1")}, flash_available=False))
    config.META_FILE.unlink()
    stats = run(instagram, BreaksOnUpgrade({"p1": event_post("p1")}))
    assert config.META_FILE.exists() and stats.upgraded == 0
    assert read(config.PROCESSED_POSTS_FILE)["p1"]["provisional"] is True  # tried again next run


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
    # Archived, not lost (its flyer here isn't a real image: the record goes without one).
    archived = read(config.ARCHIVE_DIR / f"{old.last_day[:4]}.json")
    assert [event["id"] for event in archived] == ["old-0"] and archived[0]["media"][0]["flyer"] is None


def test_a_past_events_record_and_a_small_copy_of_its_flyer_are_archived():
    old = stored("old-0", posts=[media("old")], date=days_ago_date(config.EVENT_RETENTION_DAYS + 1))
    old.media[0].preview = "previews/old-0.mp4"
    storage.save_events([old])
    config.FLYERS_DIR.mkdir(parents=True)
    (config.FLYERS_DIR / "old-0.webp").write_bytes(make_image())
    run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))
    archived = read(config.ARCHIVE_DIR / f"{old.last_day[:4]}.json")[0]
    assert archived["media"][0]["flyer"] == "archive/flyers/old-0.webp" and archived["media"][0]["preview"] is None
    small = config.ARCHIVE_FLYERS_DIR / "old-0.webp"
    assert small.exists() and not (config.FLYERS_DIR / "old-0.webp").exists()
    run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))  # nothing left to archive: kept as it was
    assert [event["id"] for event in read(config.ARCHIVE_DIR / f"{old.last_day[:4]}.json")] == ["old-0"]


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


class TimeRunsOutOnFetch(FakeInstagram):
    """The run's time budget runs out while the first account's posts are fetched."""

    def __init__(self, posts_by_account, monkeypatch):
        super().__init__(posts_by_account)
        self.monkeypatch = monkeypatch

    def fetch_recent_posts(self, account, limit=config.POSTS_PER_ACCOUNT):
        self.monkeypatch.setattr(config, "MAX_RUN_MINUTES", 0)
        return super().fetch_recent_posts(account, limit)


def test_no_new_gemini_work_starts_after_the_time_budget(monkeypatch):
    extractor = FakeExtractor({"p1": event_post("p1")})
    stats = run(TimeRunsOutOnFetch({"academia": [post("p1")], "otra": []}, monkeypatch), extractor)
    assert extractor.extracted_posts == [] and stats.pending == 1
    assert "p1" not in storage.load_processed_posts()  # analyzed on the next run


def test_no_more_accounts_are_fetched_after_the_time_budget(monkeypatch):
    """Review finding: once the time is up, fetching the other due accounts only spends Instagram calls and clip
    downloads (and risks the step's timeout). They stay due, first next run."""
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    storage.write_json(config.ACCOUNT_STATE_FILE, {"academia": swept(40), "otra": swept(30)})
    instagram = TimeRunsOutOnFetch({"academia": [], "otra": [post("p1")]}, monkeypatch)
    stats = run(instagram, FakeExtractor({"p1": event_post("p1")}), all_accounts=False)
    assert list(instagram.limits) == ["academia"] and stats.accounts == 1 and stats.out_of_time
    monkeypatch.setattr(config, "MAX_RUN_MINUTES", 30)
    assert turn(storage.read_json(config.ACCOUNT_STATE_FILE, {})) == ["otra"]  # still due; academia was read


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


def test_a_run_records_its_peak_on_instagram_and_which_measure_it_was():
    instagram = FakeInstagram({"academia": []})
    instagram.peak_usage_percent = 88
    instagram.peak_usage_detail = {"call_count": 30, "total_cputime": 88, "total_time": 70}
    stats = run(instagram, FakeExtractor({}))
    assert stats.instagram_usage == 88 and stats.instagram_usage_detail["total_cputime"] == 88


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


def test_accounts_whose_posts_never_become_events_take_their_turn_every_other_day():
    """The owner, 8 Oct 2026 (129 accounts, near Instagram's hourly limit): UNPRODUCTIVE_AFTER_POSTS read, none an
    event, and the account is read every other day; one event brings it back to daily."""
    records = {
        f"p{n}": ProcessedPost(
            account="academia",
            permalink=f"https://www.instagram.com/p/p{n}/",
            processed_at="2026-10-01T10:00:00-05:00",
            is_event_post=False,
            reason="no es un evento",
            model="m",
            outcome="not_event",
        )
        for n in range(config.UNPRODUCTIVE_AFTER_POSTS)
    }
    storage.save_processed_posts(records)
    assert turn({"academia": swept(30), "otra": swept(30)}) == ["otra"]  # 30 h: not its turn yet
    assert turn({"academia": swept(50), "otra": swept(3)}) == ["academia"]
    records["p0"] = records["p0"].model_copy(update={"outcome": "event", "is_event_post": True})
    storage.save_processed_posts(records)
    assert turn({"academia": swept(30), "otra": swept(3)}) == ["academia"]  # an event: daily again


def test_unproductive_accounts_need_enough_posts_and_not_one_event():
    many = config.UNPRODUCTIVE_AFTER_POSTS
    assert unproductive_accounts([("a", False)] * many + [("b", False)] * (many - 1)) == {"a"}
    assert unproductive_accounts([("a", False)] * many + [("a", True)]) == set()


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
        "ended-long-ago",
        date=days_ago_date(retention + 4),
        end_date=days_ago_date(retention + 1),
        posts=[media("b")],
        title="Congreso de bachata",  # another event: the same title on overlapping days would be one
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


@pytest.mark.parametrize(
    "reminder_caption",
    [
        "¡Este sábado nos vemos! Recuerda: no habrá venta de boletas en taquilla, compra la tuya en línea 🎟️",
        "Últimos cupos 🔥 Política de cancelación: no hay devoluciones",
        "¡Este sábado! Si no alcanzas, abrimos nueva fecha en noviembre",
        "¡Este sábado! Recuerda: la inversión se cancela el día del taller",
        # How a price is written, and when it's paid (the bug-squash pass of 8 Oct 2026: each took the event down).
        "¡Este sábado! 💃\n💰 Inversión: $50.000\n💳 Se cancela el día del taller",
        "Recuerda: Inversión: $50.000. Se cancela el día del taller",
        "Entrada general 20 mil\nse cancela el mismo día",
        "Inversión $120.000 / se cancela en dos cuotas",
        # A condition, a denial or a question says nothing of whether it's off (the same pass).
        "¡Este sábado! Taller de bachata\nSi no se completa el cupo mínimo, el taller se aplaza",
        "¡Nos vemos el sábado en el parque!\nEn caso de lluvia el evento se aplaza",
        "¡Sigue en pie! El social NO se cancela por la lluvia ☔",
    ],
)
def test_flash_finding_no_event_in_a_reminder_leaves_the_flyers_event(reminder_caption):
    """The bug hunt of 7 Oct 2026: a reminder read by a lighter model merges into the flyer's event; Flash's upgrade
    finds no event in it, and words in its caption read as a cancellation took the event off the site for good."""
    flyer, reminder = post("flyer", days_ago=3), post("reminder", "VIDEO", days_ago=1)
    flyer["caption"] = "Social de salsa este sábado desde las 9 pm 💃"
    reminder["caption"] = reminder_caption
    analyses = {
        "flyer": event_post("flyer", title="Social", start_time="21:00"),
        "reminder": event_post("reminder", title="Social", same_as=event_id("Social"), start_time="21:00"),
    }
    run(FakeInstagram({"academia": [flyer], "otra": []}), FakeExtractor(analyses))  # the flyer, read by Flash
    run(FakeInstagram({"academia": [flyer, reminder], "otra": []}), FakeExtractor(analyses, flash_available=False))
    assert storage.load_processed_posts()["reminder"].provisional
    flash = {"reminder": PostAnalysis(is_event_post=False, reason="Video recordatorio, sin evento nuevo", events=[])}
    run(FakeInstagram({"academia": [flyer, reminder], "otra": []}), FakeExtractor(flash))  # Flash's upgrade
    assert [[media["post_id"] for media in event["media"]] for event in read(config.EVENTS_FILE)] == [["flyer"]]


@pytest.mark.parametrize(
    "caption",
    [
        "CANCELADO",
        "Se cancela el social de hoy",
        "El social de este sábado se cancela por lluvia 😔",  # not "por" a payment (the bug hunt of 7 Oct 2026)
        "Entrada: se cancela el social por lluvia",
        "Se cancelan las clases de esta semana",
        "Evento reprogramado para el 20",
        "Lo postergamos para noviembre",
        "El social se aplazó",
        "El taller no se realizará",
        # Not an amount, nor a day it's paid on: a time, a date, "el día de hoy" (the bug-squash pass of 8 Oct 2026).
        "Hoy 8 pm se cancela el social por lluvia",
        "Sábado 12: se cancela el social",
        "Se cancela el día de hoy por lluvia",
        # A condition, a denial or a question elsewhere in the caption leaves the sentence that says it alone.
        "EVENTO CANCELADO. Si compraste tu entrada, te devolvemos el dinero",
        "No se cancela, se aplaza para el 20",
        "Sí, se cancela el social",
        "Lamentablemente el social se cancela por lluvia, si ya pagaste te devolvemos el dinero",
        "SE CANCELA EL SOCIAL, si tienes dudas escríbenos",
        "Lamentablemente, si bien lo intentamos, el evento se cancela",
        # The verbs' other forms, as the participles already counted (the bug-squash pass of 8 Oct 2026: they slipped).
        "SE SUSPENDE EL SOCIAL DE HOY POR LLUVIA",
        "Se suspenden las clases y el social de esta semana",
        "Lamentablemente el evento se canceló",
        "Los talleres se aplazan para noviembre",
        "El social se reprogramó",
        "Tuvimos que cancelar el social de este sábado 😔",
        "Hemos decidido aplazar el evento",
        "Nos vemos obligados a posponer la fiesta",
        "Por motivos de fuerza mayor el social no se llevará a cabo",
    ],
)
def test_a_caption_saying_the_event_is_off(caption):
    from pa_bailar.pipeline.base import _says_cancelled

    assert _says_cancelled({"caption": caption}, PostAnalysis(is_event_post=False, reason="", events=[]))


@pytest.mark.parametrize(
    "caption",
    [
        "La entrada se cancela en la puerta",
        "El valor se cancela en efectivo al ingresar",
        "La inscripción se cancela antes del taller",
        "Cover: $20.000, se cancela por Nequi",
        # Words that aren't about the event being off (the bug hunt of 7 Oct 2026: they took events down for good).
        "Recuerda: no habrá venta de boletas en taquilla",
        "Política de cancelación: no hay devoluciones",
        "Si no alcanzas, abrimos nueva fecha en noviembre",
        "Ya se canceló tu inscripción: ¡nos vemos!",
        # Price words the rule checks already knew (the code-quality pass of 8 Oct 2026: one table, text.PRICE_WORDS).
        "La inversión se cancela el día del taller",
        "El aporte se cancela al inicio de la clase",
        "La matrícula se cancela antes de empezar",
        # An amount says it as well as a price's word: "$50.000" (its dot groups thousands, it ends no sentence), "50
        # mil", "15k", "50%", even after a label's colon; and when or how it's paid (the bug-squash pass of 8 Oct 2026).
        "Inversión: $50.000. Se cancela el día del taller",
        "💰 Inversión: $50.000\n💳 Se cancela el día del taller",
        "Valor: $30.000 (se cancela antes del taller)",
        "Precio: $60.000 que se cancelan el día del evento",
        "Entrada general 20 mil\nse cancela el mismo día",
        "Cover: 15k se cancela en la entrada",
        "El 50% se cancela para separar el cupo",
        "Inversión $120.000 / se cancela en dos cuotas",
        "Mensualidad $150.000 se cancela los primeros 5 días del mes",
        "Valor del taller: $45.000\n*Se cancela al momento de la inscripción",
        "Separa tu cupo con $20.000 y el saldo se cancela por adelantado",
        # A condition, a refund rule, a denial or a question: none says it's off (the same pass).
        "Si no se completa el cupo mínimo, el taller se aplaza",
        "El taller se aplaza si no se completa el cupo",
        "En caso de lluvia el evento se aplaza",
        "El evento se cancela en caso de lluvia",
        "Si el evento es cancelado se devuelve el dinero",
        "¡Sigue en pie! El social NO se cancela por la lluvia",
        "Aclaramos: el evento no está cancelado, ¡nos vemos!",
        "¿Se cancela por la lluvia? ¡No! Te esperamos",
        "Se suspende por lluvia? Nooo 💃",
        # "Se canceló" paid: already, or a price's word before it (the audit of 7 Oct 2026 left it out for these).
        "Si ya se canceló el 50%, trae el comprobante",
        "La inscripción ya se canceló",
        "Gracias a quienes ya se cancelaron la mensualidad",
    ],
)
def test_se_cancela_meaning_it_is_paid_or_other_words_dont_cancel(caption):
    """In Colombia "cancelar" is also "to pay" (the audit of 7 Oct 2026)."""
    from pa_bailar.pipeline.base import _says_cancelled

    assert not _says_cancelled({"caption": caption}, PostAnalysis(is_event_post=False, reason="", events=[]))


def cancel(post_dict: dict) -> dict:
    return {**post_dict, "caption": "CANCELADO: lo sentimos"}


CANCELLED = PostAnalysis(is_event_post=False, reason="El evento fue cancelado", events=[])


@pytest.mark.parametrize(
    "caption",
    [
        "CANCELADO: lo sentimos",
        # The bug-squash pass of 8 Oct 2026: these left the event on the site, the reminder still announcing it.
        "SE SUSPENDE EL SOCIAL DE HOY POR LLUVIA ☔",
        "Tuvimos que cancelar el social de este sábado 😔",
        "Lamentablemente el social se canceló",
    ],
)
def test_a_cancelled_flyer_takes_its_event_off_even_when_a_reminder_also_announced_it(caption):
    flyer, reminder = post("flyer", days_ago=3), post("reminder", days_ago=1)
    analyses = {
        "flyer": event_post("flyer", title="Social", start_time="21:00"),
        "reminder": event_post("reminder", title="Recordatorio", same_as=event_id("Social"), start_time="21:00"),
    }
    run(FakeInstagram({"academia": [flyer, reminder], "otra": []}), FakeExtractor(analyses))
    assert len(read(config.EVENTS_FILE)) == 1

    gone = PostAnalysis(is_event_post=False, reason="Ya no anuncia un evento", events=[])  # the caption says it alone
    edited = {**flyer, "caption": caption}
    run(FakeInstagram({"academia": [edited, reminder], "otra": []}), FakeExtractor({"flyer": gone}))
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


# ---------- review fixes (2): posts no model can read, edited captions that must wait ----------


def test_a_post_no_model_can_read_is_given_up_after_a_few_runs():
    """Review finding: a post Gemini never answers with valid JSON was retried on every run for a week, spending
    Flash's small quota each time. After UNREADABLE_RUNS runs it's recorded as rejected and never asked again."""
    instagram = FakeInstagram({"academia": [post("long")], "otra": []})
    for runs in range(1, config.UNREADABLE_RUNS):
        stats = run(instagram, FakeExtractor({}, unreadable=frozenset({"long"})))
        assert stats.pending == 1 and "long" not in storage.load_processed_posts()
        assert read(config.ACCOUNT_STATE_FILE)["academia"]["unreadable"] == {"long": runs}

    stats = run(instagram, FakeExtractor({}, unreadable=frozenset({"long"})))
    record = storage.load_processed_posts()["long"]
    assert record.outcome == "rejected" and "respuesta válida" in record.reason
    assert stats.pending == 0 and stats.errors == 1
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["unreadable"] == {}
    again = FakeExtractor({}, unreadable=frozenset({"long"}))
    run(instagram, again)
    assert again.attempts == []


def test_a_post_read_at_last_forgets_its_unreadable_runs():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({}, unreadable=frozenset({"p1"})))
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["unreadable"] == {"p1": 1}
    run(instagram, FakeExtractor({"p1": event_post("p1")}))
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["unreadable"] == {} and len(read(config.EVENTS_FILE)) == 1


def test_an_unreadable_post_no_longer_fetched_is_forgotten():
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({}, unreadable=frozenset({"p1"})))
    run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["unreadable"] == {}


def test_an_unreadable_upgrade_keeps_the_provisional_reading_after_a_few_runs():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1")}, flash_available=False))
    assert storage.load_processed_posts()["p1"].provisional
    for _ in range(config.UNREADABLE_RUNS):
        run(instagram, FakeExtractor({}, unreadable=frozenset({"p1"})))
    assert not storage.load_processed_posts()["p1"].provisional and len(read(config.EVENTS_FILE)) == 1
    again = FakeExtractor({}, unreadable=frozenset({"p1"}))
    run(instagram, again)
    assert again.attempts == []  # Flash's quota isn't spent on it any more


@pytest.mark.parametrize("why", ["no quota", "no time"])
def test_an_edited_caption_that_cant_be_read_now_keeps_the_account_due(monkeypatch, why):
    """Review finding: a "CANCELADO" edit that couldn't be read (no quota, no time) wasn't pending, so the account
    was marked read and the edit waited a whole turn (20 h, or days for a quiet account)."""
    first = post("p1")
    run(FakeInstagram({"academia": [first], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    states = read(config.ACCOUNT_STATE_FILE)
    before = states["academia"]["last_swept_at"] = swept(30)["last_swept_at"]
    storage.write_json(config.ACCOUNT_STATE_FILE, states)

    edited = {**first, "caption": "CANCELADO"}
    if why == "no quota":
        instagram, extractor = FakeInstagram({"academia": [edited], "otra": []}), FakeExtractor({}, out_of_quota=True)
    else:
        instagram, extractor = TimeRunsOutOnFetch({"academia": [edited], "otra": []}, monkeypatch), FakeExtractor({})
    stats = run(instagram, extractor)
    assert stats.pending == 1 and stats.reanalyzed == 0
    assert read(config.ACCOUNT_STATE_FILE)["academia"]["last_swept_at"] == before  # still due: read next run


@pytest.mark.parametrize("edited", [False, True])
def test_a_failure_while_storing_a_post_leaves_it_to_be_read_again(monkeypatch, edited):
    """The post's record is written last: a failure after its old events were detached must not leave it recorded as
    analyzed (its events lost for good). Another account's post saves the run's state after the failure."""
    first = post("p1", days_ago=3)
    if edited:  # read before, then its caption edited
        run(FakeInstagram({"academia": [first], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
        first = {**first, "caption": "Ahora con lugar"}
    before = storage.load_processed_posts().get("p1")
    original = Sweep._add_event

    def failing(self, account, post, *args, **kwargs):
        if post["id"] == "p1":
            raise RuntimeError("disk gone")
        return original(self, account, post, *args, **kwargs)

    monkeypatch.setattr(Sweep, "_add_event", failing)
    analyses = {"p1": event_post("p1"), "p2": event_post("p2", title="Otra")}
    stats = run(FakeInstagram({"academia": [first], "otra": [post("p2")]}), FakeExtractor(analyses))
    assert stats.errors == 1 and storage.load_processed_posts().get("p1") == before  # not recorded as read

    monkeypatch.setattr(Sweep, "_add_event", original)
    run(FakeInstagram({"academia": [first], "otra": [post("p2")]}), FakeExtractor(analyses))
    assert sorted(event["id"] for event in read(config.EVENTS_FILE)) == sorted([event_id("Social"), event_id("Otra")])


def test_duplicates_stored_by_an_older_rule_are_merged_on_the_next_run():
    """Every run repairs what the rules let through before: the posts' records follow the event that's kept."""
    full = stored("salsoteca-dc-acere", posts=[media("carousel")], title="Salsoteca DC - Acere", start_time=None,
                  address="Diagonal 20A")  # fmt: skip
    bare = stored("acere", posts=[media("video", "VIDEO")], title="Acere", start_time=None)
    storage.save_events([full, bare])
    record = processed_record(1)
    record.outcome, record.event_ids = "event", ["acere"]
    storage.save_processed_posts({"video": record})
    run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))
    assert [event.id for event in storage.load_events()] == ["salsoteca-dc-acere"]
    assert storage.load_processed_posts()["video"].event_ids == ["salsoteca-dc-acere"]
