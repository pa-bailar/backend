"""Tempo, beats, first hit and loudness of music candidates, plus a spectrogram strip to compare them.

Run with the faster-whisper venv (it has librosa):
  D:/AI/whisper/.venv/Scripts/python media/tools/analyze.py media/cache/music/*.wav [--out media/out/<video>]
  → prints a table; writes music-analysis.json and music-analysis.png to --out (default media/out/music)

"first hit" is the time to put in video.json's "music"."first_hit"; "ibi std" is how steady the beat is (lower is
steadier); the cyan lines on the picture are the detected beats.
"""

import argparse
import json
from pathlib import Path

import librosa
import librosa.display
import matplotlib
import numpy as np
from common import MEDIA, ffmpeg

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (after choosing the backend)


def lufs(path: str) -> float:
    err = ffmpeg("-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-")
    tail = err[err.rfind("Summary:") :]
    return float(tail.split("I:")[1].split("LUFS")[0])


def analyze(path: str):
    y, sr = librosa.load(path, sr=22050, mono=True)
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, start_bpm=98)
    beat_t = librosa.frames_to_time(beats, sr=sr)
    times = librosa.times_like(onset, sr=sr)
    # first strong hit: first onset above 60% of the max in the first 3 s
    first = times[np.argmax(onset[: int(3 * sr / 512)] > 0.6 * onset.max())] if onset.max() else 0.0
    rms = librosa.feature.rms(y=y)[0]
    ibi = np.diff(beat_t)
    info = {
        "file": Path(path).name,
        "bpm": round(float(np.atleast_1d(tempo)[0]), 1),
        "first_hit_s": round(float(first), 2),
        "beats": [round(float(b), 3) for b in beat_t],
        "ibi_std_ms": round(float(ibi.std() * 1000), 1) if len(ibi) else None,
        "lufs": lufs(path),
        "dynamics_db": round(float(20 * np.log10(np.percentile(rms, 95) / max(np.percentile(rms, 10), 1e-6))), 1),
    }
    return info, (y, sr, beat_t)


def main(paths: list[str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    results, fig = [], plt.figure(figsize=(14, 2.6 * len(paths)))
    for i, p in enumerate(paths):
        info, (y, sr, beat_t) = analyze(p)
        results.append(info)
        ax = fig.add_subplot(len(paths), 1, i + 1)
        spec = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=2048, hop_length=512)), ref=np.max)
        librosa.display.specshow(spec, sr=sr, hop_length=512, x_axis="time", y_axis="log", ax=ax, cmap="magma")
        ax.vlines(beat_t, 40, 9000, color="cyan", alpha=0.35, linewidth=0.6)
        ax.set_title(f"{info['file']}  {info['bpm']} bpm  first hit {info['first_hit_s']} s  {info['lufs']} LUFS")
        print(
            f"{info['file']:40} bpm {info['bpm']:6} first hit {info['first_hit_s']:5} s"
            f"  ibi std {info['ibi_std_ms']} ms  {info['lufs']} LUFS  dyn {info['dynamics_db']} dB"
        )
    fig.tight_layout()
    fig.savefig(out / "music-analysis.png", dpi=60)
    (out / "music-analysis.json").write_text(json.dumps(results, indent=1))
    print(f"→ {(out / 'music-analysis.png').relative_to(MEDIA).as_posix()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", type=Path, default=MEDIA / "out" / "music")
    args = parser.parse_args()
    main(args.files, args.out.resolve())
