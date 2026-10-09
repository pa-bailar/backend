"""One runner for a video: runs only the stages whose inputs changed, each with the Python it needs.

  .venv/Scripts/python media/tools/make.py <video> [stage ...] [--draft] [--force] [--dry-run] [--strict]
      Stages, in order: tts → timing → mix → render → sheet (default: all that apply to the video). A stage runs
      when its outputs are missing or older than its inputs:
        tts     a voice line or the one take isn't cached (only those call Gemini)     .venv
        timing  timing.json was made from other lines (its voice_key), or no track    whisper venv
        mix     a soundtrack is older than the voice track or the bed, or video.json's .venv
                music/mix settings changed (the mix.key mix.py leaves next to them)
        render  a render is older than the code, the data, the public files or brand   .venv (+ node)
        sheet   the review (Instagram pre-flight, keyframe sheet, sticker band, Reel   .venv
                safe zones, side-by-side with the previous version) hasn't passed since the render
                (render.py leaves <render>-review.ok only when it passes)
      Once a stage runs, every later one runs too (a new voice line means new timing, a new mix, a new render and
      its review).
      --draft renders half size without motion blur; --force runs the named stages anyway; --dry-run only says
      what would run; --strict makes mix and render refuse a bed without provenance, and render refuse material
      past its shelf life.
  .venv/Scripts/python media/tools/make.py doctor
      Checks the machine: ffmpeg, Chrome, node and the packages, the three Pythons, the fonts, the Gemini key (set or
      not, never shown), each video's music bed, and the media home.

Music (tools/music.py, ACE-Step on the GPU) and material (capture.mjs, events.py) stay manual: they cost time or
change what the video shows, so they run on purpose.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from common import (
    BACKEND,
    CACHE,
    FONTS,
    HOME,
    MEDIA,
    Video,
    backend_path,
    load_env,
    mix_key,
    shown,
    video,
    voice_files,
    voice_key,
)
from render import passed_marker


def venv_python() -> Path:
    """The backend's .venv Python: this checkout's, else the main checkout's (a git worktree has none), else the
    Python running make.py (started from the .venv, as the docs say)."""
    exe = backend_path(".venv", "Scripts", "python.exe")
    return exe if exe.exists() else Path(sys.executable)


PYTHON = {
    "venv": venv_python(),
    "whisper": Path(os.environ.get("PA_BAILAR_WHISPER_PYTHON", r"D:\AI\whisper\.venv\Scripts\python.exe")),
    "ace": Path(os.environ.get("PA_BAILAR_ACE_PYTHON", r"D:\AI\ace-step\.venv\Scripts\python.exe")),
}
STAGES = ("tts", "timing", "mix", "render", "sheet")
TOOLS = MEDIA / "tools"


def stale(outputs: list[Path], inputs: list[Path]) -> bool:
    """True when an output is missing or any existing input is newer than the oldest output."""
    if not outputs or any(not o.exists() for o in outputs):
        return True
    oldest = min(o.stat().st_mtime for o in outputs)
    return any(i.exists() and i.stat().st_mtime > oldest for i in inputs)


def files(*folders: Path) -> list[Path]:
    return [f for d in folders if d.exists() for f in d.rglob("*") if f.is_file() and "node_modules" not in f.parts]


def soundtracks(v: Video) -> list[Path]:
    if not v.settings.get("voice") and not (v.out / "voice-track.wav").exists():
        return [v.public / "audio" / "music-only.wav"] if v.settings.get("music", {}).get("bed") else []
    out = [v.public / "audio" / "voice-only.wav"]
    if v.settings.get("music", {}).get("bed"):
        out.append(v.public / "audio" / "with-music.wav")
    return out


def render_inputs(v: Video) -> list[Path]:
    return files(MEDIA / "src", MEDIA / "fonts", v.folder, v.public) + [
        MEDIA / "brand.json",
        MEDIA / "package-lock.json",
    ]


def timing_reason(v: Video) -> str | None:
    timing = v.data / "timing.json"
    if not timing.exists() or not (v.out / "voice-track.wav").exists():
        return "no timing.json or voice track"
    stored = json.loads(timing.read_text(encoding="utf-8")).get("voice_key")
    return None if stored == voice_key(v.settings) else "the voice changed since timing.json"


def mix_reason(v: Video, tracks: list[Path]) -> str | None:
    bed = v.settings.get("music", {}).get("bed")
    if stale(tracks, [v.out / "voice-track.wav"] + ([HOME / bed] if bed else [])):
        return "a soundtrack is missing or older than the voice track or the bed"
    made = v.public / "audio" / "mix.key"
    if not made.exists() or made.read_text().strip() != mix_key(v):
        return "video.json's music or mix settings changed (mix.key)"
    return None


def plan(v: Video, draft: bool) -> dict[str, str | None]:
    """Each stage → why it should run (None: up to date; absent: doesn't apply to this video)."""
    out: dict[str, str | None] = {}
    if v.settings.get("voice"):
        missing = [p for p in voice_files(v.settings["voice"]) if not p.exists()]
        out["tts"] = f"{len(missing)} line(s) not cached" if missing else None
        out["timing"] = timing_reason(v)
    tracks = soundtracks(v)
    if tracks:
        out["mix"] = mix_reason(v, tracks)
    renders = [v.render(d, draft) for d in v.settings["renders"]]
    out["render"] = "a render is missing or older than its inputs" if stale(renders, render_inputs(v)) else None
    # A review is done when it passed (render.review leaves the marker only then), not when it drew a sheet.
    passed = [passed_marker(r) for r in renders]
    out["sheet"] = "a passing review is missing or older than its render" if stale(passed, renders) else None
    return out


def run(python: str, *args: str) -> None:
    exe = PYTHON[python]
    if not exe.exists():
        raise SystemExit(f"no {exe}: run make.py doctor")
    print(f"→ [{python}] {' '.join(Path(a).name if a.endswith('.py') else a for a in args)}", flush=True)
    done = subprocess.run([str(exe), *args], cwd=BACKEND)
    if done.returncode:
        raise SystemExit(f"stage failed: {' '.join(args)}")


def schedule(todo: dict[str, str | None], wanted: list[str], force: bool) -> list[tuple[str, str | None]]:
    """(stage, why it runs or None when it's up to date), in order. Once a stage runs, every later one runs too: its
    output is a later stage's input (tts → timing → mix → render → sheet), so a plan made before it ran is stale."""
    out: list[tuple[str, str | None]] = []
    upstream: str | None = None
    for stage in STAGES:
        if stage not in todo or (wanted and stage not in wanted):
            continue
        reason = todo[stage] or ("forced" if force else None) or (f"{upstream} ran before it" if upstream else None)
        if reason:
            upstream = stage
        out.append((stage, reason))
    return out


def make(name: str, wanted: list[str], draft: bool, force: bool, dry: bool, strict: bool) -> None:
    v = video(name)
    todo = plan(v, draft)
    unknown = [s for s in wanted if s not in STAGES]
    if unknown:
        raise SystemExit(f"unknown stage(s) {unknown}: {', '.join(STAGES)}")
    tool = lambda t: str(TOOLS / t)  # noqa: E731
    commands: dict[str, Callable[[], None]] = {
        "tts": lambda: run("venv", tool("tts.py"), name),
        "timing": lambda: run("whisper", tool("timing.py"), name),
        "mix": lambda: run("venv", tool("mix.py"), name, *(["--strict"] if strict else [])),
        "render": lambda: run(
            "venv", tool("render.py"), name, *(["--draft"] if draft else []), *(["--strict"] if strict else [])
        ),
        "sheet": lambda: review_all(v, draft),
    }
    for stage, reason in schedule(todo, wanted, force):
        if reason is None:
            print(f"  {stage}: up to date")
            continue
        print(f"  {stage}: {reason}{' (dry run)' if dry else ''}", flush=True)
        if not dry:
            commands[stage]()


def review_all(v: Video, draft: bool) -> None:
    import render

    ok = True
    for deliverable in v.settings["renders"]:
        dest = v.render(deliverable, draft)
        if not dest.exists():
            raise SystemExit(f"no {shown(dest)}: run the render stage")
        ok = render.review(v, deliverable, dest) and ok
    if not ok:
        raise SystemExit("review: something entered the sticker band, or Instagram would refuse the file (above)")


# ---------- doctor ----------


def check_python(label: str, python: str, module: str | None) -> tuple[bool, str]:
    exe = PYTHON[python]
    if not exe.exists():
        return False, f"{label}: no {exe}"
    if module:
        done = subprocess.run([str(exe), "-c", f"import {module}"], capture_output=True)
        if done.returncode:
            return False, f"{label}: {exe} can't import {module}"
    return True, f"{label}: {exe}"


def chrome() -> Path | None:
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base and (exe := Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe").exists():
            return exe
    return None


def checks() -> list[tuple[str, bool, str]]:
    """(level, ok, message): level "need" fails the doctor, "nice" only warns."""
    from common import tool

    out: list[tuple[str, bool, str]] = []
    for exe in ("ffmpeg", "ffprobe"):
        try:
            out.append(("need", True, f"{exe}: {tool(exe)}"))
        except SystemExit as error:
            out.append(("need", False, str(error)))
    if all(ok for _, ok, _ in out):
        import review

        vmaf = review.has_filter("libvmaf")
        out.append(("nice", vmaf, f"ffmpeg's libvmaf (review.py diff): {'yes' if vmaf else 'no: PSNR and SSIM only'}"))
    found = chrome()
    out.append(("need", bool(found), f"Chrome (captures): {found or 'not found'}"))
    out.append(("need", bool(shutil.which("node")), f"node: {shutil.which('node') or 'not on PATH'}"))
    modules = MEDIA / "node_modules"
    installed = (modules / "remotion").exists()
    out.append(("need", installed, f"node_modules: {'installed' if installed else 'missing: cd media && npm ci'}"))
    shell = (modules / ".remotion" / "chrome-headless-shell").exists()
    out.append(("nice", shell, f"Remotion's browser: {'downloaded' if shell else 'downloads on the first render'}"))
    out.append(("need", *check_python(".venv (tts, mix, events, render, review)", "venv", "google.genai")))
    out.append(("nice", *check_python("whisper venv (timing, analyze)", "whisper", "faster_whisper")))
    out.append(("nice", *check_python("ACE-Step venv (music)", "ace", None)))
    fonts = sorted(p.name for p in FONTS.glob("*.ttf"))
    out.append(("need", len(fonts) >= 3, f"fonts: {', '.join(fonts) or f'missing ({FONTS})'}"))
    load_env()
    has_key = bool(os.environ.get("MEDIA_GEMINI_API_KEY"))
    key_state = "set" if has_key else "not set (only new TTS lines need it)"
    out.append(("nice", has_key, f"MEDIA_GEMINI_API_KEY: {key_state}"))
    for folder in sorted((MEDIA / "projects").iterdir()):
        if not (folder / "video.json").exists():
            continue
        bed = video(folder.name).settings.get("music", {}).get("bed")
        if bed:
            out.append(("need", (HOME / bed).exists(), f"{folder.name} music bed: {HOME / bed}"))
    writable = HOME.exists() and os.access(HOME, os.W_OK)
    free = shutil.disk_usage(HOME).free / 1e9 if HOME.exists() else 0
    state = "writable" if writable else "missing or read-only"
    out.append(("need", writable, f"media home: {HOME} ({state}, {free:.0f} GB free)"))
    lines = len(list((CACHE / "tts").glob("*.wav")))
    out.append(("nice", lines > 0, f"TTS cache: {lines} lines in {CACHE / 'tts'}"))
    return out


def doctor() -> None:
    failed = 0
    for level, ok, message in checks():
        mark = "ok  " if ok else ("FAIL" if level == "need" else "warn")
        failed += not ok and level == "need"
        print(f"{mark} {message}")
    if failed:
        raise SystemExit(f"{failed} problem(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("stages", nargs="*")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.video == "doctor":
        doctor()
        return
    make(args.video, args.stages, args.draft, args.force, args.dry_run, args.strict)


if __name__ == "__main__":
    main()
