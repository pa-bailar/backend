"""One-take voices (tools/timing.py build_one_take): Whisper's words cut the take and split its lines. Needs numpy (the
toolkit's venv); skipped where it isn't installed (the backend's ci)."""

import json

import pytest

np = pytest.importorskip("numpy")
import timing  # noqa: E402  (after numpy is known to be there)

# The bug-squash pass of 8 Oct 2026.


def one_take(monkeypatch, tmp_path, lines: list[str], heard_words: list[str], first: float = 0.2, take=None):
    """timing.build_one_take on a take (silent unless given), Whisper replaced by `heard_words` half a second apart
    from `first` seconds."""
    voice = {"name": "Despina", "one_take": True, "lines": [{"id": f"l{i}", "text": t} for i, t in enumerate(lines)]}
    v = type("V", (), {"name": "x", "fps": 30, "duration": 10.0, "settings": {"voice": voice}})()
    v.out, v.data = tmp_path / "out", tmp_path / "data"
    v.out.mkdir()
    heard = [
        {"word": w, "start": 0.5 * i + first, "end": 0.5 * i + first + 0.4, "p": 0.9} for i, w in enumerate(heard_words)
    ]
    audio = take if take is not None else np.zeros(int(0.5 * len(heard_words) * 24000 + 48000), np.float32)
    monkeypatch.setattr(timing, "read", lambda p: audio)
    monkeypatch.setattr(timing, "words_of", lambda p, s: heard)
    timing.build_one_take(v, voice, 0.15)
    return json.loads((v.data / "timing.json").read_text(encoding="utf-8"))


def test_a_one_take_whose_last_word_whisper_missed_fails_instead_of_cutting_it(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match='last word is "el"'):
        one_take(
            monkeypatch,
            tmp_path,
            ["Todo en Pa' Bailar.", "Te dejo el link."],
            ["Todo", "en", "Pa'", "Bailar.", "Te", "dejo", "el"],
        )
    assert not (tmp_path / "out" / "voice-track.wav").exists()  # nothing written half-way


def test_one_take_writes_each_lines_words(tmp_path, monkeypatch):
    # Where the lines split is common.line_starts (tested without numpy in test_media_tools.py).
    lines = ["El sábado y el domingo hay salsa.", "Y el domingo, bachata."]
    got = one_take(monkeypatch, tmp_path, lines, " ".join(lines).split())
    assert [" ".join(w["word"] for w in line["words"]) for line in got["lines"]] == lines


def test_a_burst_at_the_very_start_of_a_take_is_not_kept(tmp_path, monkeypatch):
    # finde-halloween v4–v5 (22 Oct 2026): a full-scale 5 ms burst at sample 0, Whisper's first word at 0.0 s.
    take = np.zeros(4 * timing.RATE, np.float32)
    take[: int(0.005 * timing.RATE)] = 1.0
    written = {}
    monkeypatch.setattr(timing, "write", lambda path, audio: written.setdefault("track", audio.copy()))
    one_take(monkeypatch, tmp_path, ["Todo en Pa' Bailar."], ["Todo", "en", "Pa'", "Bailar."], first=0.0, take=take)
    lead = int(0.15 * timing.RATE)
    assert np.abs(written["track"][: lead + int(0.03 * timing.RATE)]).max() < 0.05
