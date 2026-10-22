"""Tidy up old renders and working files: keep the latest version of each deliverable, recycle the rest.

  .venv/Scripts/python media/tools/clean.py            lists what it would remove, and how much space it frees
  .venv/Scripts/python media/tools/clean.py --yes      moves those files to the Recycle Bin (restorable, never deleted)
  .venv/Scripts/python media/tools/clean.py --retire <video> [--yes]
                                                       a finished video whole: everything of it in the media home

Looks in four places:
- the media home's out/ (D:\\AI\\pa-bailar-media\\out, all generated): each video's older versions
  (`<video>-v2.3-reel.mp4` once `<video>-v2.4-reel.mp4` exists), stills (`frames/`), drafts (`*-draft.mp4`), keyframe
  sheets (`*-sheet.png`), side-by-sides (`*-vs-*.mp4`), the scratch folders tools and checks leave (`review/`,
  `rt/`, `auditions/`, `music/`, the stills bundles `.bundle-<checkout>/`, and any `stills…/` or `music-…/` a session
  wrote with `--out`, `check/` from tools/check.mjs), the mix's intermediate WAVs and rejected soundtracks, and logs.
  Each deliverable's latest version and its `<deliverable>.mp4` link stay. The home's archive/ (posted versions) is
  never touched. In public/<video>/, the temporary flyer folders (`.flyers-<pid>`) a stopped tools/events.py left.
- the media home's cache/tts and cache/music: what no video uses any more, read from every projects/*/video.json of
  this checkout, every other worktree and every local branch (the home is shared: a video on a branch is in use) (a
  voice line or one take that isn't any video's now, like the takes before the one the owner approved; a bed or a
  downloaded track no video's "music"."bed" names, with its .json). What a video uses stays (the owner, 8 Oct 2026:
  "you create several versions of voice or video, and then just leave them there"). While any of those video.json
  files can't be read, nothing in the cache is listed (a warning names each): what it uses is unknown.
- the checkout's media/cache, media/public/<video> and media/out/<video> from before the media home: a file is
  listed only when the home holds an identical copy (a render of a posted version: in the archive). The site checks
  that live in media/out/ (`*.mjs`, `site-bugs/`, `site-quality/`, `admin-tabs/`, and `site-checks/`: the
  screenshots of media/site-checks) are skipped, by name; new checks are scenarios in media/site-checks/.
- the original teaser project's out/ (C:\\Users\\Jhoan\\Code\\pa-bailar-teaser, the first archive): older versions of
  each deliverable (`teaser-v2.2-reel.mp4` once `teaser-v2.3-reel.mp4` exists) that the home's archive/ holds an
  identical copy of, comparisons, drafts, frames, logs. Files that project's git tracks (its voice lines, music
  options, overview sheets) are never touched.

--retire <video> is for a video that's done (posted and past its shelf life, or dropped): its out/, public/ and
archive/ folders in the media home, and the voice takes and music only it uses. Its project folder stays in git (the
code, video.json, data/), so it can be made again. The owner decides when a video is done.

With --yes, an item on a drive without a Recycle Bin, or larger than the bin holds (Windows would delete it for good),
is skipped with a message. One Windows can't move (a file another program holds open) is named with why, never with a
dialog; the rest still go, and the run then exits with an error.

Standard library only (the Recycle Bin through ctypes and the Windows shell): any Python on Windows runs it.
"""

import argparse
import ctypes
import filecmp
import json
import re
import shutil
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

from common import HOME, MEDIA, parse_render_name, version_key, version_tuple, voice_files
from mix import SCRATCH as MIX_SCRATCH  # its intermediates (it removes them after a mix; older runs left them)

ARCHIVE = MEDIA.parent.parent / "pa-bailar-teaser"
SCRATCH_DIRS = {
    "frames",
    "review",
    "rt",
    "auditions",
    "music",
    "draft",
    "inspect",
    "probe",
    "keyframes",
    ".bundle",
    "check",
}
# Site checks kept in the checkout's media/out/ (not video output): never listed. New ones are media/site-checks/.
SITE_CHECKS = {"site-bugs", "site-quality", "admin-tabs", "site-checks"}
VERSIONED = re.compile(r"^(?P<name>.+?)-v(?P<version>\d+(?:\.\d+)*)-(?P<deliverable>[\w-]+)\.mp4$")


