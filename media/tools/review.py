"""Look at a render without watching it: keyframe sheets with the safe zones, side-by-sides, and a regression check.

  python media/tools/review.py sheet <video.mp4> [--at 1.5,4,f255,c4:link --timing <video> | --every 2] [--out …]
      One row of keyframes (360 px wide each) with the safe zones drawn in cyan (no text above 250 px or below
      1580 px at 1080×1920: brand.json's "safe"). Default: every 2 s. → next to the video, <name>-sheet.png
  python media/tools/review.py compare <a.mp4> <b.mp4> [--labels v1,v2] [--from 0 --to 4.6] [--out ab.mp4]
      Side by side at half size, labeled, with b's sound: for the owner to see what changed.
  python media/tools/review.py diff <a.mp4> <b.mp4>
      PSNR per frame (∞ = identical): the worst frames first. After a refactor, renders should match.
  python media/tools/review.py band <story.mp4 | still.png …> [--video <name>] [--allow 4.2-4.3,5.75-6.45]
      The Stories' sticker band (brand.json "stickerBand": y 0–250 at 1920 tall, plus a 2 px margin) must stay
      empty on every frame: anything that isn't the frame's background above y 252 fails, with the frames and how
      high it reached. Prints how close content comes. --video takes the allowed spans from video.json's
      "sticker_band"."allow" (full-frame transitions, where the background itself sweeps through the band).
      Any size works (a half-size draft too). Exit code 1 when something enters.
  python media/tools/review.py reel <reel.mp4 | cover.png …> [--video <name>] [--allow 4.2-4.3]
      The Reel's safe zones (brand.json "reelSafe": 108 px at the top, 320 at the bottom, 60 left, 120 right at
      1080×1920, where Instagram's Reel UI sits): content in those margins is a WARNING (images may run into them,
      words never do), listed per side with the frames and how close to the edge it gets. --video takes the spans
      from video.json's "reel_safe"."allow". Exit code 0 either way.

Standard library + ffmpeg: any Python runs it.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from common import BRAND, at_seconds, ffmpeg, probe, tool, video

FONT = "C\\:/Windows/Fonts/arial.ttf"
HEIGHT = BRAND["canvas"]["height"]
WIDTH = BRAND["canvas"]["width"]
SAFE = (BRAND["safe"]["top"], BRAND["safe"]["bottom"])  # px at the canvas's height
REEL = {side: BRAND["reelSafe"][side] for side in ("top", "bottom", "left", "right")}  # px from each edge
BAND = BRAND["stickerBand"]
LIMIT = BAND["bottom"] + BAND["margin"]  # nothing above this y (canvas px)
LOOK = LIMIT + 60  # how far down the band check looks, to say how close content comes
TOLERANCE = 28  # gray levels from the background that count as content (the grain and H.264 stay within ~12)


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def sheet(path: Path, at: list[float], out: Path, reel: bool = False) -> None:
    """`reel`: also draw the Reel's safe zones (brand.json "reelSafe") in magenta."""
    if not at:
        raise SystemExit("no times to take frames at: the video is shorter than --every, give --at")
    tmp = Path(tempfile.mkdtemp(prefix="sheet-"))
    try:
        _sheet(path, at, out, tmp, reel)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(out.as_posix())


def _sheet(path: Path, at: list[float], out: Path, tmp: Path, reel: bool) -> None:
    files = []
    for i, t in enumerate(at):
        f = tmp / f"{i:02d}.png"
        ffmpeg("-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", str(f))
        files.append(f)
    inputs = sum((["-i", str(f)] for f in files), [])
    lines = (
        f"drawbox=y=ih*{SAFE[0] / HEIGHT:.4f}:w=iw:h=1:color=cyan@0.8:t=fill,"
        f"drawbox=y=ih*{SAFE[1] / HEIGHT:.4f}:w=iw:h=1:color=cyan@0.8:t=fill"
    )
    if reel:
        lines += (
            f",drawbox=y=ih*{REEL['top'] / HEIGHT:.4f}:w=iw:h=1:color=magenta@0.8:t=fill"
            f",drawbox=y=ih*{1 - REEL['bottom'] / HEIGHT:.4f}:w=iw:h=1:color=magenta@0.8:t=fill"
            f",drawbox=x=iw*{REEL['left'] / WIDTH:.4f}:w=1:h=ih:color=magenta@0.8:t=fill"
            f",drawbox=x=iw*{1 - REEL['right'] / WIDTH:.4f}:w=1:h=ih:color=magenta@0.8:t=fill"
        )
    label = f"drawtext=fontfile='{FONT}':fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6:x=8:y=8"
    graph = ";".join(f"[{i}]scale=360:-1,{lines},{label}:text='{t:.2f} s'[p{i}]" for i, t in enumerate(at))
    if len(at) > 1:  # hstack needs two inputs at least
        graph += ";" + "".join(f"[p{i}]" for i in range(len(at))) + f"hstack={len(at)}"
    else:
        graph = graph.removesuffix("[p0]")
    ffmpeg(*inputs, "-filter_complex", graph, str(out))


