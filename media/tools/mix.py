"""The soundtracks (48 kHz stereo WAV, exactly the video's length), loudness-normalized, with no click at either end.

  .venv/Scripts/python media/tools/mix.py <video>
  → public/<video>/audio/voice-only.wav   the voice alone (Instagram's music sticker goes under it)
    public/<video>/audio/with-music.wav   voice + the music bed, ducked under the voice
    out/<video>/music-ducked.wav          the bed alone after ducking (to check the balance by ear)
  .venv/Scripts/python media/tools/mix.py <video> --check
      Measures the soundtracks already there against their targets, without mixing.

Reads out/<video>/voice-track.wav (tools/timing.py) and video.json's "music"."bed" (a file in the media home, e.g.
one of tools/music.py's candidates) and "mix": "voice_only_lufs", "with_music_lufs" (default −15 and −14:
brand.json's "loudness"), "bed_db" (the bed's level before ducking, −8), "fade" (seconds in and out, 0.3).
"first_hit": seconds trimmed off the bed's start so its first hit lands on frame 0. Without a bed, only
voice-only.wav is written. A video with no voice (no voice track, no "voice" in video.json) gets music-only.wav: the
bed alone at "music_only_lufs" (−16).

Every soundtrack is measured after normalizing (EBU R128 integrated loudness and true peak). loudnorm silently falls
back to dynamic mode when it can't reach the target linearly, so the mix fails loudly instead: a true peak over
brand.json's true_peak_max (−1 dBTP) or a loudness more than "tolerance" (1 LU) off target exits with an error, keeps
the previous soundtrack, and leaves the rejected one in out/<video>/rejected-<name>.wav to listen to.
"""

import json
import os
import sys
from pathlib import Path

from common import BRAND, HOME, Video, ffmpeg, mix_key, shown, video

LOUD = BRAND["loudness"]
TP = LOUD["true_peak_target"]


def loudnorm(src: Path, dest: Path, target: float, duration: float, fade: float) -> str:
    """Two-pass EBU R128 normalization to `target` LUFS, true peak −1.5 dBTP, padded or cut to `duration`. Returns
    loudnorm's normalization type ("linear", or "dynamic" when it had to compress)."""
    stats = ffmpeg("-i", str(src), "-af", f"loudnorm=I={target}:TP={TP}:LRA=11:print_format=json", "-f", "null", "-")
    m = last_json(stats)
    second = ffmpeg(
        "-i",
        str(src),
        "-af",
        f"loudnorm=I={target}:TP={TP}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:"
        "print_format=json,"
        f"aresample=48000,apad=whole_dur={duration},atrim=0:{duration},"
        # No click at either end: DC removed, a fade-in from true zero, a fade-out.
        f"highpass=f=20,afade=t=in:st=0:d={fade},afade=t=out:st={duration - fade}:d={fade}",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(dest),
    )
    return str(last_json(second).get("normalization_type", "?"))


def last_json(stderr: str) -> dict:
    """The last {…} block ffmpeg printed (loudnorm's report)."""
    return json.loads(stderr[stderr.rindex("{") : stderr.rindex("}") + 1])


def parse_ebur128(stderr: str) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP) from the summary of ffmpeg's ebur128=peak=true."""
    tail = stderr[stderr.rfind("Summary:") :]
    integrated = float(tail.split("I:")[1].split("LUFS")[0])
    peak = float(tail.split("Peak:")[1].split("dBFS")[0])
    return integrated, peak


def measure(path: Path) -> tuple[float, float]:
    return parse_ebur128(ffmpeg("-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"))


def problems(integrated: float, peak: float, target: float) -> list[str]:
    """What's wrong with a soundtrack measured at `integrated` LUFS and `peak` dBTP, against `target` LUFS."""
    out = []
    if peak > LOUD["true_peak_max"]:
        out.append(f"true peak {peak:+.1f} dBTP is over {LOUD['true_peak_max']:+.1f}")
    if abs(integrated - target) > LOUD["tolerance"]:
        out.append(f"{integrated:.1f} LUFS is more than {LOUD['tolerance']} LU off {target}")
    return out


def normalize(v: Video, src: Path, name: str, target: float, fade: float) -> str | None:
    """Normalize `src` into public/<video>/audio/<name>.wav through a temporary file, replaced only when the result
    passes (else it goes to out/<video>/rejected-<name>.wav). Returns the problem, if any."""
    dest = v.public / "audio" / f"{name}.wav"
    rejected = v.out / f"rejected-{name}.wav"
    tmp = dest.with_name(f".{dest.stem}.tmp.wav")
    kind = loudnorm(src, tmp, target, v.duration, fade)
    integrated, peak = measure(tmp)
    wrong = problems(integrated, peak, target)
    line = f"{shown(dest)}: {integrated:.1f} LUFS (target {target}), true peak {peak:+.1f} dBTP, loudnorm {kind}"
    if wrong:
        os.replace(tmp, rejected)
        print(f"{line}  REJECTED → {shown(rejected)}")
        return f"{dest.name}: {'; '.join(wrong)}"
    os.replace(tmp, dest)
    print(line)
    return None


