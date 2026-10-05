"""Render a video's deliverables with Remotion, a quick draft, or single frames to look at.

  .venv/Scripts/python media/tools/render.py <video> [deliverable ...]   full quality → out/<video>/<deliverable>.mp4
  .venv/Scripts/python media/tools/render.py <video> --draft [...]       half size, no motion blur → …-draft.mp4
  .venv/Scripts/python media/tools/render.py <video> --frames 90,240,400 [deliverable]  stills → out/<video>/frames/
  --strict    refuse (instead of warning) when the material is past its shelf life

Deliverables are video.json's "renders" ({file name: composition id}); with none named, all of them. Full renders
take about a minute each (motion blur renders some frames 8–16 times). Draft while iterating; look at frames
before watching; render full only for the owner. Then tools/review.py for keyframes and comparisons.

Before rendering it checks the material:
- shelf life: app.json's "shelfLife", events.json's "to" and screens.json's clocks are the last day the video is
  true; past it, a warning (--strict: an error). Re-capture, or post before then.
- timing: a video with a voice needs data/timing.json made from the current lines (tools/timing.py stores a key of
  the lines, takes, gaps and recorded audio); if the voice changed since, it refuses: run timing.py and mix.py.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from common import MEDIA, Video, bogota_today, shown, video, voice_key


def remotion(*args: str) -> None:
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    done = subprocess.run([npx, "remotion", *args, "--log=error"], cwd=MEDIA)
    if done.returncode:
        raise SystemExit(f"remotion {args[0]} failed")


def first_day(text: object) -> date | None:
    """The date a shelf-life field starts with ("2026-10-10 (the screens' "Hoy"…)", "2026-10-10T19:00:00-05:00")."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", str(text or ""))
    return date.fromisoformat(m.group(1)) if m else None


def shelf_lives(data: Path) -> list[tuple[str, date]]:
    """Each dated piece of material in a video's data/ and the last day it's true."""
    out: list[tuple[str, date]] = []

    def read(name: str) -> dict:
        path = data / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    if day := first_day(read("app.json").get("shelfLife")):
        out.append(("app.json shelfLife", day))
    if day := first_day(read("events.json").get("to")):
        out.append(("events.json to", day))
    for name, screen in read("screens.json").items():
        if day := first_day(screen.get("now")):
            out.append((f"screens.json {name}", day))
    return out


def expired(lives: list[tuple[str, date]], today: date) -> list[str]:
    return [f"{what} {day.isoformat()}" for what, day in lives if day < today]


def timing_problem(v: Video) -> str | None:
    """Why data/timing.json can't be trusted for the current voice, or None."""
    if not v.settings.get("voice"):
        return None
    path = v.data / "timing.json"
    if not path.exists():
        return f"no {shown(path)}: run tools/timing.py {v.name}"
    stored = json.loads(path.read_text(encoding="utf-8")).get("voice_key")
    if stored is None:
        return f"{shown(path)} has no voice_key (it predates the check): run tools/timing.py {v.name}"
    if stored != voice_key(v.settings):
        return (
            f"the voice changed since {shown(path)} was made (a line, take, gap or recording): "
            f"run tools/timing.py {v.name}, then tools/mix.py {v.name}"
        )
    return None


def preflight(v: Video, strict: bool) -> None:
    """Refuse to render stale material (see the docstring)."""
    if problem := timing_problem(v):
        raise SystemExit(f"refusing to render: {problem}")
    old = expired(shelf_lives(v.data), bogota_today())
    if old:
        message = f"past its shelf life (today is {bogota_today().isoformat()}): {', '.join(old)}"
        if strict:
            raise SystemExit(f"refusing to render (--strict): {message}")
        print(f"WARNING: {message}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("deliverables", nargs="*")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--frames")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    v = video(args.video)
    renders: dict[str, str] = v.settings["renders"]
    names = args.deliverables or list(renders)
    unknown = [n for n in names if n not in renders]
    if unknown:
        raise SystemExit(f"unknown deliverable(s) {unknown}: video.json has {list(renders)}")
    preflight(v, args.strict)
    v.out.mkdir(parents=True, exist_ok=True)

    if args.frames:
        comp = renders[names[0]]
        for f in args.frames.split(","):
            dest = v.out / "frames" / f"{names[0]}-{int(f):04d}.png"
            remotion("still", comp, str(dest), f"--frame={int(f)}")
            print(shown(dest))
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
        print(shown(dest))


if __name__ == "__main__":
    main()
