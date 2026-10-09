"""The voice track and its timing: join the cached TTS lines with natural gaps, then time every word with Whisper.

Run with the faster-whisper venv (D:\\AI\\whisper):
  D:/AI/whisper/.venv/Scripts/python media/tools/timing.py <video>
      → out/<video>/voice-track.wav (media home) and projects/<video>/data/timing.json (line and word times, video
        seconds: the track starts at video time 0, after "lead" seconds of silence)
  D:/AI/whisper/.venv/Scripts/python media/tools/timing.py --transcribe <file.wav> …
      → what Whisper hears (QA for a take: a swallowed word shows up here)

video.json's "voice": "lead" (silence before the first word), "max_pause" (pauses inside a line, e.g. at "…",
are kept but not longer than this), and per line "gap" (silence after it). With "one_take": true (media/AUDIO.md), the
one recording of the whole script is cut to its words instead (her own pauses kept) and each line is found in it by
its first two words; "gap" and "max_pause" don't apply. Composition code reads the times with makeTiming()
(src/lib/timing.ts): line("c4").start, word("c2", "dónde").
"""

import argparse
import json
import wave
from pathlib import Path

import numpy as np
from common import DIRECTION, TTS_RATE, _norm, one_take_path, script_text, shown, tts_path, video, voice_key

RATE = TTS_RATE


