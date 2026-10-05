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
HOME = Path(os.environ.get("PA_BAILAR_MEDIA_HOME") or r"D:\AI\pa-bailar-media")
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


def load_env() -> None:
    """The backend's .env (MEDIA_GEMINI_API_KEY lives there), without printing anything from it."""
    env = BACKEND / ".env"
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
