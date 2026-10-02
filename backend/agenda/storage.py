"""Read and write the events file, the processed-posts state and flyer images."""

import io
import json
from pathlib import Path

from PIL import Image

from . import config


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Always LF line endings so files are identical on Windows and on the Linux CI runner.
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_accounts() -> list[str]:
    lines = config.ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
    return [l.strip().lstrip("@") for l in lines if l.strip() and not l.strip().startswith("#")]


def save_flyer(image_bytes: bytes, name: str) -> str:
    """Save a compressed WebP copy (Instagram image links expire). Returns the path relative to data/."""
    config.FLYERS_DIR.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((1080, 1350))
    path = config.FLYERS_DIR / f"{name}.webp"
    img.save(path, "WEBP", quality=80)
    return path.relative_to(config.DATA_DIR).as_posix()


def remove_unused_flyers(events: list[dict]) -> int:
    used = {e["flyer"] for e in events if e.get("flyer")}
    unused = [f for f in config.FLYERS_DIR.glob("*.webp") if f.relative_to(config.DATA_DIR).as_posix() not in used]
    for f in unused:
        f.unlink()
    return len(unused)


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e["date"] or "9999", e["start_time"] or ""))