def drawtext_value(text: str) -> str:
    """Text for drawtext's quoted text option (drawn with expansion=none, so % is literal): ' becomes ’, and a colon
    and a backslash are escaped."""
    return text.replace("\\", "\\\\").replace("'", "’").replace(":", r"\:")


def compare(a: Path, b: Path, labels: list[str], start: float, end: float | None, out: Path) -> None:
    span = ["-ss", str(start)] + (["-t", str(end - start)] if end else [])
    label = (
        f"drawtext=fontfile='{FONT}':expansion=none:fontsize=40:fontcolor=white:box=1:boxcolor=black@0.6:"
        "boxborderw=12:x=24:y=24:text="
    )
    ffmpeg(
        *span,
        *("-i", str(a)),
        *span,
        *("-i", str(b)),
        "-filter_complex",
        f"[0:v]scale=540:960,{label}'{drawtext_value(labels[0])}'[a];"
        f"[1:v]scale=540:960,{label}'{drawtext_value(labels[1])}'[b];[a][b]hstack=2[v]",
        *("-map", "[v]", "-map", "1:a?", "-c:v", "libx264", "-crf", "20", "-preset", "slow", "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)),
    )
    print(out.as_posix())


def diff(a: Path, b: Path) -> None:
    log = a.parent / f".psnr-{a.stem}.log"
    # Run in the log's folder and name it bare: a drive letter's colon would end the filter option.
    a, b = a.resolve(), b.resolve()
    ffmpeg(
        "-i",
        str(a),
        "-i",
        str(b),
        "-lavfi",
        f"[0:v][1:v]psnr=stats_file='{log.name}'",
        "-f",
        "null",
        "-",
        cwd=log.parent,
    )
    rows = []
    for line in log.read_text().splitlines():
        n = re.search(r"n:(\d+)", line)
        p = re.search(r"psnr_avg:(\S+)", line)
        if n and p:
            rows.append((float(p.group(1)), int(n.group(1))))
    log.unlink()
    rows.sort()
    same = sum(1 for p, _ in rows if p == float("inf"))
    print(f"{len(rows)} frames, {same} identical; worst (PSNR dB, frame): {rows[:8]}")


def background(sample: bytes, bucket: int = 6) -> int:
    """The most common gray level in a sample of the band (the paper, or a full-bleed color)."""
    level = Counter(v // bucket for v in sample).most_common(1)[0][0]
    return level * bucket + bucket // 2


def content_top(frame: bytes, width: int, tolerance: int = TOLERANCE, min_px: int = 3) -> int | None:
    """The first row (from the top) of a gray frame strip where at least `min_px` pixels differ from the background by
    more than `tolerance`; None when the strip is all background."""
    ref = background(frame[::97] or frame)
    table = bytes(1 if abs(v - ref) > tolerance else 0 for v in range(256))
    for row in range(len(frame) // width):
        if frame[row * width : (row + 1) * width].translate(table).count(1) >= min_px:
            return row
    return None


def band_tops(path: Path) -> Iterator[int | None]:
    """For each frame of a video or image: the topmost y (canvas px) of content in the top LOOK px, or None."""
    stream = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
    w, h = int(stream["width"]), int(stream["height"])
    rows = round(h * LOOK / HEIGHT)
    size = w * rows
    min_px = max(2, round(3 * w / 1080))
    # Gray before cropping: a yuv420 crop rounds an odd height down, which would misalign the frames.
    cmd = [tool("ffmpeg"), "-v", "error", "-i", str(path), "-fps_mode", "passthrough"]
    cmd += ["-vf", f"format=gray,crop={w}:{rows}:0:0", "-f", "rawvideo", "-"]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        assert proc.stdout
        while len(buf := proc.stdout.read(size)) == size:
            top = content_top(buf, w, min_px=min_px)
            yield None if top is None else round(top * HEIGHT / h)


def runs(hits: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Consecutive frames → (first, last, topmost y)."""
    out: list[tuple[int, int, int]] = []
    for frame, y in hits:
        if out and frame == out[-1][1] + 1:
            first, _, top = out[-1]
            out[-1] = (first, frame, min(top, y))
        else:
            out.append((frame, frame, y))
    return out


def parse_spans(text: str) -> list[tuple[float, float]]:
    """ "4.2-4.3,5.75-6.45" → [(4.2, 4.3), (5.75, 6.45)]."""
    return [(float(a), float(b)) for a, b in (s.split("-") for s in text.split(",") if s.strip())]


def band(path: Path, allow: list[tuple[float, float]], fps: int) -> bool:
    """Check one render or still; prints the verdict and returns whether the band stayed empty."""
    tops = list(band_tops(path))
    allowed = lambda f: any(a <= f / fps <= b for a, b in allow)  # noqa: E731
    seen = [(f, y) for f, y in enumerate(tops) if y is not None]
    inside = [(f, y) for f, y in seen if y < LIMIT and not allowed(f)]
    excused = [(f, y) for f, y in seen if y < LIMIT and allowed(f)]
    clear = [(f, y) for f, y in seen if y >= LIMIT]
    closest = min(clear, key=lambda fy: fy[1], default=None)
    near = f"; closest content: y {closest[1]} at {closest[0] / fps:.2f} s" if closest else ""
    name = path.name
    if excused:
        print(f"{name}: {len(excused)} frames in allowed spans {allow} (full-frame transitions)")
    if inside:
        print(f"{name}: FAIL, content above y {LIMIT} in {len(inside)} of {len(tops)} frames{near}")
        for first, last, top in runs(inside):
            print(f"  {first / fps:6.2f}–{last / fps:6.2f} s (frames {first}–{last}): reaches y {top}")
        return False
    print(f"{name}: band clear, nothing above y {LIMIT} in {len(tops)} frames{near}")
    return True


def allowed_spans(name: str, key: str = "sticker_band") -> list[tuple[float, float]]:
    """video.json's "sticker_band"."allow" (or "reel_safe"."allow"): [[from, to, "why"], …] (seconds)."""
    spans = video(name).settings.get(key, {}).get("allow", [])
    return [(float(s[0]), float(s[1])) for s in spans]


# ---------- the Reel's safe zones ----------


def edge_strip(frame: bytes, w: int, h: int, side: str, depth: int) -> tuple[bytes, int]:
    """The `depth` rows (top, bottom) or columns (left, right) of a gray w×h frame nearest one edge, as rows ordered
    from that edge inward (a column becomes a row), and the strip's width: content_top() then gives how close to the
    edge content gets."""
    if side == "top":
        return frame[: depth * w], w
    if side == "bottom":
        return b"".join(frame[(h - 1 - r) * w : (h - r) * w] for r in range(depth)), w
    if side == "left":
        return b"".join(frame[c::w] for c in range(depth)), h
    return b"".join(frame[w - 1 - c :: w] for c in range(depth)), h


def reel_depths(path: Path) -> Iterator[dict[str, int | None]]:
    """For each frame of a video or image: per side, how close to the edge content gets inside the Reel's margins
    (canvas px from the edge), or None when that margin is all background. Read at half size or smaller (2 px steps)."""
    stream = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
    w, h = int(stream["width"]), int(stream["height"])
    if h > HEIGHT // 2:
        w, h = round(w * (HEIGHT // 2) / h / 2) * 2, HEIGHT // 2
    scale = HEIGHT / h  # canvas px per analyzed px (the canvas is 9:16, as is every deliverable)
    depth = {side: max(1, round(px / scale)) for side, px in REEL.items()}
    min_px = max(2, round(3 * w / WIDTH))
    cmd = [tool("ffmpeg"), "-v", "error", "-i", str(path), "-fps_mode", "passthrough"]
    cmd += ["-vf", f"scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        assert proc.stdout
        while len(buf := proc.stdout.read(w * h)) == w * h:
            out: dict[str, int | None] = {}
            for side, d in depth.items():
                strip, width = edge_strip(buf, w, h, side, d)
                top = content_top(strip, width, min_px=min_px)
                out[side] = None if top is None else round(top * scale)
            yield out


def reel_deliverables(settings: dict) -> list[str]:
    """The Reel deliverables of a video: video.json's "reel_safe"."deliverables", else every render named "…reel…"."""
    named = settings.get("reel_safe", {}).get("deliverables")
    return list(named) if named is not None else [d for d in settings.get("renders", {}) if "reel" in d]


def reel(path: Path, allow: list[tuple[float, float]], fps: int) -> list[str]:
    """Check one Reel render or still against the Reel's safe zones; prints and returns the warnings (one per side)."""
    frames = list(reel_depths(path))
    allowed = lambda f: any(a <= f / fps <= b for a, b in allow)  # noqa: E731
    warnings = []
    for side in REEL:
        hits = [(f, d[side]) for f, d in enumerate(frames) if d[side] is not None and not allowed(f)]
        if not hits:
            continue
        spans = runs([(f, y) for f, y in hits if y is not None])
        where = ", ".join(
            (f"{a / fps:.2f}–{b / fps:.2f} s" if a != b else f"{a / fps:.2f} s") + f" (to {edge} px from the edge)"
            for a, b, edge in spans[:8]
        )
        more = f" and {len(spans) - 8} more" if len(spans) > 8 else ""
        warnings.append(f"{side} {REEL[side]} px: content in {len(hits)} of {len(frames)} frames: {where}{more}")
    name = path.name
    if warnings:
        print(f"{name}: WARNING, content where the Reel's UI sits (fine for images, never for words):")
        for w in warnings:
            print(f"  {w}")
    else:
        print(f"{name}: Reel margins clear in {len(frames)} frames")
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("video", type=Path)
    s.add_argument("--at")
    s.add_argument("--every", type=float, default=2.0)
    s.add_argument("--out", type=Path)
    s.add_argument("--timing", metavar="VIDEO", help="the video whose timing.json --at's line:word refer to")
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--labels", default="A,B")
    c.add_argument("--from", dest="start", type=float, default=0.0)
    c.add_argument("--to", dest="end", type=float)
    c.add_argument("--out", type=Path)
    d = sub.add_parser("diff")
    d.add_argument("a", type=Path)
    d.add_argument("b", type=Path)
    b = sub.add_parser("band")
    b.add_argument("files", type=Path, nargs="+")
    b.add_argument("--video")
    b.add_argument("--allow", default="")
    b.add_argument("--fps", type=int, default=BRAND["canvas"]["fps"])
    r = sub.add_parser("reel")
    r.add_argument("files", type=Path, nargs="+")
    r.add_argument("--video")
    r.add_argument("--allow", default="")
    r.add_argument("--fps", type=int, default=BRAND["canvas"]["fps"])
    args = parser.parse_args()

    if args.cmd == "band":
        allow = parse_spans(args.allow) + (allowed_spans(args.video) if args.video else [])
        ok = [band(f, allow, args.fps) for f in args.files]
        raise SystemExit(0 if all(ok) else 1)
    if args.cmd == "reel":
        allow = parse_spans(args.allow) + (allowed_spans(args.video, "reel_safe") if args.video else [])
        for f in args.files:
            reel(f, allow, args.fps)
        return
    if args.cmd == "sheet":
        if args.at:
            timing = json.loads((video(args.timing).data / "timing.json").read_text("utf-8")) if args.timing else None
            at = [round(at_seconds(t, timing), 3) for t in args.at.split(",")]
        else:
            total = duration_of(args.video)
            at = [round(t * args.every + args.every / 2, 2) for t in range(int(total / args.every))]
        sheet(args.video, at, args.out or args.video.with_name(f"{args.video.stem}-sheet.png"))
    elif args.cmd == "compare":
        out = args.out or args.b.with_name(f"{args.a.stem}-vs-{args.b.stem}.mp4")
        compare(args.a, args.b, args.labels.split(","), args.start, args.end, out)
    else:
        diff(args.a, args.b)


if __name__ == "__main__":
    main()
