"""Shared by the tools: where things live, a video's settings (projects/<video>/video.json), WAV and ffmpeg helpers.

Standard library only, so every tool can import it whichever Python runs it (the backend's .venv, the Whisper
venv, the ACE-Step venv).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent
BACKEND = MEDIA.parent
CACHE = MEDIA / "cache"
WINGET_FFMPEG = Path(
    r"C:\Users\Jhoan\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-9.0.2-full_build\bin"
)
TTS_RATE = 24000  # Gemini TTS: 24 kHz 16-bit mono PCM

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def tool(name: str) -> str:
    """ffmpeg or ffprobe: on PATH, else the winget install (D:\\AI\\README.md)."""
    found = shutil.which(name)
    if found:
        return found
    exe = WINGET_FFMPEG / f"{name}.exe"
    if exe.exists():
        return str(exe)
    raise SystemExit(f"{name} not found: install ffmpeg (winget install Gyan.FFmpeg)")


def ffmpeg(*args: str) -> str:
    """Run ffmpeg quietly; returns its stderr (where filters like loudnorm and ebur128 report)."""
    done = subprocess.run([tool("ffmpeg"), "-hide_banner", "-y", *args], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"ffmpeg failed:\n{done.stderr[-2000:]}")
    return done.stderr


def probe(path: Path) -> dict:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
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
        return MEDIA / "public" / self.name

    @property
    def out(self) -> Path:
        """Working files and renders: not committed."""
        return MEDIA / "out" / self.name

    @property
    def fps(self) -> int:
        return int(self.settings.get("fps", 30))

    @property
    def duration(self) -> float:
        return float(self.settings["duration"])


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
