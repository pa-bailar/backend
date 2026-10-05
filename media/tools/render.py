"""Render a video's deliverables with Remotion, a quick draft, or single frames to look at.

  .venv/Scripts/python media/tools/render.py <video> [deliverable ...]   full quality → out/<video>/<deliverable>.mp4
  .venv/Scripts/python media/tools/render.py <video> --draft [...]       half size, no motion blur → …-draft.mp4
  .venv/Scripts/python media/tools/render.py <video> --frames 90,240,400 [deliverable]  stills → out/<video>/frames/

Deliverables are video.json's "renders" ({file name: composition id}); with none named, all of them. Full renders
take about a minute each (motion blur renders some frames 8–16 times). Draft while iterating; look at frames
before watching; render full only for the owner. Then tools/review.py for keyframes and comparisons.
"""

import argparse
import json
import subprocess
import sys

from common import MEDIA, video


def remotion(*args: str) -> None:
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    done = subprocess.run([npx, "remotion", *args, "--log=error"], cwd=MEDIA)
    if done.returncode:
        raise SystemExit(f"remotion {args[0]} failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("deliverables", nargs="*")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--frames")
    args = parser.parse_args()
    v = video(args.video)
    renders: dict[str, str] = v.settings["renders"]
    names = args.deliverables or list(renders)
    unknown = [n for n in names if n not in renders]
    if unknown:
        raise SystemExit(f"unknown deliverable(s) {unknown}: video.json has {list(renders)}")
    v.out.mkdir(parents=True, exist_ok=True)

    if args.frames:
        comp = renders[names[0]]
        for f in args.frames.split(","):
            dest = v.out / "frames" / f"{names[0]}-{int(f):04d}.png"
            remotion("still", comp, str(dest), f"--frame={int(f)}")
            print(dest.relative_to(MEDIA).as_posix())
        return
    for name in names:
        if args.draft:
            dest = v.out / f"{name}-draft.mp4"
            # Compositions take a `blur` prop (the convention): off for drafts. A file, as cmd.exe mangles JSON.
            props = v.out / "draft-props.json"
            props.write_text(json.dumps({"blur": False}))
            remotion("render", renders[name], str(dest), "--scale=0.5", f"--props={props}")
        else:
            dest = v.out / f"{name}.mp4"
            remotion("render", renders[name], str(dest))
        print(dest.relative_to(MEDIA).as_posix())


if __name__ == "__main__":
    main()
