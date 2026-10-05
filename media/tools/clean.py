"""Tidy up old renders and working files: keep the latest version of each deliverable, recycle the rest.

  .venv/Scripts/python media/tools/clean.py            lists what it would remove, and how much space it frees
  .venv/Scripts/python media/tools/clean.py --yes      moves those files to the Recycle Bin (restorable, never deleted)

Looks in two places:
- media/out/ (all generated, never committed): each video's stills (`frames/`), drafts (`*-draft.mp4`), keyframe
  sheets (`*-sheet.png`), side-by-sides (`*-vs-*.mp4`), the scratch folders tools and checks leave (`review/`,
  `rt/`, `auditions/`, `music/`), and logs. Each video's latest full renders (`<deliverable>.mp4`) stay.
- the original teaser project's out/ (C:\\Users\\Jhoan\\Code\\pa-bailar-teaser, the archive): older versions of each
  deliverable (`teaser-v2.2-reel.mp4` once `teaser-v2.3-reel.mp4` exists), comparisons, drafts, frames, logs. Files
  that project's git tracks (its voice lines, music options, overview sheets) are never touched.

Standard library + PowerShell (the Recycle Bin): any Python on Windows runs it.
"""

import argparse
import re
import subprocess
from pathlib import Path

from common import MEDIA, parse_render_name

ARCHIVE = MEDIA.parent.parent / "pa-bailar-teaser"
SCRATCH_DIRS = {"frames", "review", "rt", "auditions", "music", "draft", "inspect", "probe", "keyframes"}
VERSIONED = re.compile(r"^(?P<name>.+?)-v(?P<version>\d+(?:\.\d+)*)-(?P<deliverable>[\w-]+)\.mp4$")


def tracked(root: Path) -> set[Path]:
    """Files a git checkout tracks (never removed)."""
    if not (root / ".git").exists():
        return set()
    out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, encoding="utf-8").stdout
    return {(root / line).resolve() for line in out.splitlines()}


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def old_versions(folder: Path, name: str | None = None) -> list[Path]:
    """`<name>-v<version>-<deliverable>.mp4` files that aren't the latest version of their deliverable. With `name` (a
    video's out/ folder) the name is known, so "teaser-v2-v2.4-reel.mp4" parses right; without it, any name."""
    latest: dict[tuple[str, str], tuple[tuple[int, ...], Path]] = {}
    found: list[tuple[tuple[str, str], tuple[int, ...], Path]] = []
    for f in folder.glob("*.mp4"):
        if name is not None:
            parsed = parse_render_name(name, f.name)
            if not parsed:
                continue
            key, version = (name, parsed[1]), parsed[0]
        else:
            m = VERSIONED.match(f.name)
            if not m:
                continue
            key = (m["name"], m["deliverable"])
            version = tuple(int(p) for p in m["version"].split("."))
        found.append((key, version, f))
        if key not in latest or version > latest[key][0]:
            latest[key] = (version, f)
    return [f for key, version, f in found if latest[key][1] != f]


def working_file(path: Path) -> bool:
    """In a video's out/ folder: a scratch folder, a draft, a sheet, a comparison, a check's leftover."""
    name = path.name
    if path.is_dir():
        return name in SCRATCH_DIRS or name.startswith("audio-orig")
    return (
        name.endswith(("-draft.mp4", "-sheet.png", ".log"))
        or "-vs-" in name
        or name.startswith(("old-", "new-", "psnr", "timing-orig"))
    )


def archive_leftover(path: Path) -> bool:
    """In the teaser archive's out/: a scratch folder, a comparison or a log."""
    if path.is_dir():
        return path.name in SCRATCH_DIRS | {"keyframes-v2", "mix"}
    return path.name.startswith("compare-") or path.suffix == ".log"


def candidates() -> list[Path]:
    out = MEDIA / "out"
    picks: list[Path] = []
    if out.exists():
        for item in out.iterdir():
            if item.is_dir() and item.name in SCRATCH_DIRS:
                picks.append(item)
            elif item.is_file() and item.suffix in {".log", ".png", ".mp4"}:
                picks.append(item)  # loose checks and stills at out/'s top level
            elif item.is_dir():  # a video's folder: its latest renders stay; older versions and the rest go
                picks += [sub for sub in item.iterdir() if working_file(sub)]
                picks += old_versions(item, item.name)
    archive_out = ARCHIVE / "out"
    if archive_out.exists():
        keep = tracked(ARCHIVE)
        loose = [*old_versions(archive_out)]
        loose += [item for item in archive_out.iterdir() if archive_leftover(item)]
        for item in loose:
            if item.is_dir():
                # A folder is recycled whole only when git tracks nothing in it.
                if not any(p.is_relative_to(item.resolve()) for p in keep):
                    picks.append(item)
            elif item.resolve() not in keep:
                picks.append(item)
    return sorted(set(picks))


def recycle(path: Path) -> None:
    """To the Recycle Bin (Windows), so anything can be restored."""
    kind = "DeleteDirectory" if path.is_dir() else "DeleteFile"
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"[Microsoft.VisualBasic.FileIO.FileSystem]::{kind}($env:TARGET, 'OnlyErrorDialogs', 'SendToRecycleBin')"
    )
    env = {**__import__("os").environ, "TARGET": str(path)}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="move them to the Recycle Bin (default: only list)")
    args = parser.parse_args()
    picks = candidates()
    total = 0
    for p in picks:
        n = size(p)
        total += n
        print(f"{n / 1e6:8.1f} MB  {p}")
    print(
        f"{len(picks)} items, {total / 1e6:.0f} MB" + ("" if args.yes else " (nothing removed: --yes to recycle them)")
    )
    if args.yes:
        for p in picks:
            recycle(p)
        print("moved to the Recycle Bin")


if __name__ == "__main__":
    main()
