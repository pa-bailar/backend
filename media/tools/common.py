"""Shared by the tools: where things live, a video's settings (projects/<video>/video.json), WAV and ffmpeg helpers.

Standard library only, so every tool can import it whichever Python runs it (the backend's .venv, the Whisper
venv, the ACE-Step venv).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import wave
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent
BACKEND = MEDIA.parent
# The canvas, safe zones, sticker band, default tempo and loudness targets, shared with src/lib/tokens.ts.
BRAND: dict = json.loads((MEDIA / "brand.json").read_text(encoding="utf-8"))
# The media home: everything generated (the TTS and music cache, each video's public/ binaries, renders and working
# files, the archive of posted versions) lives outside any checkout, so every worktree shares it and removing a
# worktree can't delete it. PA_BAILAR_MEDIA_HOME overrides it (tools/paths.mjs and remotion.config.ts read the same).
DEFAULT_HOME = r"D:\AI\pa-bailar-media"


def media_home(raw: str | None) -> Path:
    """PA_BAILAR_MEDIA_HOME as a path: a relative one is relative to the backend's root, whatever the working folder
    (tools/paths.mjs mediaHome() and remotion.config.ts resolve it the same way)."""
    return (BACKEND / raw).resolve() if raw else Path(DEFAULT_HOME)


HOME = media_home(os.environ.get("PA_BAILAR_MEDIA_HOME"))
CACHE = HOME / "cache"
# The site's three faces (OFL), committed; src/lib/fonts.ts imports them.
FONTS = MEDIA / "fonts"
# winget's Gyan.FFmpeg package (D:\AI\README.md), any version: <package>\ffmpeg-<version>-full_build\bin
WINGET_PACKAGES = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
TTS_RATE = 24000  # Gemini TTS: 24 kHz 16-bit mono PCM

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def tool(name: str) -> str:
    """ffmpeg or ffprobe: on PATH, else the winget install (D:\\AI\\README.md)."""
    found = shutil.which(name)
    if found:
        return found
    for exe in sorted(WINGET_PACKAGES.glob(f"Gyan.FFmpeg_*/ffmpeg-*-full_build/bin/{name}.exe"), reverse=True):
        return str(exe)
    raise SystemExit(f"{name} not found: install ffmpeg (winget install Gyan.FFmpeg)")


def ffmpeg(*args: str, cwd: Path | None = None) -> str:
    """Run ffmpeg quietly (in `cwd` if given); returns its stderr (where filters like loudnorm and ebur128 report)."""
    done = subprocess.run(
        [tool("ffmpeg"), "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    if done.returncode:
        raise SystemExit(f"ffmpeg failed:\n{done.stderr[-2000:]}")
    return done.stderr


def probe(path: Path) -> dict:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    return json.loads(out)


def main_checkout() -> Path:
    """The repository's main checkout. In a git worktree (which has no .venv or .env of its own) it's the folder of the
    shared .git (`git rev-parse --git-common-dir`); elsewhere, or without git, the backend itself."""
    try:
        done = subprocess.run(
            ["git", "-C", str(BACKEND), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return BACKEND
    common_dir = Path(done.stdout.strip())
    return common_dir.parent if common_dir.name == ".git" else BACKEND


def backend_path(*parts: str) -> Path:
    """A path in the backend (`.env`, `.venv/…`): this checkout's when it exists, else the main checkout's (a git
    worktree shares them with it); when neither exists, this checkout's."""
    here = BACKEND.joinpath(*parts)
    if here.exists():
        return here
    main = main_checkout().joinpath(*parts)
    return main if main.exists() else here


def load_env() -> None:
    """The backend's .env (MEDIA_GEMINI_API_KEY lives there; a worktree uses the main checkout's), without printing
    anything from it. Variables already in the environment win."""
    env = backend_path(".env")
    if not env.exists():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def bogota_today() -> date:
    """Today in Bogotá (UTC−5, no daylight saving): the day the site and its visitors are on."""
    return datetime.now(timezone(timedelta(hours=-5))).date()


def key(*parts: object) -> str:
    """A short, stable cache key for the given inputs."""
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]


