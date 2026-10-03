"""Videos' preview clips: a few silent seconds that play on the site, so a video looks like a video.

When an event's image is a video's frame (a reel, or a carousel's video slide), `make_clip` downloads the video
and cuts its first config.CLIP_SECONDS seconds with ffmpeg: no sound, config.CLIP_WIDTH pixels wide, H.264 MP4
(it plays in every browser), usually 100–400 KB. Saved as data/previews/<post id>-<slide>.mp4, next to the
flyer of the same slide. Anything that goes wrong (no ffmpeg, no video file from Instagram, a download or
ffmpeg error) means no clip: the site then shows the still image, as before.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)


def ffmpeg() -> str | None:
    """The ffmpeg program (config.FFMPEG: a path, or a name on the PATH), or None if there isn't one."""
    return shutil.which(config.FFMPEG) or (config.FFMPEG if Path(config.FFMPEG).is_file() else None)


def clip_path(name: str) -> str:
    """The clip's path relative to the data folder, as stored in events.json."""
    return f"previews/{name}.mp4"


def make_clip(url: str, name: str) -> str | None:
    """The clip of the video at `url`, saved as previews/<name>.mp4 (once: reused if it exists); None if it
    can't be made."""
    target = config.DATA_DIR / clip_path(name)
    if target.exists():
        return clip_path(name)
    program = ffmpeg()
    if program is None:
        return None
    config.PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            _download(url, source)
            output = Path(folder) / "clip.mp4"
            command = [program, "-y", "-loglevel", "error", "-t", str(config.CLIP_SECONDS), "-i", str(source)]
            command += ["-an", "-vf", f"scale={config.CLIP_WIDTH}:-2,fps=24", "-c:v", "libx264", "-preset", "veryfast"]
            command += ["-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            shutil.move(output, target)
    except (OSError, requests.RequestException, subprocess.SubprocessError) as error:
        log.warning("     no clip for %s: %s", name, error)
        return None
    log.info("     clip: %s (%s KB)", target.name, target.stat().st_size // 1024)
    return clip_path(name)


def _download(url: str, path: Path) -> None:
    limit = config.CLIP_MAX_DOWNLOAD_MB * 1024 * 1024
    with requests.get(url, stream=True, timeout=config.HTTP_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        size = 0
        with path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1 << 16):
                size += len(chunk)
                if size > limit:
                    raise OSError(f"video over {config.CLIP_MAX_DOWNLOAD_MB} MB")
                file.write(chunk)
