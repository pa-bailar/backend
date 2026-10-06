"""The images' own repository (media_store.py): copied into the site checkout before a run, pushed back after it."""

import json

import pytest

from pa_bailar import media_store


def write(path, content=b"img"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def events(data, *images):
    """data/events.json with one event pointing to these images."""
    data.mkdir(parents=True, exist_ok=True)
    flyers = [{"flyer": image} for image in images]
    (data / "events.json").write_text(json.dumps([{"id": "e", "media": flyers}]), encoding="utf-8")


def test_pull_copies_the_current_images_but_not_the_archive(tmp_path):
    media, data = tmp_path / "media", tmp_path / "data"
    write(media / "flyers" / "a-0.webp")
    write(media / "previews" / "a-0.mp4")
    write(media / "archive" / "flyers" / "old-0.webp")
    assert media_store.pull(media, data) == 2
    assert (data / "flyers" / "a-0.webp").exists() and (data / "previews" / "a-0.mp4").exists()
    assert not (data / "archive").exists()  # the site never publishes the archive's images


def test_push_adds_new_images_updates_changed_ones_and_removes_what_the_run_deleted(tmp_path):
    media, data = tmp_path / "media", tmp_path / "data"
    write(media / "flyers" / "kept-0.webp")
    write(media / "flyers" / "changed-0.webp", b"old")
    write(media / "flyers" / "expired-0.webp")  # its event left the site this run
    write(data / "flyers" / "kept-0.webp")
    write(data / "flyers" / "changed-0.webp", b"new")
    write(data / "flyers" / "new-0.webp")
    write(data / "archive" / "flyers" / "expired-0.webp", b"small")
    events(data, "flyers/kept-0.webp", "flyers/changed-0.webp", "flyers/new-0.webp")
    report = media_store.push(data, media)
    assert (report.added, report.updated, report.removed) == (2, 1, 1)
    assert sorted(file.name for file in (media / "flyers").iterdir()) == ["changed-0.webp", "kept-0.webp", "new-0.webp"]
    assert (media / "flyers" / "changed-0.webp").read_bytes() == b"new"
    assert (media / "archive" / "flyers" / "expired-0.webp").exists()


def test_push_never_removes_an_image_an_event_still_points_to(tmp_path):
    """A run that couldn't pull has an empty data/flyers/: the repository must not be emptied with it."""
    media, data = tmp_path / "media", tmp_path / "data"
    write(media / "flyers" / "a-0.webp")
    events(data, "flyers/a-0.webp")
    assert media_store.push(data, media).removed == 0
    assert (media / "flyers" / "a-0.webp").exists()


def test_push_never_removes_the_archive(tmp_path):
    media, data = tmp_path / "media", tmp_path / "data"
    write(media / "archive" / "flyers" / "old-0.webp")
    events(data)
    media_store.push(data, media)
    assert (media / "archive" / "flyers" / "old-0.webp").exists()


def test_push_refuses_to_run_without_the_events(tmp_path):
    media, data = tmp_path / "media", tmp_path / "data"
    write(media / "flyers" / "a-0.webp")
    data.mkdir()
    with pytest.raises(SystemExit):
        media_store.push(data, media)
    assert (media / "flyers" / "a-0.webp").exists()