def targets(v: Video) -> dict[str, float]:
    """The soundtracks this video has, with their loudness targets."""
    mix = v.settings.get("mix", {})
    music = v.settings.get("music", {})
    if "voice" not in v.settings and not (v.out / "voice-track.wav").exists():
        return {"music-only": float(mix.get("music_only_lufs", LOUD["music_only"]))}
    out = {"voice-only": float(mix.get("voice_only_lufs", LOUD["voice_only"]))}
    if music.get("bed"):
        out["with-music"] = float(mix.get("with_music_lufs", LOUD["with_music"]))
    return out


def check(v: Video) -> list[str]:
    wrong = []
    for name, target in targets(v).items():
        path = v.public / "audio" / f"{name}.wav"
        if not path.exists():
            wrong.append(f"{name}.wav: missing")
            continue
        integrated, peak = measure(path)
        print(f"{shown(path)}: {integrated:.1f} LUFS (target {target}), true peak {peak:+.1f} dBTP")
        wrong += [f"{name}.wav: {p}" for p in problems(integrated, peak, target)]
    return wrong


def mix_music(v: Video, voice: Path, bed: Path, raw: Path, ducked: Path) -> None:
    """The bed from its first hit, under the voice; the voice keys a compressor that pulls it down a further ~5 dB
    while someone speaks; out over the last 1.2 s. The voice (the compressor's key) is padded to the full length:
    sidechaincompress stops at its shortest input."""
    music = v.settings["music"]
    mix = v.settings.get("mix", {})
    duration = v.duration
    graph = (
        f"[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,volume=1.0,apad=whole_dur={duration},asplit=2[v][key];"
        f"[1:a]atrim=start={float(music.get('first_hit', 0))},asetpts=PTS-STARTPTS,aresample=48000,"
        f"volume={mix.get('bed_db', -8)}dB,afade=t=out:st={duration - 1.2}:d=1.2[m];"
        f"[m][key]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=350:makeup=1[duck];"
        f"[duck]asplit=2[duck1][duck2];"
        f"[v][duck1]amix=inputs=2:duration=longest:normalize=0[mix]"
    )
    ffmpeg(
        *("-i", str(voice), "-i", str(bed), "-filter_complex", graph),
        *("-map", "[mix]", "-t", str(duration), str(raw)),
        *("-map", "[duck2]", "-t", str(duration), str(ducked)),
    )


def main(name: str) -> None:
    v = video(name)
    duration = v.duration
    fade = float(v.settings.get("mix", {}).get("fade", 0.3))
    voice = v.out / "voice-track.wav"
    public = v.public / "audio"
    public.mkdir(parents=True, exist_ok=True)
    v.out.mkdir(parents=True, exist_ok=True)
    music = v.settings.get("music", {})
    goals = targets(v)
    wrong: list[str | None] = []
    if "music-only" in goals:
        if not music.get("bed"):
            raise SystemExit("no voice and no music bed in video.json: nothing to mix")
        raw = v.out / "music-only-raw.wav"
        trim = f"atrim=start={float(music.get('first_hit', 0))},asetpts=PTS-STARTPTS,aresample=48000"
        fade_out = f"afade=t=out:st={duration - 1.2}:d=1.2"
        ffmpeg("-i", str(HOME / music["bed"]), "-af", f"{trim},{fade_out}", "-t", str(duration), str(raw))
        # −16 by default: a bed alone at −14 reaches 0 dBTP (no voice to make the loudness).
        wrong.append(normalize(v, raw, "music-only", goals["music-only"], fade))
    else:
        if not voice.exists():
            raise SystemExit(f"no {shown(voice)}: run tools/timing.py {name} first")
        tmp = v.out / "voice-48k.wav"
        ffmpeg("-i", str(voice), "-af", "aresample=48000", "-ac", "2", str(tmp))
        wrong.append(normalize(v, tmp, "voice-only", goals["voice-only"], fade))
        if "with-music" in goals:
            raw, ducked = v.out / "with-music-raw.wav", v.out / "music-ducked.wav"
            mix_music(v, voice, HOME / music["bed"], raw, ducked)
            wrong.append(normalize(v, raw, "with-music", goals["with-music"], fade))
            print(f"{shown(ducked)}: the bed alone after ducking (not normalized)")
    failed = [w for w in wrong if w]
    if failed:
        raise SystemExit("mix failed (the previous soundtracks stay):\n  " + "\n  ".join(failed))
    (public / "mix.key").write_text(mix_key(v))  # what these were made from (tools/make.py)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help") or len(args) > 2 or (len(args) == 2 and args[1] != "--check"):
        raise SystemExit(__doc__)
    if len(args) == 2:
        problems_found = check(video(args[0]))
        if problems_found:
            raise SystemExit("\n".join(problems_found))
    else:
        main(args[0])
