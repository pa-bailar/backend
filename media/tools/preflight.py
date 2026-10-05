"""Instagram pre-flight: will Instagram take this file as it is? ffprobe against Instagram's published video specs.

  .venv/Scripts/python media/tools/preflight.py <video.mp4 …> [--story | --reel] [--api]
      --story / --reel   which limits apply (default: "reel" in the file name means a Reel, anything else a Story)
      --api              the Graph API's stricter limits too (a Story's file at most 8 MB; the moov atom first)

Checks: the container (MP4 or MOV), the video codec (H.264 or HEVC, 4:2:0, progressive), 23–60 fps, 9:16, at most
1920 px wide, a video bitrate up to 25 Mbps, the length (a Story clip up to 60 s; a Reel 3 s to 15 min), the size
(up to 1 GB), AAC audio (Instagram plays 128 kbps: more is a note, not a failure), at most 48 kHz and 2 channels, and
whether the moov atom comes first (faststart). Exit code 1 when something fails; warnings don't.

tools/render.py --review runs it on every render. Standard library + ffprobe: any Python runs it.
"""

import argparse
import struct
from fractions import Fraction
from pathlib import Path

from common import probe

# Instagram's limits (help center and the Graph API's Reels and Stories specs, Oct 2026). One place to change them.
CODECS = {"h264", "hevc"}
FPS = (23, 60)
MAX_WIDTH = 1920
MAX_VIDEO_BPS = 25_000_000
AUDIO_BPS = 128_000  # what Instagram plays; a higher bitrate is re-encoded down
MAX_RATE = 48_000
STORY_MAX_S = 60.0  # per clip: a longer Story is cut into 60 s clips
REEL_S = (3.0, 15 * 60.0)
MAX_BYTES = 1_000_000_000
API_STORY_BYTES = 8_000_000
ASPECT = 9 / 16


def rate(text: str | None) -> float:
    """ffprobe's "30/1" or "30000/1001" → frames per second (0 when unknown)."""
    try:
        return float(Fraction(text or "0"))
    except (ValueError, ZeroDivisionError):
        return 0.0


def moov_first(path: Path) -> bool | None:
    """Whether the moov atom comes before mdat (faststart), walking the top-level boxes; None when neither is found."""
    seen: list[str] = []
    with path.open("rb") as f:
        at = 0
        while True:
            f.seek(at)
            header = f.read(16)
            if len(header) < 8:
                break
            size, kind = struct.unpack(">I4s", header[:8])
            if size == 1 and len(header) == 16:
                size = struct.unpack(">Q", header[8:16])[0]
            seen.append(kind.decode("latin-1"))
            if kind in (b"moov", b"mdat") or size < 8:  # size 0: to the end of the file; smaller is broken
                break
            at += size
    if "moov" in seen:
        return True
    return False if "mdat" in seen else None


def video_problems(video: dict, fmt: dict, audio: dict | None, fail: list[str], warn: list[str]) -> None:
    codec = video.get("codec_name")
    if codec not in CODECS:
        fail.append(f"video codec {codec}: Instagram takes H.264 or HEVC")
    pix = str(video.get("pix_fmt", ""))
    if "420" not in pix:
        fail.append(f"pixel format {pix}: Instagram takes 4:2:0 (yuv420p)")
    if video.get("field_order") not in (None, "progressive", "unknown"):
        warn.append(f"field order {video.get('field_order')}: Instagram wants progressive scan")
    fps = rate(video.get("avg_frame_rate")) or rate(video.get("r_frame_rate"))
    if not FPS[0] <= fps <= FPS[1]:
        fail.append(f"{fps:.2f} fps: Instagram takes {FPS[0]}–{FPS[1]} fps")
    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    if not h or abs(w / h - ASPECT) > 0.01:
        fail.append(f"{w}×{h} isn't 9:16")
    if w > MAX_WIDTH:
        fail.append(f"{w} px wide: Instagram takes up to {MAX_WIDTH}")
    elif w < 1080:
        warn.append(f"{w}×{h}: under 1080 wide (a draft?): Instagram shows Stories and Reels at 1080×1920")
    # Some muxers leave the stream's bitrate out: then the file's, less the audio.
    bps = int(video.get("bit_rate") or 0) or int(fmt.get("bit_rate") or 0) - int((audio or {}).get("bit_rate") or 0)
    if bps > MAX_VIDEO_BPS:
        fail.append(f"video {bps / 1e6:.1f} Mbps: Instagram takes up to {MAX_VIDEO_BPS / 1e6:.0f} Mbps")