@dataclass
class Video:
    """One video: its folder, its settings and where the tools write for it."""

    name: str
    settings: dict

    @property
    def folder(self) -> Path:
        return MEDIA / "projects" / self.name

    @property
    def data(self) -> Path:
        """Small files the composition imports (timing.json, app.json, events.json): committed."""
        return self.folder / "data"

    @property
    def public(self) -> Path:
        """Binaries the composition loads with staticFile (screens, flyers, audio): not committed."""
        return HOME / "public" / self.name

    @property
    def out(self) -> Path:
        """Working files and renders: not committed."""
        return HOME / "out" / self.name

    @property
    def fps(self) -> int:
        return int(self.settings.get("fps", BRAND["canvas"]["fps"]))

    @property
    def duration(self) -> float:
        return float(self.settings["duration"])

    @property
    def version(self) -> str:
        """video.json's "version" ("2.4"): part of every render's name. Bump it for each cut the owner sees."""
        text = str(self.settings.get("version", ""))
        if not re.fullmatch(r"\d+(\.\d+)*", text):
            raise SystemExit(f'video.json of {self.name} needs a "version" like "1" or "2.4" (got {text!r})')
        return text

    @property
    def archive(self) -> Path:
        """Posted versions, kept whole: archive/<video>/v<version>/ (renders, and public/ as it was)."""
        return HOME / "archive" / self.name

    def render(self, deliverable: str, draft: bool = False) -> Path:
        """out/<video>/<video>-v<version>-<deliverable>[-draft].mp4"""
        return self.out / render_name(self.name, self.version, deliverable, draft)

    def versions(self, deliverable: str) -> list[tuple[tuple[int, ...], Path]]:
        """Every full render of a deliverable (out/ and the archive), oldest version first."""
        found: dict[tuple[int, ...], Path] = {}
        for folder in (self.archive, self.out):
            for path in sorted(folder.rglob("*.mp4")) if folder.exists() else []:
                parsed = parse_render_name(self.name, path.name)
                if parsed and parsed[1] == deliverable:
                    found.setdefault(parsed[0], path)
        return sorted(found.items())


def mix_key(v: "Video") -> str:
    """A key of what the soundtracks are made from in video.json (the bed, its first hit, "mix", the length):
    tools/mix.py writes it next to them, tools/make.py re-mixes when it changes."""
    music = v.settings.get("music", {})
    return key(music.get("bed"), music.get("first_hit", 0), v.settings.get("mix", {}), v.duration)


# What video.json's "music"."provenance"[<bed>] records for every published bed (ACE-Step's rights to generated
# output are an open question upstream, so each bed keeps how it was made): the model and its revision, the prompt,
# the seed, the reference audio (null for none) and the day it was generated.
PROVENANCE_FIELDS = ("model", "revision", "prompt", "seed", "reference_audio", "generated")


def provenance_problems(music: dict) -> list[str]:
    """What's missing from the provenance of the bed a video uses (video.json's "music"); [] without a bed."""
    bed = music.get("bed")
    if not bed:
        return []
    entry = music.get("provenance", {}).get(bed)
    if entry is None:
        return [
            f'no "music"."provenance" for {bed} in video.json (model, revision, prompt, seed, reference audio, date)'
        ]
    out = [f"{bed}: provenance has no {field!r}" for field in PROVENANCE_FIELDS if field not in entry]
    if "generated" in entry and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry["generated"])):
        out.append(f'{bed}: provenance "generated" should be a date like 2026-10-04 (got {entry["generated"]!r})')
    return out


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split("."))


def render_name(name: str, version: str, deliverable: str, draft: bool = False) -> str:
    return f"{name}-v{version}-{deliverable}{'-draft' if draft else ''}.mp4"


def parse_render_name(name: str, filename: str) -> tuple[tuple[int, ...], str] | None:
    """(version, deliverable) of a full render named by render_name() for video `name`; None for anything else
    (drafts included)."""
    m = re.fullmatch(rf"{re.escape(name)}-v(\d+(?:\.\d+)*)-([\w-]+)\.mp4", filename)
    if not m or m.group(2).endswith("-draft"):
        return None
    return version_tuple(m.group(1)), m.group(2)