def read(path: Path) -> np.ndarray:
    if not path.exists():
        raise SystemExit(f"{path.name} isn't cached: run tools/tts.py first")
    with wave.open(str(path)) as f:
        assert f.getframerate() == RATE and f.getnchannels() == 1 and f.getsampwidth() == 2, path
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def trim(audio: np.ndarray, threshold: float = 0.012, pad: float = 0.06) -> np.ndarray:
    """Cut the silence TTS leaves around a line, keeping a few ms so consonants aren't clipped."""
    win = int(0.01 * RATE)
    frames = np.abs(audio[: len(audio) // win * win]).reshape(-1, win).max(axis=1)
    loud = np.nonzero(frames > threshold)[0]
    if not len(loud):
        return audio
    start = max(0, loud[0] * win - int(pad * RATE))
    end = min(len(audio), (loud[-1] + 1) * win + int(pad * RATE))
    return audio[start:end]


def tighten(audio: np.ndarray, max_pause: float, threshold: float = 0.012) -> np.ndarray:
    """Shorten silent runs inside a line to `max_pause` seconds (keeps the breath, drops the dead air)."""
    win = int(0.01 * RATE)
    quiet = np.abs(audio[: len(audio) // win * win]).reshape(-1, win).max(axis=1) < threshold
    keep, run = [], 0
    for q in quiet:
        run = run + 1 if q else 0
        keep.append(not q or run * 0.01 <= max_pause)
    mask = np.repeat(np.array(keep), win)
    return np.concatenate([audio[: len(mask)][mask], audio[len(mask) :]])


def write(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def whisper():
    from faster_whisper import WhisperModel

    return WhisperModel("medium", device="cpu", compute_type="int8")


def words_of(path: Path, prompt: str) -> list[dict]:
    """Whisper's words (start, end, probability) of a file, with the script as a hint so names come out as written."""
    segments, _ = whisper().transcribe(
        str(path), language="es", word_timestamps=True, initial_prompt=prompt, vad_filter=False, beam_size=5
    )
    return [
        {"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3), "p": round(w.probability, 2)}
        for s in segments
        for w in s.words
    ]


def build_one_take(v, voice: dict, lead: float) -> None:
    """A one-take recording ("voice"."one_take"): cut from just before its first word to just after its last (the
    model leaves noise past the end: a clipped burst after "link" in the puente take of 8 Oct 2026), its own pauses
    kept, after `lead` seconds of silence; each line found in it by its first two words, in order."""
    script = script_text(voice)
    raw_path = one_take_path(voice)
    raw = read(raw_path)
    heard = words_of(raw_path, script)
    if not heard:
        raise SystemExit(f"Whisper heard nothing in {raw_path.name}")
    # The cut follows Whisper's first and last words: one it missed there would be cut out of the track, silently
    # ("link" dropped, the bug-squash pass of 8 Oct 2026). Listen to the take; re-record it if the word isn't there.
    said = [_norm(w) for w in script.split()]
    got = [_norm(w["word"]) for w in heard]
    for where, want, have in (("first", said[0], got[0]), ("last", said[-1], got[-1])):
        if want != have:
            raise SystemExit(
                f'Whisper\'s {where} word is "{have}", the script\'s "{want}": it would be cut off the track'
            )
    start, end = max(0.0, heard[0]["start"] - 0.06), heard[-1]["end"] + 0.12
    take = raw[int(start * RATE) : int(end * RATE)].copy()
    fade = int(0.08 * RATE)
    take[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    track = np.concatenate([np.zeros(int(lead * RATE), np.float32), take, np.zeros(int(0.3 * RATE), np.float32)])
    out = v.out / "voice-track.wav"

    shift = lead - start
    words = [{**w, "start": round(w["start"] + shift, 3), "end": round(w["end"] + shift, 3)} for w in heard]
    counts = [len(line["text"].split()) for line in voice["lines"]]
    if got == said:  # heard word for word: each line by its own count
        starts = [sum(counts[:k]) for k in range(len(counts))]
    else:
        # Each line starts at its first two words, searched in order (two words: "El viernes" vs "El sábado"), not
        # before most of the line before it ("Y el domingo" inside "El sábado y el domingo hay salsa").
        starts, at = [], 0
        for line, count in zip(voice["lines"], counts, strict=True):
            want = [_norm(w) for w in line["text"].split()[:2]]
            found = next(
                (i for i in range(at, len(words)) if [_norm(w["word"]) for w in words[i : i + len(want)]] == want), None
            )
            if found is None:
                heard_text = " ".join(w["word"] for w in words[at:])
                raise SystemExit(
                    f'line {line["id"]}: "{" ".join(want)}" not heard after word {at} (heard: {heard_text})'
                )
            starts.append(found)
            at = found + max(1, count - 2)
    lines = []
    for k, line in enumerate(voice["lines"]):
        mine = words[starts[k] : starts[k + 1] if k + 1 < len(starts) else len(words)]
        lines.append(
            {"id": line["id"], "text": line["text"], "start": mine[0]["start"], "end": mine[-1]["end"], "words": mine}
        )
    write(out, track)  # only now: a take whose lines aren't found leaves the track and timing.json as they were
    print(f"{out.name}: {len(track) / RATE:.2f} s, one take (the video is {v.duration} s)")
    write_timing(
        v, voice, track, out, lead, lines, segments=[], note="One take: line and word times are Whisper medium (es)."
    )


def write_timing(
    v, voice: dict, track: np.ndarray, out: Path, lead: float, lines: list, segments: list, note: str
) -> None:
    timing = {
        "fps_hint": v.fps,
        "duration": round(len(track) / RATE, 3),
        "voice": f"(media home) {shown(out)}",
        "lead": lead,
        # what the track was made from: tools/render.py refuses to render when the voice changed since
        "voice_key": voice_key(v.settings),
        "lines": lines,
        "segments": segments,
        "note": note,
    }
    v.data.mkdir(parents=True, exist_ok=True)
    # "\n" endings on Windows too: a committed file that doesn't flip line endings with each run.
    (v.data / "timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    for line in lines:
        print(f"{line['start']:6.2f}–{line['end']:6.2f} {line['id']}: " + " ".join(w["word"] for w in line["words"]))


def build(name: str) -> None:
    v = video(name)
    voice = v.settings["voice"]
    direction = voice.get("direction", DIRECTION)
    lead = float(voice.get("lead", 0.55))
    if voice.get("one_take"):
        return build_one_take(v, voice, lead)
    max_pause = float(voice.get("max_pause", 0.32))
    parts, lines, t = [np.zeros(int(lead * RATE), np.float32)], [], lead
    for line in voice["lines"]:
        audio = tighten(trim(read(tts_path(line["text"], voice["name"], direction, line.get("take", 0)))), max_pause)
        lines.append(
            {"id": line["id"], "text": line["text"], "start": round(t, 3), "end": round(t + len(audio) / RATE, 3)}
        )
        gap = float(line.get("gap", 0.3))
        parts += [audio, np.zeros(int(gap * RATE), np.float32)]
        t += len(audio) / RATE + gap
    track = np.concatenate([*parts, np.zeros(int(0.3 * RATE), np.float32)])
    out = v.out / "voice-track.wav"
    write(out, track)
    print(f"{out.name}: {len(track) / RATE:.2f} s (the video is {v.duration} s)")

    prompt = " ".join(line["text"] for line in voice["lines"])
    segments, _ = whisper().transcribe(
        str(out), language="es", word_timestamps=True, initial_prompt=prompt, vad_filter=False, beam_size=5
    )
    words, segs = [], []
    for s in segments:
        segs.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()})
        for w in s.words:
            words.append(
                {
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "p": round(w.probability, 2),
                }
            )
    for line in lines:
        line["words"] = []
    for w in words:  # each word to the one line it falls in (or the nearest, within 0.15 s), never to two
        mid = (w["start"] + w["end"]) / 2
        gap = [max(line["start"] - mid, mid - line["end"], 0) for line in lines]
        nearest = min(range(len(lines)), key=gap.__getitem__)
        if gap[nearest] <= 0.15:
            lines[nearest]["words"].append(dict(w))
    for line in lines:
        for w in line["words"]:  # Whisper stretches a first word over the silence before it
            w["start"] = max(w["start"], line["start"])
            w["end"] = min(max(w["end"], w["start"] + 0.05), line["end"] + 0.1)
    write_timing(
        v,
        voice,
        track,
        out,
        lead,
        lines,
        segs,
        note="Times are video seconds. Line start/end are exact (from the joined files); "
        "word times are Whisper medium (es).",
    )


def transcribe(paths: list[str]) -> None:
    model = whisper()
    for p in paths:
        segments, info = model.transcribe(p, language="es", vad_filter=False)
        text = " ".join(s.text.strip() for s in segments)
        print(f"{Path(p).name} ({info.duration:.1f} s): {text or '[nothing]'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", nargs="?")
    parser.add_argument("--transcribe", nargs="+", metavar="WAV")
    args = parser.parse_args()
    if args.transcribe:
        transcribe(args.transcribe)
    elif args.video:
        build(args.video)
    else:
        parser.print_help()
