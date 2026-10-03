"""Videos' preview clips and carousels' slide counts: which media get them. No network, no ffmpeg."""

import pytest

from pa_bailar import clips, config, instagram, pipeline
from tests.factories import make_image
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post, read, run


@pytest.fixture(autouse=True)
def two_accounts_and_fake_images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.download_image", lambda url: make_image())


def carousel(post_id: str = "c1") -> dict:
    return {
        **post(post_id),
        "media_type": "CAROUSEL_ALBUM",
        "children": {
            "data": [
                {
                    "media_type": "VIDEO",
                    "media_url": "https://cdn.example/v.mp4",
                    "thumbnail_url": "https://cdn.example/f.jpg",
                },
                {"media_type": "IMAGE", "media_url": "https://cdn.example/i.jpg"},
                {"media_type": "VIDEO", "thumbnail_url": "https://cdn.example/f2.jpg"},  # no file: licensed music
            ]
        },
    }


def test_the_video_behind_each_analyzed_image():
    assert instagram.video_url(carousel(), 0) == "https://cdn.example/v.mp4"
    assert instagram.video_url(carousel(), 1) is None  # a photo
    assert instagram.video_url(carousel(), 2) is None  # a video Instagram gives no file for
    reel = {**post("r1", "VIDEO"), "media_url": "https://cdn.example/r.mp4"}
    assert instagram.video_url(reel, 0) == "https://cdn.example/r.mp4"
    assert instagram.slide_count(carousel()) == 3 and instagram.slide_count(reel) is None


def test_no_ffmpeg_means_no_clip(monkeypatch):
    monkeypatch.setattr(config, "FFMPEG", "no-such-ffmpeg-program")
    assert clips.make_clip("https://cdn.example/v.mp4", "x-0") is None


@pytest.fixture
def fake_clips(monkeypatch):
    made: list[str] = []

    def make(url, name):
        made.append(name)
        return clips.clip_path(name)

    monkeypatch.setattr("pa_bailar.pipeline.clips.make_clip", make)
    return made


def test_a_flyer_from_a_video_slide_gets_a_clip_and_carousels_their_slide_count(fake_clips):
    instagram_posts = FakeInstagram({"academia": [carousel()], "otra": []})
    run(instagram_posts, FakeExtractor({"c1": event_post("c1", image_index=0)}))
    media = read(config.EVENTS_FILE)[0]["media"][0]
    assert media["preview"] == "previews/c1-0.mp4" and media["slides"] == 3
    assert fake_clips == ["c1-0"]


def test_a_flyer_from_a_photo_slide_gets_no_clip(fake_clips):
    run(FakeInstagram({"academia": [carousel()], "otra": []}), FakeExtractor({"c1": event_post("c1", image_index=1)}))
    media = read(config.EVENTS_FILE)[0]["media"][0]
    assert media["preview"] is None and media["slides"] == 3 and fake_clips == []


def test_posts_stored_before_clips_get_them_when_seen_again(fake_clips, monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.clips.make_clip", lambda url, name: None)
    instagram_posts = FakeInstagram({"academia": [carousel()], "otra": []})
    run(instagram_posts, FakeExtractor({"c1": event_post("c1", image_index=0)}))  # no clip then
    assert read(config.EVENTS_FILE)[0]["media"][0]["preview"] is None

    monkeypatch.setattr("pa_bailar.pipeline.clips.make_clip", lambda url, name: clips.clip_path(name))
    run(instagram_posts, FakeExtractor({}))  # already analyzed: not sent to Gemini again
    assert read(config.EVENTS_FILE)[0]["media"][0]["preview"] == "previews/c1-0.mp4"


def test_unused_clips_are_deleted_with_their_events(isolated_files):
    config.PREVIEWS_DIR.mkdir(parents=True)
    (config.PREVIEWS_DIR / "old-0.mp4").write_bytes(b"x")
    assert pipeline.storage.remove_unused_flyers([]) == 1
    assert not list(config.PREVIEWS_DIR.glob("*.mp4"))


def test_old_flyer_names_point_to_the_first_slide():
    assert pipeline._flyer_slide("flyers/123-4.webp") == 4
    assert pipeline._flyer_slide("flyers/123.webp") == 0
