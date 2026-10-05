"""The media tools' pure functions: the weekend rule, occurrences, version names, the sticker-band math, loudness
parsing, shelf lives, stale stages, TTS errors. Standard library only (no ffmpeg, no network)."""

import json
import os
import time
from datetime import date
from pathlib import Path

import clean
import common
import events
import make
import mix
import pytest
import render
import review
import tts

CASES = json.loads((Path(__file__).parent / "weekend-cases.json").read_text(encoding="utf-8"))["cases"]


# ---------- events ----------


@pytest.mark.parametrize("case", CASES, ids=[c["today"] for c in CASES])
def test_weekend_follows_the_shared_rule(case):
    friday, sunday = events.weekend(date.fromisoformat(case["today"]))
    assert (friday.isoformat(), sunday.isoformat()) == (case["from"], case["to"])


def test_occurrence_of_a_run_of_days_is_its_first_day_in_range():
    e = {"date": "2026-10-07", "end_date": "2026-10-09", "start_time": "10:00", "end_time": "12:00"}
    assert events.occurrence(e, "2026-10-09", "2026-10-11") == ("2026-10-09", "10:00", "12:00")


def test_occurrence_of_a_series_takes_that_sessions_times():
    e = {
        "date": "2026-10-04",
        "sessions": [
            {"date": "2026-10-04", "start_time": "15:00", "end_time": "17:00"},
            {"date": "2026-10-11", "start_time": "16:00", "end_time": "18:00"},
        ],
    }
    assert events.occurrence(e, "2026-10-09", "2026-10-11") == ("2026-10-11", "16:00", "18:00")


def test_pick_sorts_by_the_day_shown_and_filters_styles():
    a = {"date": "2026-10-11", "start_time": "19:00", "styles": ["salsa caleña"]}
    b = {"date": "2026-10-07", "end_date": "2026-10-10", "start_time": "20:00", "styles": ["bachata"]}
    c = {"date": "2026-10-10", "start_time": None, "styles": ["tango"]}
    assert events.pick([a, b, c], "2026-10-09", "2026-10-11", [], 0) == [b, c, a]
    assert events.pick([a, b, c], "2026-10-09", "2026-10-11", ["salsa"], 0) == [a]
    assert events.pick([a, b, c], "2026-10-09", "2026-10-11", [], 1) == [b]


# ---------- versions and names ----------


def test_render_names_round_trip_with_dashes_in_the_video_name():
    name = common.render_name("teaser-v2", "2.4", "with-music")
    assert name == "teaser-v2-v2.4-with-music.mp4"
    assert common.parse_render_name("teaser-v2", name) == ((2, 4), "with-music")
    assert common.parse_render_name("teaser-v2", common.render_name("teaser-v2", "2.4", "reel", draft=True)) is None
    assert common.parse_render_name("teaser-v2", "reel.mp4") is None


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_old_versions_keeps_the_latest_of_each_deliverable(tmp_path):
    old = [touch(tmp_path / "teaser-v2-v2.3-reel.mp4"), touch(tmp_path / "teaser-v2-v2.10-with-music.mp4")]
    keep = [touch(tmp_path / "teaser-v2-v2.11-with-music.mp4"), touch(tmp_path / "teaser-v2-v3-reel.mp4")]
    touch(tmp_path / "reel.mp4")
    found = clean.old_versions(tmp_path, "teaser-v2")
    assert sorted(found) == sorted(old)
    assert not set(keep) & set(found)


def test_old_versions_without_a_name_reads_the_archive_names(tmp_path):
    old = touch(tmp_path / "teaser-v2.2-reel.mp4")
    touch(tmp_path / "teaser-v2.3-reel.mp4")
    assert clean.old_versions(tmp_path) == [old]


def test_clean_skips_the_site_checks_and_spots_working_files(tmp_path):
    assert clean.site_check(touch(tmp_path / "calendar-check.mjs"))
    assert clean.site_check(tmp_path / "site-bugs")
    assert not clean.site_check(tmp_path / "teaser-v2")
    assert clean.working_file(touch(tmp_path / "teaser-v2-v2.4-reel-draft.mp4"))
    assert clean.working_file(touch(tmp_path / "teaser-v2-v2.4-reel-vs-v2.3.mp4"))
    assert not clean.working_file(touch(tmp_path / "teaser-v2-v2.4-reel.mp4"))


# ---------- times ----------

TIMING = {
    "lines": [
        {
            "id": "c4",
            "start": 17.411,
            "words": [{"word": "link…", "start": 17.96}, {"word": "Bailando.", "start": 19.0}],
        },
        {"id": "c2", "start": 10.871, "words": [{"word": "dónde,", "start": 12.14}, {"word": "dónde", "start": 12.5}]},
    ]
}


def test_at_seconds_takes_seconds_frames_lines_and_words():
    assert common.at_seconds("8.5", None) == 8.5
    assert common.at_seconds("8.5s", None) == 8.5
    assert common.at_seconds("f255", None) == 8.5
    assert common.at_seconds("c4", TIMING) == 17.411
    assert common.at_seconds("c4:link", TIMING) == 17.96
    assert common.at_seconds("c4:bailando", TIMING) == 19.0
    assert common.at_seconds("c2:donde:1", TIMING) == 12.5
    with pytest.raises(SystemExit):
        common.at_seconds("c9", TIMING)


