"""Read and write data/events.json, the processed-posts state, the accounts list and flyer images.

Every load and save goes through the Pydantic models, so a malformed file is never written.
"""

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import TypeAdapter

from . import config
from .models import ProcessedPost, StoredEvent

_events_adapter = TypeAdapter(list[StoredEvent])
_processed_adapter = TypeAdapter(dict[str, ProcessedPost])


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Always LF line endings so files are identical on Windows and on the Linux CI runner.
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


# ---------- events ----------


def load_events() -> list[StoredEvent]:
    return _events_adapter.validate_python(_read_json(config.EVENTS_FILE, []))


def save_events(events: list[StoredEvent]) -> None:
    ordered = sorted(events, key=lambda event: (event.date or "9999", event.start_time or ""))
    _write_json(config.EVENTS_FILE, _events_adapter.dump_python(ordered, mode="json"))


# ---------- processed posts ----------


def load_processed_posts() -> dict[str, ProcessedPost]:
    return _processed_adapter.validate_python(_read_json(config.PROCESSED_POSTS_FILE, {}))


def save_processed_posts(processed: dict[str, ProcessedPost]) -> None:
    _write_json(config.PROCESSED_POSTS_FILE, _processed_adapter.dump_python(processed, mode="json"))


# ---------- accounts ----------


def read_accounts() -> list[str]:
    """Usernames from accounts.txt: one per line, '@' optional, '#' starts a comment."""
    lines = config.ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip().lstrip("@") for line in lines if line.strip() and not line.strip().startswith("#")]


# ---------- flyers ----------


def save_flyer(image_bytes: bytes, name: str) -> str:
    """Save a compressed WebP copy (Instagram image links expire). Returns the path relative to data/."""
    config.FLYERS_DIR.mkdir(parents=True, exist_ok=True)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail(config.FLYER_MAX_SIZE)
    path = config.FLYERS_DIR / f"{name}.webp"
    image.save(path, "WEBP", quality=config.FLYER_WEBP_QUALITY)
    return path.relative_to(config.DATA_DIR).as_posix()


def remove_unused_flyers(events: list[StoredEvent]) -> int:
    """Delete flyer files no event points to. Returns how many were deleted."""
    used = {event.flyer for event in events if event.flyer}
    unused = [
        path for path in config.FLYERS_DIR.glob("*.webp") if path.relative_to(config.DATA_DIR).as_posix() not in used
    ]
    for path in unused:
        path.unlink()
    return len(unused)
