"""The soundtracks (48 kHz stereo WAV, exactly the video's length), loudness-normalized, with no click at either end.

  .venv/Scripts/python media/tools/mix.py <video>
  → public/<video>/audio/voice-only.wav   the voice alone (Instagram's music sticker goes under it)
    public/<video>/audio/with-music.wav   voice + the music bed, ducked under the voice
    out/<video>/music-ducked.wav          the bed alone after ducking (to check the balance by ear)

Reads media/out/<video>/voice-track.wav (tools/timing.py) and video.json's "music"."bed" (a file under media/,
e.g. one of tools/music.py's candidates) and "mix": "voice_only_lufs", "with_music_lufs" (default −15 and −14:
brand.json's "loudness"), "bed_db" (the bed's level before ducking, −8), "fade" (seconds in and out, 0.3).
"first_hit": seconds trimmed off the bed's start so its first hit lands on frame 0. Without a bed, only
voice-only.wav is written. A video with no voice (no voice track, no "voice" in video.json) gets music-only.wav: the
bed alone at "music_only_lufs" (−16).
"""

import json
import sys
from pathlib import Path

from common import BRAND, MEDIA, Video, ffmpeg, video

LOUD = BRAND["loudness"]
TP = LOUD["true_peak_target"]


def loudnorm(src: Path, dest: Path, target: float, duration: float, fade: float) -> None:
    """Two-pass EBU R128 normalization to `target` LUFS, true peak −1.5 dBTP, padded or cut to `duration`."""
    stats = ffmpeg("-i", str(src), "-af", f"loudnorm=I={target}:TP={TP}:LRA=11:print_format=json", "-f", "null", "-")
    m = json.loads(stats[stats.rindex("{") : stats.rindex("}") + 1])
    ffmpeg(
        "-i",
        str(src),
        "-af",
        f"loudnorm=I={target}:TP={TP}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
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


def lufs(path: Path) -> str:
    err = ffmpeg("-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-")
    tail = err[err.rfind("Summary:") :]
    i = tail.split("I:")[1].split("LUFS")[0].strip()
    peak = tail.split("Peak:")[1].split("dBFS")[0].strip()
    return f"{i} LUFS, true peak {peak} dBFS"


def music_only(v: Video, bed: Path, first_hit: float, mix: dict, duration: float, fade: float) -> None:
    """A video without a voice: the bed from its first hit, out over the last 1.2 s, normalized."""
    raw = v.out / "music-only-raw.wav"
    ffmpeg(
        *(
            "-i",
            str(bed),
            "-af",
            f"atrim=start={first_hit},asetpts=PTS-STARTPTS,aresample=48000,afade=t=out:st={duration - 1.2}:d=1.2",
        ),
        *("-t", str(duration), str(raw)),
    )
    dest = v.public / "audio" / "music-only.wav"
    # −16 by default: a bed alone at −14 reaches 0 dBTP (no voice to make the loudness).
    loudnorm(raw, dest, float(mix.get("music_only_lufs", LOUD["music_only"])), duration, fade)
    print(f"{dest.relative_to(MEDIA).as_posix()}: {lufs(dest)}")


def main(name: str) -> None:
    v = video(name)
    duration = v.duration
    mix = v.settings.get("mix", {})
    fade = float(mix.get("fade", 0.3))
    voice = v.out / "voice-track.wav"
    public = v.public / "audio"
    public.mkdir(parents=True, exist_ok=True)
    v.out.mkdir(parents=True, exist_ok=True)
    music = v.settings.get("music", {})
    if "voice" not in v.settings and not voice.exists():
        if not music.get("bed"):
            raise SystemExit("no voice and no music bed in video.json: nothing to mix")
        music_only(v, MEDIA / music["bed"], float(music.get("first_hit", 0)), mix, duration, fade)
        return
    if not voice.exists():
        raise SystemExit(f"no {voice.relative_to(MEDIA).as_posix()}: run tools/timing.py {name} first")
    tmp = v.out / "voice-48k.wav"
    ffmpeg("-i", str(voice), "-af", "aresample=48000", "-ac", "2", str(tmp))
    loudnorm(tmp, public / "voice-only.wav", float(mix.get("voice_only_lufs", LOUD["voice_only"])), duration, fade)
    written = [public / "voice-only.wav"]

    if music.get("bed"):
        bed = MEDIA / music["bed"]
        first_hit = float(music.get("first_hit", 0))
        # The bed from its first hit, under the voice; the voice keys a compressor that pulls it down a further
        # ~5 dB while someone speaks; out over the last 1.2 s. The voice (the compressor's key) is padded to the
        # full length: sidechaincompress stops at its shortest input.
        graph = (
            f"[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,volume=1.0,apad=whole_dur={duration},asplit=2[v][key];"
            f"[1:a]atrim=start={first_hit},asetpts=PTS-STARTPTS,aresample=48000,volume={mix.get('bed_db', -8)}dB,"
            f"afade=t=out:st={duration - 1.2}:d=1.2[m];"
            f"[m][key]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=350:makeup=1[duck];"
            f"[duck]asplit=2[duck1][duck2];"
            f"[v][duck1]amix=inputs=2:duration=longest:normalize=0[mix]"
        )
        raw = v.out / "with-music-raw.wav"
        ducked = v.out / "music-ducked.wav"
        ffmpeg(
            *("-i", str(voice), "-i", str(bed), "-filter_complex", graph),
            *("-map", "[mix]", "-t", str(duration), str(raw)),
            *("-map", "[duck2]", "-t", str(duration), str(ducked)),
        )
        loudnorm(raw, public / "with-music.wav", float(mix.get("with_music_lufs", LOUD["with_music"])), duration, fade)
        written += [public / "with-music.wav", ducked]

    for f in written:
        print(f"{f.relative_to(MEDIA).as_posix()}: {lufs(f)}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        raise SystemExit(__doc__)
    main(sys.argv[1])
