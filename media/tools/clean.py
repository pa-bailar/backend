"""Tidy up old renders and working files: keep the latest version of each deliverable, recycle the rest.

  .venv/Scripts/python media/tools/clean.py            lists what it would remove, and how much space it frees
  .venv/Scripts/python media/tools/clean.py --yes      moves those files to the Recycle Bin (restorable, never deleted)

Looks in three places:
- the media home's out/ (D:\\AI\\pa-bailar-media\\out, all generated): each video's older versions
  (`<video>-v2.3-reel.mp4` once `<video>-v2.4-reel.mp4` exists), stills (`frames/`), drafts (`*-draft.mp4`), keyframe
  sheets (`*-sheet.png`), side-by-sides (`*-vs-*.mp4`), the scratch folders tools and checks leave (`review/`,
  `rt/`, `auditions/`, `music/`, the stills bundle `.bundle/`), and logs. Each deliverable's latest version and its
  `<deliverable>.mp4` link stay. The home's archive/ (posted versions) is never touched.
- the checkout's media/cache, media/public/<video> and media/out/<video> from before the media home: a file is
  listed only when the home holds an identical copy (a render of a posted version: in the archive). The site checks
  that live in media/out/ (`*.mjs`, `site-bugs/`, `site-quality/`, `admin-tabs/`) are skipped, by name; new checks
  belong in a scratch folder, not in media/out/.
- the original teaser project's out/ (C:\\Users\\Jhoan\\Code\\pa-bailar-teaser, the first archive): older versions of
  each deliverable (`teaser-v2.2-reel.mp4` once `teaser-v2.3-reel.mp4` exists), comparisons, drafts, frames, logs.
  Files that project's git tracks (its voice lines, music options, overview sheets) are never touched.

Standard library + PowerShell (the Recycle Bin): any Python on Windows runs it.
"""

import argparse
import filecmp
import os
import re
import subprocess
from pathlib import Path

from common import HOME, MEDIA, parse_render_name

ARCHIVE = MEDIA.parent.parent / "pa-bailar-teaser"
SCRATCH_DIRS = {"frames", "review", "rt", "auditions", "music", "draft", "inspect", "probe", "keyframes", ".bundle"}
# Site checks kept in the checkout's media/out/ (not video output): never listed. New ones go in a scratch folder.
SITE_CHECKS = {"site-bugs", "site-quality", "admin-tabs"}
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
        name.endswith(("-draft.mp4", "-sheet.png", "-review.ok", ".log"))
        or "-vs-" in name
        or name.startswith(("old-", "new-", "psnr", "timing-orig"))
    )


def archive_leftover(path: Path) -> bool:
    """In the teaser archive's out/: a scratch folder, a comparison or a log."""
    if path.is_dir():
        return path.name in SCRATCH_DIRS | {"keyframes-v2", "mix"}
    return path.name.startswith("compare-") or path.suffix == ".log"


def site_check(path: Path) -> bool:
    """A site check left in the checkout's media/out/ (a script or its folder), not a video's output."""
    return path.name in SITE_CHECKS or (path.is_file() and path.suffix in {".mjs", ".json"})


def home_out(out: Path) -> list[Path]:
    picks: list[Path] = []
    for item in out.iterdir() if out.exists() else []:
        if item.is_dir() and item.name in SCRATCH_DIRS:
            picks.append(item)
        elif item.is_file() and item.suffix in {".log", ".png", ".mp4"}:
            picks.append(item)  # loose checks and stills at out/'s top level
        elif item.is_dir() and not site_check(item):  # a video: its latest renders stay; older ones and the rest go
            picks += [sub for sub in item.iterdir() if working_file(sub)]
            picks += old_versions(item, item.name)
    return picks


def home_copies(path: Path) -> list[Path]:
    """Where the media home may hold a copy of a file from the checkout's media/ (same place; a render of a posted
    version: in the archive)."""
    rel = path.relative_to(MEDIA)
    out = [HOME / rel]
    if rel.parts[0] == "out" and len(rel.parts) == 3 and path.suffix == ".mp4":
        video = rel.parts[1]
        out += sorted((HOME / "archive" / video).glob(f"*/{video}-v*-{path.name}"))
    return out


def copied(path: Path) -> bool:
    return any(c.exists() and filecmp.cmp(path, c, shallow=False) for c in home_copies(path))


def legacy() -> list[Path]:
    """The checkout's generated folders from before the media home: what the home holds an identical copy of (a whole
    folder when every file in it is copied)."""
    if HOME.resolve() == MEDIA.resolve():
        return []
    roots = [MEDIA / "cache"]
    roots += [d for top in ("public", "out") if (MEDIA / top).exists() for d in (MEDIA / top).iterdir()]
    picks: list[Path] = []
    for root in roots:
        if not root.exists() or site_check(root) or root.name == "fonts":
            continue
        if root.name in SCRATCH_DIRS:  # e.g. the stills bundle, made again in seconds
            picks.append(root)
            continue
        files = [f for f in root.rglob("*") if f.is_file()] if root.is_dir() else [root]
        done = [f for f in files if copied(f)]
        picks += [root] if root.is_dir() and files and len(done) == len(files) else done
    return picks


def candidates() -> list[Path]:
    picks = home_out(HOME / "out") + legacy()
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
    env = {**os.environ, "TARGET": str(path)}
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
