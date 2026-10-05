"""Look at a render without watching it: keyframe sheets with the safe zones, side-by-sides, and a regression check.

  python media/tools/review.py sheet <video.mp4> [--at 1.5,4,9.2 | --every 2] [--out sheet.png]
      One row of keyframes (360 px wide each) with the safe zones drawn in cyan (no text above 250 px or below
      1580 px at 1080×1920). Default: every 2 s. → next to the video, <name>-sheet.png
  python media/tools/review.py compare <a.mp4> <b.mp4> [--labels v1,v2] [--from 0 --to 4.6] [--out ab.mp4]
      Side by side at half size, labeled, with b's sound: for the owner to see what changed.
  python media/tools/review.py diff <a.mp4> <b.mp4>
      PSNR per frame (∞ = identical): the worst frames first. After a refactor, renders should match.

Standard library + ffmpeg: any Python runs it.
"""

import argparse
import os
import re
from pathlib import Path

from common import ffmpeg, probe

FONT = "C\\:/Windows/Fonts/arial.ttf"
SAFE = (250, 1580)  # px at 1920 tall


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def sheet(path: Path, at: list[float], out: Path) -> None:
    tmp = out.parent / f".{out.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    files = []
    for i, t in enumerate(at):
        f = tmp / f"{i:02d}.png"
        ffmpeg("-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", str(f))
        files.append(f)
    inputs = sum((["-i", str(f)] for f in files), [])
    lines = (
        f"drawbox=y=ih*{SAFE[0] / 1920:.4f}:w=iw:h=1:color=cyan@0.8:t=fill,"
        f"drawbox=y=ih*{SAFE[1] / 1920:.4f}:w=iw:h=1:color=cyan@0.8:t=fill"
    )
    label = f"drawtext=fontfile='{FONT}':fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6:x=8:y=8"
    graph = ";".join(f"[{i}]scale=360:-1,{lines},{label}:text='{t:.2f} s'[p{i}]" for i, t in enumerate(at))
    graph += ";" + "".join(f"[p{i}]" for i in range(len(at))) + f"hstack={len(at)}"
    ffmpeg(*inputs, "-filter_complex", graph, str(out))
    for f in files:
        f.unlink()
    tmp.rmdir()
    print(out.as_posix())


def compare(a: Path, b: Path, labels: list[str], start: float, end: float | None, out: Path) -> None:
    span = ["-ss", str(start)] + (["-t", str(end - start)] if end else [])
    label = "drawtext=fontfile='{}':fontsize=40:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=24:y=24:text="
    label = label.format(FONT)
    ffmpeg(
        *span,
        *("-i", str(a)),
        *span,
        *("-i", str(b)),
        "-filter_complex",
        f"[0:v]scale=540:960,{label}'{labels[0]}'[a];[1:v]scale=540:960,{label}'{labels[1]}'[b];[a][b]hstack=2[v]",
        *("-map", "[v]", "-map", "1:a?", "-c:v", "libx264", "-crf", "20", "-preset", "slow", "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)),
    )
    print(out.as_posix())


def diff(a: Path, b: Path) -> None:
    log = a.parent / f".psnr-{a.stem}.log"
    # A relative path: a drive letter's colon would end the filter option.
    rel = Path(os.path.relpath(log)).as_posix()
    ffmpeg("-i", str(a), "-i", str(b), "-lavfi", f"[0:v][1:v]psnr=stats_file='{rel}'", "-f", "null", "-")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("video", type=Path)
    s.add_argument("--at")
    s.add_argument("--every", type=float, default=2.0)
    s.add_argument("--out", type=Path)
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
    args = parser.parse_args()

    if args.cmd == "sheet":
        if args.at:
            at = [float(t) for t in args.at.split(",")]
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
