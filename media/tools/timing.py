"""The voice track and its timing: join the cached TTS lines with natural gaps, then time every word with Whisper.

Run with the faster-whisper venv (D:\\AI\\whisper):
  D:/AI/whisper/.venv/Scripts/python media/tools/timing.py <video>
      → media/out/<video>/voice-track.wav and projects/<video>/data/timing.json (line and word times, video
        seconds: the track starts at video time 0, after "lead" seconds of silence)
  D:/AI/whisper/.venv/Scripts/python media/tools/timing.py --transcribe <file.wav> …
      → what Whisper hears (QA for a take: a swallowed word shows up here)

video.json's "voice": "lead" (silence before the first word), "max_pause" (pauses inside a line, e.g. at "…",
are kept but not longer than this), and per line "gap" (silence after it). Composition code reads the times with
makeTiming() (src/lib/timing.ts): line("c4").start, word("c2", "dónde").
"""

import argparse
import json
import wave
from pathlib import Path

import numpy as np
from common import TTS_RATE, tts_path, video
from tts import DIRECTION

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


def build(name: str) -> None:
    v = video(name)
    voice = v.settings["voice"]
    direction = voice.get("direction", DIRECTION)
    lead = float(voice.get("lead", 0.55))
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
    for line in lines:  # which words fall in each line
        line["words"] = [w for w in words if line["start"] - 0.15 <= (w["start"] + w["end"]) / 2 <= line["end"] + 0.15]
        for w in line["words"]:  # Whisper stretches a first word over the silence before it
            w["start"] = max(w["start"], line["start"])
            w["end"] = min(max(w["end"], w["start"] + 0.05), line["end"] + 0.1)
    timing = {
        "fps_hint": v.fps,
        "duration": round(len(track) / RATE, 3),
        "voice": f"media/out/{name}/voice-track.wav",
        "lead": lead,
        "lines": lines,
        "segments": segs,
        "note": "Times are video seconds. Line start/end are exact (from the joined files); "
        "word times are Whisper medium (es).",
    }
    v.data.mkdir(parents=True, exist_ok=True)
    (v.data / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    for line in lines:
        print(f"{line['start']:6.2f}–{line['end']:6.2f} {line['id']}: " + " ".join(w["word"] for w in line["words"]))


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