# ---------- review ----------


def test_drawtext_value_escapes_quotes_colons_and_backslashes():
    assert review.drawtext_value("v2.3: Pa' Bailar \\ x") == "v2.3\\: Pa’ Bailar \\\\ x"


def strip(rows: list[list[int]]) -> bytes:
    return bytes(v for row in rows for v in row)


def test_band_background_ignores_grain_and_finds_content():
    paper = [[218, 222, 214, 220, 219, 221, 216, 223]] * 6
    assert review.content_top(strip(paper), 8, min_px=2) is None
    ink = [row[:] for row in paper]
    ink[4] = [218, 40, 42, 220, 219, 221, 216, 223]
    assert review.content_top(strip(ink), 8, min_px=2) == 4


def test_band_full_bleed_color_is_background_not_content():
    tomato = [[92, 95, 90, 93, 94, 91, 92, 93]] * 5
    assert review.content_top(strip(tomato), 8, min_px=2) is None


def test_band_runs_and_spans():
    assert review.runs([(10, 249), (11, 245), (12, 250), (20, 248)]) == [(10, 12, 245), (20, 20, 248)]
    assert review.parse_spans("4.2-4.3, 5.75-6.45") == [(4.2, 4.3), (5.75, 6.45)]
    assert common.BRAND["stickerBand"]["bottom"] + common.BRAND["stickerBand"]["margin"] == review.LIMIT


# ---------- mix ----------

EBUR128 = """[Parsed_ebur128_0 @ 000] Summary:

  Integrated loudness:
    I:         -13.9 LUFS
    Threshold: -24.3 LUFS

  Loudness range:
    LRA:         2.1 LU

  True peak:
    Peak:       -1.1 dBFS
"""


def test_parse_ebur128_reads_loudness_and_true_peak():
    assert mix.parse_ebur128("noise before\n" + EBUR128) == (-13.9, -1.1)


def test_mix_problems_catch_true_peak_and_loudness():
    assert mix.problems(-13.9, -1.1, -14.0) == []
    assert any("true peak" in p for p in mix.problems(-14.0, -0.4, -14.0))
    assert any("LU off" in p for p in mix.problems(-16.2, -3.0, -14.0))


def test_last_json_takes_loudnorms_report():
    assert mix.last_json('x {"a": 1} y {"normalization_type": "dynamic"} z') == {"normalization_type": "dynamic"}


# ---------- render ----------


def test_first_day_and_expired_shelf_lives(tmp_path):
    assert render.first_day('2026-10-10 (the screens\' "Hoy")') == date(2026, 10, 10)
    assert render.first_day("2026-10-10T19:00:00-05:00") == date(2026, 10, 10)
    assert render.first_day(None) is None
    (tmp_path / "app.json").write_text(json.dumps({"shelfLife": "2026-10-10 (Hoy)"}))
    (tmp_path / "events.json").write_text(json.dumps({"to": "2026-10-11"}))
    lives = render.shelf_lives(tmp_path)
    assert lives == [("app.json shelfLife", date(2026, 10, 10)), ("events.json to", date(2026, 10, 11))]
    assert render.expired(lives, date(2026, 10, 10)) == []
    assert render.expired(lives, date(2026, 10, 11)) == ["app.json shelfLife 2026-10-10"]


def test_timing_problem_when_the_voice_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "MEDIA", tmp_path)
    settings = {"voice": {"name": "Achird", "lines": [{"id": "a", "text": "Hola."}]}}
    v = common.Video("x", settings)
    assert "no " in render.timing_problem(v)
    v.data.mkdir(parents=True)
    (v.data / "timing.json").write_text(json.dumps({"voice_key": common.voice_key(settings)}))
    assert render.timing_problem(v) is None
    settings["voice"]["lines"][0]["take"] = 1
    assert "changed" in render.timing_problem(v)
    assert render.timing_problem(common.Video("y", {})) is None


# ---------- make ----------


def test_stale_when_missing_or_older_than_an_input(tmp_path):
    src, out = touch(tmp_path / "in.txt"), tmp_path / "out.txt"
    assert make.stale([out], [src])
    touch(out)
    old = time.time() - 100
    os.utime(src, (old, old))
    assert not make.stale([out], [src])
    os.utime(src, None)
    os.utime(out, (old, old))
    assert make.stale([out], [src])
    assert make.stale([], [src])


# ---------- tts ----------


class FakeError(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def test_tts_retries_only_transient_errors():
    assert tts.classify(FakeError(401, "unauthenticated")) == "stop"
    assert tts.classify(FakeError(400, "API key not valid")) == "stop"
    assert tts.classify(FakeError(429, "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel")) == "next"
    assert tts.classify(FakeError(404, "model not found")) == "next"
    assert tts.classify(FakeError(429, "Resource exhausted, per minute")) == "retry"
    assert tts.classify(FakeError(503, "overloaded")) == "retry"
    assert tts.classify(TimeoutError("timed out")) == "retry"
