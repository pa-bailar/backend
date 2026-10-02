"""Flyer assignment in the sweep."""

import pytest

from pa_bailar import config, pipeline
from tests.factories import extracted, make_image


def test_each_event_gets_the_slide_gemini_points_to():
    events = [extracted(image_index=1), extracted(image_index=2)]
    flyers = pipeline._save_flyers("post", events, [make_image(), make_image(), make_image()])
    assert flyers == ["flyers/post-1.webp", "flyers/post-2.webp"]


def test_events_announced_on_the_same_image_share_one_file():
    events = [extracted(image_index=1), extracted(image_index=1)]
    flyers = pipeline._save_flyers("post", events, [make_image(), make_image()])
    assert flyers == ["flyers/post-1.webp", "flyers/post-1.webp"]
    assert len(list(config.FLYERS_DIR.glob("*.webp"))) == 1


@pytest.mark.parametrize("image_index", [None, 7, -1])
def test_missing_or_invalid_slide_falls_back_to_the_first_image(image_index):
    flyers = pipeline._save_flyers("post", [extracted(image_index=image_index)], [make_image()])
    assert flyers == ["flyers/post-0.webp"]


def test_post_without_images_has_no_flyers():
    assert pipeline._save_flyers("post", [extracted()], []) == [None]