def git(*args: str, root: Path | None = None) -> str:
    """A git command in `root` (default: this checkout); "" when git or the command fails (then only this checkout's
    files count)."""
    try:
        run = subprocess.run(
            ["git", "-C", str(MEDIA if root is None else root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return run.stdout


def tracked(root: Path) -> set[Path]:
    """Files a git checkout tracks (never removed)."""
    if not (root / ".git").exists():
        return set()
    return {(root / line).resolve() for line in git("ls-files", root=root).splitlines()}


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def old_versions(folder: Path, name: str | None = None) -> list[Path]:
    """`<name>-v<version>-<deliverable>.mp4` files older than the latest version of their deliverable (version_key():
    v6 = v6.0 < v6.1 < v10, and both spellings of the latest stay). With `name` (a video's out/ folder) the name is
    known, so "teaser-v2-v2.4-reel.mp4" parses right; without it, any name."""
    latest: dict[tuple[str, str], tuple[int, ...]] = {}
    found: list[tuple[tuple[str, str], tuple[int, ...], Path]] = []
    for f in folder.glob("*.mp4"):
        if name is not None:
            parsed = parse_render_name(name, f.name)
            if not parsed:
                continue
            key, version = (name, parsed[1]), version_key(parsed[0])
        else:
            m = VERSIONED.match(f.name)
            if not m:
                continue
            key, version = (m["name"], m["deliverable"]), version_key(version_tuple(m["version"]))
        found.append((key, version, f))
        latest[key] = max(latest.get(key, version), version)
    return [f for key, version, f in found if version < latest[key]]


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
        or name in MIX_SCRATCH
        or name.startswith(("old-", "new-", "psnr", "timing-orig", "rejected-"))
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


def stray_public() -> list[Path]:
    """Temporary flyer folders in public/<video>/ that a stopped tools/events.py left (`.flyers-<pid>`). Never its
    `.flyers-old-<pid>`: if the swap failed half-way, the video's current flyers are in it (events.py puts them
    back)."""
    public = HOME / "public"
    if not public.exists():
        return []
    return sorted(p for p in public.glob("*/.flyers-*") if not p.name.startswith(".flyers-old-"))


def uses(settings: dict[str, Any]) -> set[Path]:
    """The cache files a video uses: its voice lines (or its one take) and its music bed (with the bed's .json)."""
    used: set[Path] = set()
    if voice := settings.get("voice"):
        used |= {path.resolve() for path in voice_files(voice)}
    bed = settings.get("music", {}).get("bed")
    if bed:
        used |= {(HOME / bed).resolve(), (HOME / f"{bed}.json").resolve(), (HOME / bed).with_suffix(".json").resolve()}
    return used


Settings = list[tuple[str, dict[str, Any]]]  # (video, its video.json)


def worktree_settings() -> tuple[Settings, list[str]]:
    """The video.json files of this checkout and every other worktree, and the ones that couldn't be read."""
    found: Settings = []
    unreadable: list[str] = []
    roots = [MEDIA] + [
        Path(line.removeprefix("worktree ")) / "media"
        for line in git("worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    ]
    seen: set[Path] = set()
    for root in roots:
        for path in sorted((root / "projects").glob("*/video.json")):
            if path.resolve() in seen:
                continue
            seen.add(path.resolve())
            try:
                found.append((path.parent.name, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                unreadable.append(str(path))
    return found, unreadable


def branch_settings() -> tuple[Settings, list[str]]:
    """Each local branch's committed video.json files, and the ones that couldn't be read (as `<ref>:<path>`)."""
    found: Settings = []
    unreadable: list[str] = []
    for ref in git("for-each-ref", "--format=%(refname)", "refs/heads").split():
        for name in git("ls-tree", "-r", "--name-only", "--full-name", ref, "--", "projects").splitlines():
            if not name.endswith("/video.json"):
                continue
            try:
                found.append((name.split("/")[-2], json.loads(git("show", f"{ref}:{name}"))))
            except ValueError:
                unreadable.append(f"{ref}:{name}")
    return found, unreadable


def project_settings() -> tuple[Settings, list[str]]:
    """Every video's settings the shared media home serves (this checkout's and every other worktree's files, and each
    local branch's committed ones), and the video.json files that couldn't be read. Only this checkout's, the
    bug-squash pass of 8 Oct 2026 found, listed a branch's new video's takes and bed as unused."""
    here, bad_here = worktree_settings()
    branches, bad_branches = branch_settings()
    return here + branches, bad_here + bad_branches


def in_use(skip: str | None = None) -> set[Path] | None:
    """The cache files some video uses (every video's settings but `skip`'s: project_settings), or None when a
    video.json couldn't be read: that video's takes and bed are unknown, so nothing in the cache is known unused (a
    broken file skipped silently made them "unused", and --yes would have recycled them)."""
    found, unreadable = project_settings()
    for where in unreadable:
        print(f"WARNING: can't read {where}: the voice takes and music in the cache aren't listed", file=sys.stderr)
    if unreadable:
        return None
    used: set[Path] = set()
    for name, settings in found:
        if name != skip:
            used |= uses(settings)
    return used


def retired(name: str) -> list[Path]:
    """A finished video's files in the media home: its out/, public/ and archive/ folders, and the cache files only it
    uses (none while a video.json can't be read: in_use). The project folder (in git) stays."""
    project = MEDIA / "projects" / name / "video.json"
    if not project.exists():
        raise SystemExit(f"no video called {name!r} (no {project})")
    folders = [f for f in (HOME / top / name for top in ("out", "public", "archive")) if f.exists()]
    others = in_use(skip=name)
    if others is None:
        return sorted(folders)
    own = uses(json.loads(project.read_text(encoding="utf-8")))
    return sorted(folders + [f for f in own if f.exists() and f not in others])


def unused_cache() -> list[Path]:
    """Voice takes and music in the home's cache that no video uses (a folder whole when nothing in it is used); none
    while a video.json can't be read (in_use)."""
    used = in_use()
    if used is None:
        return []
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
    picks = home_out(HOME / "out") + stray_public() + legacy() + unused_cache()
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


# The shell's SHFileOperationW (shellapi.h), asked to move to the Recycle Bin without a word: no confirmation, no
# progress, and no error dialog (FOF_NOERRORUI). It answers with a code instead, and the run goes on to the next item.
# Before 22 Oct 2026 it went through PowerShell and Visual Basic's FileSystem with 'OnlyErrorDialogs' (FOF_NOERRORUI
# unset: the shell may stop on an error dialog), and an item it couldn't move (a file another program held open)
# ended the whole run with a traceback, the items after it never tried.
FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040  # to the Recycle Bin, not deleted for good
FOF_NOCONFIRMMKDIR = 0x0200
FOF_NOERRORUI = 0x0400
# FOF_WANTNUKEWARNING stays off: it's a dialog. What the bin can't take, Windows deletes for good without asking, so
# unrecyclable() keeps those out before anything is moved.
RECYCLE_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_NOCONFIRMMKDIR


class SHFileOpStruct(ctypes.Structure):
    """SHFILEOPSTRUCTW (byte-packed in 32-bit Windows, natural in 64-bit)."""

    if ctypes.sizeof(ctypes.c_void_p) == 4:
        _pack_ = 1
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


if sys.platform == "win32":

    def recycle(path: Path) -> str | None:
        """To the Recycle Bin (Windows), so anything can be restored, never stopping on a dialog. Returns why it
        couldn't (a file another program holds open, a missing file…), or None once it's in the bin."""
        op = SHFileOpStruct(
            wFunc=FO_DELETE,
            pFrom=f"{path.resolve()}\0",  # a list of paths, each ended by a NUL, then one more (ctypes adds that one)
            fFlags=RECYCLE_FLAGS,
        )
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if code or op.fAnyOperationsAborted:
            # Below 0x71 the code is a Windows error (0x20: another program holds it open); from there on, the
            # shell's own DE_* codes, which FormatError would misread.
            why = ctypes.FormatError(code).strip() if 0 < code < 0x71 else f"shell code 0x{code:X}"
            return f"Windows couldn't move it ({why})"
        if path.exists():  # a folder's other files went, one didn't (held open): those are in the bin, it isn't
            return "only part of it went to the Recycle Bin; the rest stays where it is"
        return None

else:

    def recycle(path: Path) -> str | None:
        """The Recycle Bin is Windows': elsewhere nothing moves."""
        return "the Recycle Bin is Windows' (nothing moved)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="move them to the Recycle Bin (default: only list)")
    parser.add_argument(
        "--retire", metavar="VIDEO", help="a finished video whole (its media home files), not the tidy-up"
    )
    args = parser.parse_args()
    picks = retired(args.retire) if args.retire else candidates()
    total = 0
    for p in picks:
        n = size(p)
        total += n
        print(f"{n / 1e6:8.1f} MB  {p}")
    print(
        f"{len(picks)} items, {total / 1e6:.0f} MB" + ("" if args.yes else " (nothing removed: --yes to recycle them)")
    )
    if args.yes:
        recycle_all(picks)


def recycle_all(picks: list[Path]) -> None:
    """Each item to the Recycle Bin, past the ones it can't move (named, with why); exits with an error when some
    stayed."""
    moved, stuck = 0, 0
    for p in picks:
        if reason := unrecyclable(p):
            print(f"skipped {p}: {reason}; remove it yourself if you mean to")
            continue
        if problem := recycle(p):
            print(f"couldn't move {p}: {problem}", file=sys.stderr)
            stuck += 1
            continue
        moved += 1
    print(f"{moved} moved to the Recycle Bin")
    if stuck:
        raise SystemExit(f"{stuck} couldn't be moved (above): close what holds them open and run it again")


if __name__ == "__main__":
    main()
