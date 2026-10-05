"""A Reel's cover image: one frame of the Reel at full size, and the centered crop the profile grid shows.

  .venv/Scripts/python media/tools/cover.py <video> --at 19.5 | 19.5s | f585 | c4 | c4:link [--deliverable reel]
      [--grid 1080x1350]
  → out/<video>/<video>-v<version>-cover.png        1080×1920, to upload as the Reel's cover
    out/<video>/<video>-v<version>-cover-grid.png   1080×1350, the centered 4:5 crop the profile grid shows (--grid
                                                    for another shape: 1080x1440 is 3:4)

The frame is rendered by tools/stills.mjs (from the code, with motion blur: not a frame out of the H.264 file), from
the deliverable given (default: the first Reel one in video.json's "renders", else the first). Times as everywhere:
seconds, a frame (f585), a line's start (c4) or a word's start (c4:link), from data/timing.json. Named by video.json's
"version" like the renders, so each cut keeps its own cover. Then the Reel's safe zones are checked on the cover
(tools/review.py reel: a warning when content sits under the Reel's UI), and the grid crop is the part to judge for
the profile: anything important outside it is lost there.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import BRAND, MEDIA, Video, at_seconds, ffmpeg, shown, video

GRID = (1080, 1350)  # the profile grid's 4:5 crop of a 9:16 cover, centered


def grid_crop(width: int, height: int, grid: tuple[int, int] = GRID) -> tuple[int, int, int, int]:
    """The centered crop (w, h, x, y) of a width×height frame with the grid's aspect ratio, scaled to the frame."""
    w = width
    h = round(width * grid[1] / grid[0])
    return w, h, 0, (height - h) // 2


def cover_paths(v: Video) -> tuple[Path, Path]:
    stem = f"{v.name}-v{v.version}-cover"
    return v.out / f"{stem}.png", v.out / f"{stem}-grid.png"


def pick_deliverable(v: Video, wanted: str | None) -> str:
    import review

    renders = list(v.settings["renders"])
    if wanted:
        if wanted not in renders:
            raise SystemExit(f"no deliverable {wanted!r}: video.json has {renders}")
        return wanted
    reels = review.reel_deliverables(v.settings)
    return reels[0] if reels else renders[0]


def still(v: Video, deliverable: str, frame: int, folder: Path) -> Path:
    """One full-size still through tools/stills.mjs, into `folder`."""
    node = "node.exe" if sys.platform == "win32" else "node"
    cmd = [node, str(MEDIA / "tools" / "stills.mjs"), v.name, deliverable, "--at", f"f{frame}", "--out", str(folder)]
    if subprocess.run(cmd, cwd=MEDIA).returncode:
        raise SystemExit("stills failed")
    found = sorted(folder.glob("*.png"))
    if not found:
        raise SystemExit("stills.mjs wrote no image")
    return found[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--at", required=True)
    parser.add_argument("--deliverable")
    parser.add_argument("--grid", default=f"{GRID[0]}x{GRID[1]}", help="the grid crop's shape, WxH")
    args = parser.parse_args()
    v = video(args.video)
    timing_file = v.data / "timing.json"
    timing = json.loads(timing_file.read_text(encoding="utf-8")) if timing_file.exists() else None
    frame = min(round(at_seconds(args.at, timing, v.fps) * v.fps), round(v.duration * v.fps) - 1)
    deliverable = pick_deliverable(v, args.deliverable)
    full, grid = cover_paths(v)
    v.out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cover-"))
    try:
        shutil.move(still(v, deliverable, frame, tmp), full)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    shape = tuple(int(n) for n in args.grid.lower().split("x"))
    w, h, x, y = grid_crop(BRAND["canvas"]["width"], BRAND["canvas"]["height"], (shape[0], shape[1]))
    ffmpeg("-i", str(full), "-vf", f"crop={w}:{h}:{x}:{y}", str(grid))
    print(f"{shown(full)} ({deliverable}, frame {frame} = {frame / v.fps:.2f} s)")
    print(f"{shown(grid)} (the profile grid's {args.grid} crop: y {y}–{y + h} of the cover)")
    import review

    review.reel(full, [], v.fps)


if __name__ == "__main__":
    main()