def audio_problems(audio: dict, fail: list[str], warn: list[str]) -> None:
    if audio.get("codec_name") != "aac":
        fail.append(f"audio codec {audio.get('codec_name')}: Instagram takes AAC")
    abps = int(audio.get("bit_rate") or 0)
    if abps > AUDIO_BPS:
        warn.append(f"audio {abps // 1000} kbps: Instagram plays {AUDIO_BPS // 1000} kbps (it re-encodes; fine)")
    if int(audio.get("sample_rate") or 0) > MAX_RATE:
        warn.append(f"audio at {audio.get('sample_rate')} Hz: Instagram takes up to {MAX_RATE}")
    if int(audio.get("channels") or 0) > 2:
        warn.append(f"{audio.get('channels')} audio channels: Instagram takes mono or stereo")


def assess(info: dict, size: int, kind: str, api: bool, faststart: bool | None, suffix: str = ".mp4"):
    """(failures, warnings) for ffprobe's -show_format -show_streams output of one file."""
    fail: list[str] = []
    warn: list[str] = []
    fmt = info.get("format", {})
    names = set(str(fmt.get("format_name", "")).split(","))
    if not ({"mp4", "mov"} & names) or suffix.lower() not in (".mp4", ".mov"):
        fail.append(f"container {fmt.get('format_name')} ({suffix}): Instagram takes MP4 or MOV")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or (video or {}).get("duration") or 0)
    if video is None:
        fail.append("no video stream")
    else:
        video_problems(video, fmt, audio, fail, warn)
    if audio is None:
        warn.append("no audio stream (fine for a Story that gets Instagram's music; a Reel needs its own)")
    else:
        audio_problems(audio, fail, warn)
    if kind == "story" and duration > STORY_MAX_S:
        fail.append(f"{duration:.1f} s: a Story clip is at most {STORY_MAX_S:.0f} s (Instagram cuts it)")
    if kind == "reel" and not REEL_S[0] <= duration <= REEL_S[1]:
        fail.append(f"{duration:.1f} s: a Reel is {REEL_S[0]:.0f} s to {REEL_S[1] / 60:.0f} min")
    if size > MAX_BYTES:
        fail.append(f"{size / 1e6:.0f} MB: Instagram takes up to {MAX_BYTES / 1e9:.0f} GB")
    if api and kind == "story" and size > API_STORY_BYTES:
        fail.append(f"{size / 1e6:.1f} MB: the API takes a Story video up to {API_STORY_BYTES / 1e6:.0f} MB")
    if faststart is False:
        (fail if api else warn).append("the moov atom comes after the media (not faststart): the API wants it first")
    return fail, warn


def check(path: Path, kind: str | None = None, api: bool = False) -> bool:
    """Check one file; prints the verdict and returns whether it passes."""
    kind = kind or ("reel" if "reel" in path.name.lower() else "story")
    info = probe(path)
    fail, warn = assess(info, path.stat().st_size, kind, api, moov_first(path), path.suffix)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    summary = (
        f"{video.get('codec_name')} {video.get('width')}×{video.get('height')} "
        f"{rate(video.get('avg_frame_rate')):.0f} fps {int(video.get('bit_rate') or 0) / 1e6:.1f} Mbps, "
        f"{audio.get('codec_name', 'no audio')} {int(audio.get('bit_rate') or 0) // 1000} kbps, "
        f"{float(info['format'].get('duration', 0)):.2f} s, {path.stat().st_size / 1e6:.1f} MB"
    )
    verdict = "FAIL" if fail else "ok"
    print(f"{path.name} ({kind}{', API' if api else ''}): {verdict}: {summary}")
    for line in fail:
        print(f"  FAIL {line}")
    for line in warn:
        print(f"  warn {line}")
    return not fail


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", type=Path, nargs="+")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--story", dest="kind", action="store_const", const="story")
    kind.add_argument("--reel", dest="kind", action="store_const", const="reel")
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    ok = [check(f, args.kind, args.api) for f in args.files]
    raise SystemExit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
