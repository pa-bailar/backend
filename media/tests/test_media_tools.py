"""The media tools' pure functions: the weekend rule, occurrences, version names, the sticker-band math, loudness
parsing, shelf lives, stale stages, TTS errors. Standard library only (no ffmpeg, no network)."""

import json
import os
import time
from datetime import date
from pathlib import Path

import clean
import common
import cover
import events
import make
import mix
import music
import preflight
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


def test_diff_reads_psnr_ssim_and_vmaf_logs():
    psnr = "n:1 mse_avg:0.00 psnr_avg:inf psnr_y:inf\nn:2 mse_avg:1.2 psnr_avg:41.37 psnr_y:40.1\n"
    assert review.per_frame(psnr, "psnr_avg") == [(float("inf"), 0), (41.37, 1)]
    ssim = "n:1 Y:1.000000 U:1.000000 V:1.000000 All:1.000000 (inf)\nn:2 Y:0.98 U:0.99 V:0.99 All:0.985000 (18.2)\n"
    assert review.per_frame(ssim, "All") == [(1.0, 0), (0.985, 1)]
    report = {"frames": [{"frameNum": 0, "metrics": {"vmaf": 97.43}}, {"frameNum": 1, "metrics": {"vmaf": 88.1}}]}
    assert review.vmaf_frames(report) == [(97.43, 0), (88.1, 1)]


def test_edge_strips_read_from_each_edge_inward():
    # A 4×3 frame: values are 10·row + column.
    frame = bytes(10 * r + c for r in range(3) for c in range(4))
    assert review.edge_strip(frame, 4, 3, "top", 2) == (bytes([0, 1, 2, 3, 10, 11, 12, 13]), 4)
    assert review.edge_strip(frame, 4, 3, "bottom", 1) == (bytes([20, 21, 22, 23]), 4)
    assert review.edge_strip(frame, 4, 3, "left", 2) == (bytes([0, 10, 20, 1, 11, 21]), 3)
    assert review.edge_strip(frame, 4, 3, "right", 1) == (bytes([3, 13, 23]), 3)


def test_reel_margin_content_is_found_by_its_distance_from_the_edge():
    paper = [[220] * 8 for _ in range(6)]
    paper[2][7] = paper[3][7] = paper[4][7] = 30  # ink 0 px from the right edge, rows 2-4
    frame = strip(paper)
    right, width = review.edge_strip(frame, 8, 6, "right", 2)
    assert review.content_top(right, width, min_px=2) == 0
    left, width = review.edge_strip(frame, 8, 6, "left", 2)
    assert review.content_top(left, width, min_px=2) is None


def test_reel_deliverables_are_named_or_inferred():
    renders = {"voice-only": "a", "with-music": "b", "reel": "c"}
    assert review.reel_deliverables({"renders": renders}) == ["reel"]
    assert review.reel_deliverables({"renders": renders, "reel_safe": {"deliverables": []}}) == []
    assert review.REEL == {"top": 108, "bottom": 320, "left": 60, "right": 120}


# ---------- preflight ----------


