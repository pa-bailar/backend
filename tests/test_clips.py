"""Videos' preview clips and carousels' slide counts: which media get them. No network, no ffmpeg."""

import pytest

from pa_bailar import clips, config, instagram, storage
from pa_bailar.pipeline import common
from tests.factories import make_image
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post, read, run


@pytest.fixture(autouse=True)
def two_accounts_and_fake_images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


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

    monkeypatch.setattr("pa_bailar.clips.make_clip", make)
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
    monkeypatch.setattr("pa_bailar.clips.make_clip", lambda url, name: None)
    instagram_posts = FakeInstagram({"academia": [carousel()], "otra": []})
    run(instagram_posts, FakeExtractor({"c1": event_post("c1", image_index=0)}))  # no clip then
    assert read(config.EVENTS_FILE)[0]["media"][0]["preview"] is None

    monkeypatch.setattr("pa_bailar.clips.make_clip", lambda url, name: clips.clip_path(name))
    run(instagram_posts, FakeExtractor({}))  # already analyzed: not sent to Gemini again
    assert read(config.EVENTS_FILE)[0]["media"][0]["preview"] == "previews/c1-0.mp4"


def test_unused_clips_are_deleted_with_their_events(isolated_files):
    config.PREVIEWS_DIR.mkdir(parents=True)
    (config.PREVIEWS_DIR / "old-0.mp4").write_bytes(b"x")
    assert storage.remove_unused_flyers([]) == 1
    assert not list(config.PREVIEWS_DIR.glob("*.mp4"))


def test_old_flyer_names_point_to_the_first_slide():
    assert common.flyer_slide("flyers/123-4.webp") == 4
    assert common.flyer_slide("flyers/123.webp") == 0


# ---------- _complete_media: what older stored media get from a fresh copy of their post ----------


def stored_media(post_id: str, media_type: str, flyer: str | None, preview: str | None = None, slides=None):
    from tests.factories import media, stored

    item = media(post_id, media_type).model_copy(update={"flyer": flyer, "preview": preview, "slides": slides})
    return stored(f"{post_id}-event", posts=[item])


def complete(events, posts):
    from pa_bailar.pipeline import Sweep

    sweep = Sweep(lookback_days=7, instagram=FakeInstagram({}), extractor=FakeExtractor({}))
    sweep.events = events
    sweep._complete_media(posts)
    return sweep.events


def test_older_media_get_the_slide_count_and_the_clip_of_their_flyers_slide(fake_clips):
    [event] = complete([stored_media("c1", "CAROUSEL_ALBUM", "flyers/c1-0.webp")], [carousel()])
    assert (event.media[0].slides, event.media[0].preview) == (3, "previews/c1-0.mp4")
    assert storage.load_events() == [event]  # saved


def test_a_flyer_from_a_photo_slide_or_a_photo_post_gets_no_clip(fake_clips):
    photo = {**post("p1"), "media_type": "IMAGE"}
    events = [
        stored_media("c1", "CAROUSEL_ALBUM", "flyers/c1-1.webp"),  # the photo slide
        stored_media("c2", "CAROUSEL_ALBUM", "flyers/c2-2.webp"),  # a video Instagram gives no file for
        stored_media("p1", "IMAGE", "flyers/p1-0.webp"),
    ]
    complete(events, [carousel("c1"), carousel("c2"), photo])
    assert fake_clips == [] and [e.media[0].preview for e in events] == [None, None, None]
    assert [e.media[0].slides for e in events] == [3, 3, None]


def test_media_already_complete_or_not_fetched_now_are_left_alone(fake_clips):
    done = stored_media("c1", "CAROUSEL_ALBUM", "flyers/c1-0.webp", preview="previews/c1-0.mp4", slides=3)
    unseen = stored_media("c9", "CAROUSEL_ALBUM", "flyers/c9-0.webp")
    complete([done, unseen], [carousel("c1")])
    assert fake_clips == [] and unseen.media[0].slides is None
    assert storage.load_events() == []  # nothing changed: nothing saved