def shown(path: Path) -> str:
    """A path to print: relative to the media home or to media/ when it's inside one, else whole."""
    for root in (HOME, MEDIA):
        if path.resolve().is_relative_to(root.resolve()):
            return path.resolve().relative_to(root.resolve()).as_posix()
    return path.as_posix()


def video(name: str) -> Video:
    path = MEDIA / "projects" / name / "video.json"
    if not path.exists():
        raise SystemExit(f"no {path.relative_to(MEDIA)}: is '{name}' a folder in media/projects/?")
    return Video(name, json.loads(path.read_text(encoding="utf-8")))


def write_wav(path: Path, pcm: bytes, rate: int = TTS_RATE) -> None:
    """16-bit mono PCM to a WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)


def tts_path(text: str, voice: str, direction: str, take: int = 0) -> Path:
    """Where one TTS line is cached: the same words, voice, direction and take never call Gemini twice."""
    return CACHE / "tts" / f"{key(text, voice, direction, take)}.wav"


# The owner's chosen reading direction (a video's "voice"."direction" overrides it). Part of every line's cache key:
# changing it re-records every line.
DIRECTION = (
    "Lee este texto en español con acento colombiano de Bogotá (rolo), natural y cercano, como un audio de "
    "WhatsApp a un amigo: relajado, con una sonrisa, sin sonar a locutor ni a comercial. Haz pausas cortas "
    "donde hay puntos suspensivos."
)


def voice_key(settings: dict) -> str | None:
    """A key of everything the voice track and its timing are made of: each line's words, take and gap, the voice,
    the direction, the lead and the pauses, and the bytes of each cached line. tools/timing.py stores it in
    timing.json; tools/render.py refuses to render when it no longer matches (timing older than the voice)."""
    voice = settings.get("voice")
    if not voice:
        return None
    direction = voice.get("direction", DIRECTION)
    parts: list[object] = [voice["name"], direction, voice.get("lead", 0.55), voice.get("max_pause", 0.32)]
    for line in voice["lines"]:
        path = tts_path(line["text"], voice["name"], direction, line.get("take", 0))
        audio = hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "missing"
        parts.append([line["text"], line.get("take", 0), line.get("gap", 0.3), audio])
    return key(*parts)


def _norm(word: str) -> str:
    """A word as the Node side compares it (src/lib/words.ts plain()): no accents (any combining mark), no punctuation,
    lower case. tests/timing-cases.json holds the cases both pass."""
    plain = "".join(
        c for c in unicodedata.normalize("NFD", word.lower()) if not unicodedata.category(c).startswith("M")
    )
    return re.sub(r"[^a-z']", "", plain)


def at_seconds(spec: str, timing: dict | None, fps: int = 30) -> float:
    """A moment as tools/stills.mjs takes it (src/lib/words.ts secondsAt(), the same cases in tests/timing-cases.json):
    seconds ("8.5" or "8.5s"), a frame ("f255"), a line's start ("c4") or a word's start ("c4:link", the nth with
    "c4:link:1"), from a video's data/timing.json."""
    spec = spec.strip()
    if re.fullmatch(r"f\d+", spec):
        return int(spec[1:]) / fps
    if re.fullmatch(r"\d+(\.\d+)?s?", spec):
        return float(spec.removesuffix("s"))
    line_id, _, rest = spec.partition(":")
    line = next((x for x in (timing or {}).get("lines", []) if x["id"] == line_id), None)
    if line is None:
        raise SystemExit(f'no line "{line_id}" in timing.json (times are seconds, f<frame>, <line> or <line>:<word>)')
    if not rest:
        return float(line["start"])
    word, _, nth = rest.partition(":")
    hits = [w for w in line["words"] if _norm(w["word"]) == _norm(word)]
    if len(hits) <= int(nth or 0):
        raise SystemExit(f'no word "{word}" (#{nth or 0}) in {line_id}')
    return float(hits[int(nth or 0)]["start"])
