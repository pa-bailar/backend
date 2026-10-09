"""One-take voices (tools/timing.py build_one_take): Whisper's words cut the take and split its lines. Needs numpy (the
toolkit's venv); skipped where it isn't installed (the backend's ci)."""

import json

import pytest

np = pytest.importorskip("numpy")
import timing  # noqa: E402  (after numpy is known to be there)

# The bug-squash pass of 8 Oct 2026.


def one_take(monkeypatch, tmp_path, lines: list[str], heard_words: list[str]):
    """timing.build_one_take on a silent take, Whisper replaced by `heard_words` half a second apart."""
    voice = {"name": "Despina", "one_take": True, "lines": [{"id": f"l{i}", "text": t} for i, t in enumerate(lines)]}
    v = type("V", (), {"name": "x", "fps": 30, "duration": 10.0, "settings": {"voice": voice}})()
    v.out, v.data = tmp_path / "out", tmp_path / "data"
    v.out.mkdir()
    heard = [{"word": w, "start": 0.5 * i + 0.2, "end": 0.5 * i + 0.6, "p": 0.9} for i, w in enumerate(heard_words)]
    monkeypatch.setattr(timing, "read", lambda p: np.zeros(int(0.5 * len(heard_words) * 24000 + 48000), np.float32))
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