def probed(**video):
    v = {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "avg_frame_rate": "30/1"}
    v |= {"width": 1080, "height": 1920, "bit_rate": "15000000"} | video
    a = {"codec_type": "audio", "codec_name": "aac", "bit_rate": "128000", "sample_rate": "48000", "channels": 2}
    return {"format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "21.0"}, "streams": [v, a]}


def test_preflight_passes_a_render_and_names_what_instagram_refuses():
    assert preflight.assess(probed(), 40_000_000, "story", False, True) == ([], [])
    fail, _ = preflight.assess(
        probed(codec_name="vp9", avg_frame_rate="120/1", width=1080, height=1080), 1, "reel", False, True
    )
    assert any("codec vp9" in f for f in fail)
    assert any("120.00 fps" in f for f in fail)
    assert any("isn't 9:16" in f for f in fail)
    fail, _ = preflight.assess(probed(width=2160, height=3840, bit_rate="40000000"), 1, "story", False, True)
    assert any("2160 px wide" in f for f in fail) and any("40.0 Mbps" in f for f in fail)
    assert preflight.rate("30000/1001") == pytest.approx(29.97, abs=0.01)


def test_preflight_lengths_sizes_and_the_api():
    long = probed()
    long["format"]["duration"] = "75"
    assert any("Story clip" in f for f in preflight.assess(long, 1, "story", False, True)[0])
    assert preflight.assess(long, 1, "reel", False, True)[0] == []
    short = probed()
    short["format"]["duration"] = "2.5"
    assert any("a Reel is" in f for f in preflight.assess(short, 1, "reel", False, True)[0])
    assert preflight.assess(probed(), 40_000_000, "story", True, True)[0] == [
        "40.0 MB: the API takes a Story video up to 8 MB"
    ]
    fail, warn = preflight.assess(probed(), 1, "story", False, False)
    assert not fail and any("moov" in w for w in warn)
    assert any("moov" in f for f in preflight.assess(probed(), 1, "story", True, False)[0])
    fail, warn = preflight.assess(probed(width=540, height=960), 1, "story", False, True)
    assert not fail and any("under 1080" in w for w in warn)


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def test_moov_first_walks_the_top_level_boxes(tmp_path):
    fast, slow = tmp_path / "fast.mp4", tmp_path / "slow.mp4"
    fast.write_bytes(box(b"ftyp", b"isom") + box(b"moov", b"x" * 20) + box(b"mdat", b"y" * 40))
    slow.write_bytes(box(b"ftyp", b"isom") + box(b"free") + box(b"mdat", b"y" * 40) + box(b"moov", b"x" * 20))
    assert preflight.moov_first(fast) is True
    assert preflight.moov_first(slow) is False
    (tmp_path / "junk.mp4").write_bytes(b"abc")
    assert preflight.moov_first(tmp_path / "junk.mp4") is None


# ---------- cover ----------


def test_cover_grid_crop_is_centered_and_named_by_version(tmp_path, monkeypatch):
    assert cover.grid_crop(1080, 1920) == (1080, 1350, 0, 285)
    assert cover.grid_crop(1080, 1920, (1080, 1440)) == (1080, 1440, 0, 240)
    assert cover.grid_crop(540, 960) == (540, 675, 0, 142)
    monkeypatch.setattr(common, "HOME", tmp_path)
    v = common.Video("teaser-v2", {"version": "2.4", "renders": {"voice-only": "a", "reel": "b"}})
    full, grid = cover.cover_paths(v)
    assert (full.name, grid.name) == ("teaser-v2-v2.4-cover.png", "teaser-v2-v2.4-cover-grid.png")
    assert cover.pick_deliverable(v, None) == "reel"
    assert cover.pick_deliverable(v, "voice-only") == "voice-only"
    with pytest.raises(SystemExit):
        cover.pick_deliverable(v, "story")


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


def test_speech_spans_join_words_across_short_gaps():
    timing = {
        "lines": [{"words": [{"start": 0.5, "end": 0.9}, {"start": 1.0, "end": 1.4}, {"start": 2.0, "end": 2.3}]}]
    }
    assert mix.speech_spans(timing) == [(0.5, 1.4), (2.0, 2.3)]


def test_energies_and_windows_inside_the_spans():
    from array import array

    samples = array("h", [1] * 800 + [2] * 800 + [0] * 100)
    assert mix.energies(samples) == [800.0, 3200.0]
    assert mix.in_spans(6, [(0.05, 0.2)]) == [1, 2, 3]


def test_masking_measures_voice_over_music_where_the_voice_speaks():
    voice = [100.0, 100.0, 100.0, 0.001]
    assert mix.masking(voice, [1.0, 1.0, 1.0, 50.0], [0, 1, 2, 3])[:2] == (20.0, 0.0)
    ratio, share, masked = mix.masking(voice, [1.0, 80.0, 1.0, 1.0], [0, 1, 2])
    assert round(ratio, 1) == 5.6 and share == pytest.approx(1 / 3) and masked == [1]
    assert mix.masking(voice, voice, []) == (float("inf"), 0.0, [])


def test_provenance_is_required_for_the_bed_in_use():
    assert common.provenance_problems({}) == []
    bed = "cache/music/x.wav"
    assert "no " in common.provenance_problems({"bed": bed})[0]
    made = music.provenance("fania", "salsa dura…", 7, 98, 30, "ace-step/ACE-Step-1.5@ca1e85f", "2026-10-04")
    assert set(common.PROVENANCE_FIELDS) <= set(made)
    assert common.provenance_problems({"bed": bed, "provenance": {bed: made}}) == []
    partial = {k: v for k, v in made.items() if k not in ("seed", "reference_audio")} | {"generated": "4 Oct"}
    found = common.provenance_problems({"bed": bed, "provenance": {bed: partial}})
    assert len(found) == 3 and any("'seed'" in p for p in found) and any("date like" in p for p in found)


def test_every_video_with_a_bed_records_its_provenance():
    for folder in sorted((common.MEDIA / "projects").iterdir()):
        if (folder / "video.json").exists():
            settings = common.video(folder.name).settings
            assert common.provenance_problems(settings.get("music", {})) == [], folder.name
            entry = settings.get("music", {}).get("provenance", {}).get(settings.get("music", {}).get("bed"))
            if entry and "prompt_name" in entry:
                assert entry["prompt"] == settings["music"]["prompts"][entry["prompt_name"]]


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
