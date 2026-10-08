"""Tidy up old renders and working files: keep the latest version of each deliverable, recycle the rest.

  .venv/Scripts/python media/tools/clean.py            lists what it would remove, and how much space it frees
  .venv/Scripts/python media/tools/clean.py --yes      moves those files to the Recycle Bin (restorable, never deleted)

Looks in four places:
- the media home's out/ (D:\\AI\\pa-bailar-media\\out, all generated): each video's older versions
  (`<video>-v2.3-reel.mp4` once `<video>-v2.4-reel.mp4` exists), stills (`frames/`), drafts (`*-draft.mp4`), keyframe
  sheets (`*-sheet.png`), side-by-sides (`*-vs-*.mp4`), the scratch folders tools and checks leave (`review/`,
  `rt/`, `auditions/`, `music/`, the stills bundles `.bundle-<checkout>/`, and any `stills…/` or `music-…/` a session
  wrote with `--out`), and logs. Each deliverable's latest version and its `<deliverable>.mp4` link stay. The home's
  archive/ (posted versions) is never touched.
- the media home's cache/tts and cache/music: what no video uses any more, read from every projects/*/video.json (a
  voice line or one take that isn't any video's now, like the takes before the one the owner approved; a bed or a
  downloaded track no video's "music"."bed" names, with its .json). What a video uses stays (the owner, 8 Oct 2026:
  "you create several versions of voice or video, and then just leave them there").
- the checkout's media/cache, media/public/<video> and media/out/<video> from before the media home: a file is
  listed only when the home holds an identical copy (a render of a posted version: in the archive). The site checks
  that live in media/out/ (`*.mjs`, `site-bugs/`, `site-quality/`, `admin-tabs/`, and `site-checks/`: the
  screenshots of media/site-checks) are skipped, by name; new checks are scenarios in media/site-checks/.
- the original teaser project's out/ (C:\\Users\\Jhoan\\Code\\pa-bailar-teaser, the first archive): older versions of
  each deliverable (`teaser-v2.2-reel.mp4` once `teaser-v2.3-reel.mp4` exists) that the home's archive/ holds an
  identical copy of, comparisons, drafts, frames, logs. Files that project's git tracks (its voice lines, music
  options, overview sheets) are never touched.

With --yes, an item on a drive without a Recycle Bin, or larger than the bin holds (Windows would delete it for good),
is skipped with a message.

Standard library + PowerShell (the Recycle Bin): any Python on Windows runs it.
"""

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from common import DIRECTION, HOME, MEDIA, one_take_path, parse_render_name, tts_path

ARCHIVE = MEDIA.parent.parent / "pa-bailar-teaser"
SCRATCH_DIRS = {"frames", "review", "rt", "auditions", "music", "draft", "inspect", "probe", "keyframes", ".bundle"}
# Site checks kept in the checkout's media/out/ (not video output): never listed. New ones are media/site-checks/.
SITE_CHECKS = {"site-bugs", "site-quality", "admin-tabs", "site-checks"}
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
        return name in SCRATCH_DIRS or name.startswith(("audio-orig", "stills", "music-"))
    return (
        name.endswith(("-draft.mp4", "-sheet.png", "-review.ok", ".log"))
        or "-vs-" in name
        # render.py keeps the <deliverable>.mp4 a re-render of the same version orphaned: an earlier cut, stale
        or "-unversioned-" in name
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
        if item.is_dir() and (item.name in SCRATCH_DIRS or item.name.startswith(".bundle")):  # .bundle-<checkout>
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


def in_home_archive(path: Path) -> bool:
    """Whether the media home's archive/ holds an identical copy of a file (same size, same bytes)."""
    size = path.stat().st_size
    return any(
        c.stat().st_size == size and filecmp.cmp(path, c, shallow=False)
        for c in (HOME / "archive").rglob(f"*{path.suffix}")
    )


def in_use() -> set[Path]:
    """The cache files some video uses: its voice lines (or its one take) and its music bed (with the bed's .json)."""
    used: set[Path] = set()
    for path in (MEDIA / "projects").glob("*/video.json"):
        settings = json.loads(path.read_text(encoding="utf-8"))
        voice = settings.get("voice")
        if voice:
            direction = voice.get("direction", DIRECTION)
            if voice.get("one_take"):
                used.add(one_take_path(voice).resolve())
            for line in voice["lines"]:
                used.add(tts_path(line["text"], voice["name"], direction, line.get("take", 0)).resolve())
        bed = settings.get("music", {}).get("bed")
        if bed:
            used |= {
                (HOME / bed).resolve(),
                (HOME / f"{bed}.json").resolve(),
                (HOME / bed).with_suffix(".json").resolve(),
            }
    return used


def unused_cache() -> list[Path]:
    """Voice takes and music in the home's cache that no video uses (a folder whole when nothing in it is used)."""
    used = in_use()
    picks: list[Path] = []
    for top in ("tts", "music"):
        root = HOME / "cache" / top
        if not root.exists():
            continue
        for item in root.iterdir():
            files = [f for f in item.rglob("*") if f.is_file()] if item.is_dir() else [item]
            unused = [f for f in files if f.resolve() not in used]
            picks += [item] if item.is_dir() and files and len(unused) == len(files) else unused
    return picks


def candidates() -> list[Path]:
    picks = home_out(HOME / "out") + legacy() + unused_cache()
    archive_out = ARCHIVE / "out"
    if archive_out.exists():
        keep = tracked(ARCHIVE)
        # The teaser project's older versions go only when the home's archive keeps a copy (as legacy() does).
        loose = [p for p in old_versions(archive_out) if in_home_archive(p)]
        loose += [item for item in archive_out.iterdir() if archive_leftover(item)]
        for item in loose:
            if item.is_dir():
                # A folder is recycled whole only when git tracks nothing in it.
                if not any(p.is_relative_to(item.resolve()) for p in keep):
                    picks.append(item)
            elif item.resolve() not in keep:
                picks.append(item)
    return sorted(set(picks))


BIN_SHARE = 0.05  # the Recycle Bin's size on a drive: Windows' default is about 5% (it deletes for good past it)


def unrecyclable(path: Path) -> str | None:
    """Why `path` can't go to the Recycle Bin safely (Windows deletes it for good instead), or None: a drive with no
    bin ($Recycle.Bin: network shares, some removable drives) or an item larger than the bin may hold."""
    drive = Path(path.resolve().anchor)
    if not (drive / "$Recycle.Bin").exists():
        return f"{drive} has no Recycle Bin (it would be deleted for good)"
    limit = shutil.disk_usage(drive).total * BIN_SHARE
    if size(path) > limit:
        return f"{size(path) / 1e9:.1f} GB is more than {drive}'s Recycle Bin holds (~{limit / 1e9:.0f} GB)"
    return None


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
        moved = 0
        for p in picks:
            if reason := unrecyclable(p):
                print(f"skipped {p}: {reason}; remove it yourself if you mean to")
                continue
            recycle(p)
            moved += 1
        print(f"{moved} moved to the Recycle Bin")


if __name__ == "__main__":
    main()
