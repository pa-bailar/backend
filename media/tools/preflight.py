"""Instagram pre-flight: will Instagram take this file as it is? ffprobe against Instagram's published video specs.

  .venv/Scripts/python media/tools/preflight.py <video.mp4 …> [--story | --reel] [--api]
      --story / --reel   which limits apply (default: "reel" in the file name means a Reel, anything else a Story)
      --api              the Graph API's limits too (tools/publish.py): a Reel's file at most 300 MB, a Story's 100 MB
                         and 3–60 s; the moov atom first; an edit list is a warning

Checks: the container (MP4 or MOV), the video codec (H.264 or HEVC, 4:2:0, progressive), 23–60 fps, 9:16, at most
1920 px wide, a video bitrate up to 25 Mbps, the length (a Story clip up to 60 s; a Reel 3 s to 15 min, and a warning
past 3 min, where Instagram stops recommending a Reel in Explore and the Reels tab), the size (up to 1 GB), AAC audio
(Instagram plays 128 kbps: more is a note, not a failure), at most 48 kHz and 2 channels, and whether the moov atom
comes first (faststart). Exit code 1 when something fails; warnings don't.

tools/render.py --review runs it on every render; tools/publish.py runs it with --api before anything else.
Standard library + ffprobe: any Python runs it.
"""

import argparse
import struct
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path

from common import probe

# Instagram's limits, one place to change them. The Graph API's video specs for Reels and Stories (Oct 2026):
# https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
CODECS = {"h264", "hevc"}
FPS = (23, 60)
MAX_WIDTH = 1920
MAX_VIDEO_BPS = 25_000_000
AUDIO_BPS = 128_000  # what Instagram plays; a higher bitrate is re-encoded down
MAX_RATE = 48_000
STORY_MAX_S = 60.0  # per clip: the app cuts a longer Story into 60 s clips (the API refuses it)
REEL_S = (3.0, 15 * 60.0)
# Recommended in Explore and the Reels tab up to 3 minutes (Instagram, January 2025; 90 s before): a longer Reel
# reaches followers only. A warning, not a failure.
REELS_TAB_MAX_S = 180.0
# Uploading in the app (Meta's Reels sample, github.com/fbsamples/reels_publishing_apis, states 1 GB too).
MAX_BYTES = 1_000_000_000
# The API (tools/publish.py): a Reel's video up to 300 MB; a Story's up to 100 MB and 3–60 s. (8 MB is the API's
# limit for a Story *image*, a JPEG, not a video.)
API_BYTES = {"reel": 300_000_000, "story": 100_000_000}
API_STORY_S = (3.0, 60.0)
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


def boxes(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[bytes, int, int]]:
    """(kind, payload start, payload end) of the boxes in data[start:end]."""
    end = len(data) if end is None else end
    at = start
    while at + 8 <= end:
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        head = 8
        if size == 1 and at + 16 <= end:
            size, head = struct.unpack(">Q", data[at + 8 : at + 16])[0], 16
        elif size == 0:
            size = end - at
        if size < head:
            return
        yield kind, at + head, min(at + size, end)
        at += size


def top_box(path: Path, wanted: bytes) -> bytes | None:
    """The payload of the first top-level box of a kind (e.g. moov), or None."""
    with path.open("rb") as f:
        at = 0
        while True:
            f.seek(at)
            header = f.read(16)
            if len(header) < 8:
                return None
            size, kind = struct.unpack(">I4s", header[:8])
            head = 8
            if size == 1 and len(header) == 16:
                size, head = struct.unpack(">Q", header[8:16])[0], 16
            if kind == wanted:
                f.seek(at + head)
                return f.read(size - head) if size >= head else f.read()
            if size < 8:
                return None
            at += size


def edit_lists(path: Path) -> bool | None:
    """Whether a track has an edit list (moov/trak/edts/elst; the API's spec says "no edit lists"); None without a
    moov."""
    moov = top_box(path, b"moov")
    if moov is None:
        return None
    for kind, a, b in boxes(moov):
        if kind != b"trak":
            continue
        for inner, x, y in boxes(moov, a, b):
            if inner == b"edts" and any(e == b"elst" for e, _, _ in boxes(moov, x, y)):
                return True
    return False


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


def assess(
    info: dict,
    size: int,
    kind: str,
    api: bool,
    faststart: bool | None,
    suffix: str = ".mp4",
    edit_list: bool | None = None,
):
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
    elif kind == "reel" and duration > REELS_TAB_MAX_S:
        warn.append(
            f"{duration:.1f} s: over {REELS_TAB_MAX_S / 60:.0f} min, Instagram doesn't recommend a Reel in Explore or "
            "the Reels tab (followers still see it)"
        )
    if api and kind == "story" and not API_STORY_S[0] <= duration <= API_STORY_S[1]:
        fail.append(f"{duration:.1f} s: the API takes a Story video of {API_STORY_S[0]:.0f}–{API_STORY_S[1]:.0f} s")
    if size > MAX_BYTES:
        fail.append(f"{size / 1e6:.0f} MB: Instagram takes up to {MAX_BYTES / 1e9:.0f} GB")
    if api and size > API_BYTES[kind]:
        what = "a Reel" if kind == "reel" else "a Story video"
        fail.append(f"{size / 1e6:.1f} MB: the API takes {what} up to {API_BYTES[kind] / 1e6:.0f} MB")
    if faststart is False:
        (fail if api else warn).append("the moov atom comes after the media (not faststart): the API wants it first")
    if api and edit_list:
        warn.append("a track has an edit list: the API's spec says none (a warning until Instagram refuses one)")
    return fail, warn


def check(path: Path, kind: str | None = None, api: bool = False) -> bool:
    """Check one file; prints the verdict and returns whether it passes."""
    kind = kind or ("reel" if "reel" in path.name.lower() else "story")
    info = probe(path)
    fail, warn = assess(info, path.stat().st_size, kind, api, moov_first(path), path.suffix, edit_lists(path))
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
