"""End-to-end sweep with fake Instagram and Gemini: no network, no quota."""

import json

import pytest

from pabailar import config
from pabailar.instagram import InstagramError
from pabailar.models import PostAnalysis
from pabailar.pipeline import Sweep
from run_pipeline import summary_markdown
from tests.factories import extracted, make_image

FLYER_URL = "https://cdn.example/flyer.jpg"
VIDEO_THUMB_URL = "https://cdn.example/video.jpg"


def post(post_id: str, media_type: str, timestamp: str, **extra) -> dict:
    url = {"media_url": FLYER_URL} if media_type == "IMAGE" else {"thumbnail_url": VIDEO_THUMB_URL}
    return {
        "id": post_id,
        "media_type": media_type,
        "timestamp": timestamp,
        "permalink": f"https://www.instagram.com/p/{post_id}/",
        "caption": "caption",
        **url,
        **extra,
    }


class FakeInstagram:
    def __init__(self, posts_by_account: dict[str, list[dict] | Exception]):
        self.posts_by_account = posts_by_account

    def check_token(self) -> str:
        return "me"

    def fetch_recent_posts(self, account: str) -> list[dict]:
        result = self.posts_by_account[account]
        if isinstance(result, Exception):
            raise result
        return result


class FakeExtractor:
    """Returns a prepared analysis per post id and records the known events it was given."""

    def __init__(self, analyses: dict[str, PostAnalysis]):
        self.analyses = analyses
        self.known_seen: dict[str, list[str]] = {}

    def analyze(self, account, post, published, images, known_events):
        self.known_seen[post["id"]] = [event.id for event in known_events]
        return self.analyses[post["id"]], "fake-model"


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "FLYERS_DIR", tmp_path / "data" / "flyers")
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "data" / "events.json")
    monkeypatch.setattr(config, "META_FILE", tmp_path / "data" / "meta.json")
    monkeypatch.setattr(config, "PROCESSED_POSTS_FILE", tmp_path / "state" / "processed_posts.json")
    accounts = tmp_path / "accounts.txt"
    accounts.write_text("academia\n# comment\n@otra\n", encoding="utf-8")
    monkeypatch.setattr(config, "ACCOUNTS_FILE", accounts)
    monkeypatch.setattr("pabailar.pipeline.download_image", lambda url: make_image())
    return tmp_path


def run(instagram, extractor, days=3650):
    return Sweep(lookback_days=days, instagram=instagram, extractor=extractor).run()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_flyer_then_video_of_the_same_event_become_one_event_with_two_posts():
    instagram = FakeInstagram(
        {
            # Instagram returns newest first; the sweep processes oldest first.
            "academia": [
                post("video", "VIDEO", "2026-09-30T12:00:00+0000"),
                post("flyer", "IMAGE", "2026-09-28T12:00:00+0000"),
            ],
            "otra": [],
        }
    )
    extractor = FakeExtractor(
        {
            "flyer": PostAnalysis(
                is_event_post=True, reason="", events=[extracted(title="Social", start_time="20:00")]
            ),
            "video": PostAnalysis(
                is_event_post=True,
                reason="",
                events=[extracted(title="Ven a bailar", same_as="flyer-0", start_time=None)],
            ),
        }
    )

    stats = run(instagram, extractor)

    events = read(config.EVENTS_FILE)
    assert len(events) == 1
    assert [m["post_id"] for m in events[0]["media"]] == ["flyer", "video"]
    assert events[0]["title"] == "Social" and events[0]["start_time"] == "20:00"
    assert extractor.known_seen["video"] == ["flyer-0"]  # Gemini was told about the earlier event
    assert (stats.events_new, stats.events_merged) == (1, 1)


def test_recurring_and_undated_events_are_not_published():
    instagram = FakeInstagram({"academia": [post("p1", "IMAGE", "2026-09-28T12:00:00+0000")], "otra": []})
    extractor = FakeExtractor(
        {
            "p1": PostAnalysis(
                is_event_post=True,
                reason="",
                events=[extracted(title="Clase", is_recurring=True), extracted(title="Sin fecha", date="sábado")],
            )
        }
    )
    stats = run(instagram, extractor)
    assert read(config.EVENTS_FILE) == []
    assert stats.events_discarded == 2


def test_processed_posts_are_not_sent_to_gemini_again():
    instagram = FakeInstagram({"academia": [post("p1", "IMAGE", "2026-09-28T12:00:00+0000")], "otra": []})
    analysis = PostAnalysis(is_event_post=True, reason="", events=[extracted()])
    run(instagram, FakeExtractor({"p1": analysis}))

    second = FakeExtractor({})  # would raise KeyError if asked about p1 again
    stats = run(instagram, second)
    assert stats.posts_analyzed == 0 and second.known_seen == {}


def test_one_account_failing_does_not_stop_the_others_and_meta_is_written():
    instagram = FakeInstagram(
        {
            "academia": InstagramError("not a business account"),
            "otra": [post("p1", "IMAGE", "2026-09-28T12:00:00+0000")],
        }
    )
    analysis = PostAnalysis(is_event_post=True, reason="", events=[extracted()])
    stats = run(instagram, FakeExtractor({"p1": analysis}))

    assert stats.failed_accounts == 1 and stats.events_new == 1
    meta = read(config.META_FILE)
    assert meta["schema_version"] == 1 and meta["generated_at"]
    assert meta["stats"]["by_account"]["academia"]["fetch_failed"] is True
    assert "@academia" in summary_markdown(stats)
