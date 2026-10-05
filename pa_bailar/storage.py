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
from .merging import ordered_media
from .models import AccountState, HiddenEvent, ProcessedPost, StoredEvent

_events_adapter = TypeAdapter(list[StoredEvent])
_processed_adapter = TypeAdapter(dict[str, ProcessedPost])
_accounts_adapter = TypeAdapter(dict[str, AccountState])
_hidden_adapter = TypeAdapter(dict[str, HiddenEvent])


def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data: Any) -> None:
    """Write atomically: a crash mid-write leaves the previous file intact instead of a truncated one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Always LF line endings so files are identical on Windows and on the Linux CI runner.
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


# ---------- events ----------


def load_events() -> list[StoredEvent]:
    return _events_adapter.validate_python(read_json(config.EVENTS_FILE, []))


def save_events(events: list[StoredEvent]) -> None:
    """Events by date and time; each event's posts in their order (merging.ordered_media), so every
    event follows it, including events stored before the order last changed."""
    ordered = [
        event.model_copy(update={"media": ordered_media(event.media)})
        for event in sorted(events, key=lambda event: (event.date or "9999", event.start_time or ""))
    ]
    write_json(config.EVENTS_FILE, _events_adapter.dump_python(ordered, mode="json"))


# ---------- run metadata ----------

SCHEMA_VERSION = 1  # bump on breaking changes to events.json


def save_meta(stats: dict[str, Any]) -> None:
    """data/meta.json: when the data was last refreshed (shown on the site), every account swept (the site's
    list of sources, including those without upcoming events) and what the run did."""
    meta = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": config.now_bogota().isoformat(timespec="seconds"),
        "accounts": sorted(read_accounts()),
        "stats": stats,
    }
    write_json(config.META_FILE, meta)


# ---------- processed posts ----------


def load_processed_posts() -> dict[str, ProcessedPost]:
    return _processed_adapter.validate_python(read_json(config.PROCESSED_POSTS_FILE, {}))


def save_processed_posts(processed: dict[str, ProcessedPost]) -> None:
    write_json(config.PROCESSED_POSTS_FILE, _processed_adapter.dump_python(processed, mode="json"))


# ---------- events hidden by hand ----------


def load_hidden_events() -> dict[str, HiddenEvent]:
    return _hidden_adapter.validate_python(read_json(config.HIDDEN_EVENTS_FILE, {}))


def save_hidden_events(hidden: dict[str, HiddenEvent]) -> None:
    write_json(config.HIDDEN_EVENTS_FILE, _hidden_adapter.dump_python(hidden, mode="json"))


# ---------- account state (backfill) ----------


def load_account_state() -> dict[str, AccountState]:
    return _accounts_adapter.validate_python(read_json(config.ACCOUNT_STATE_FILE, {}))


def save_account_state(accounts: dict[str, AccountState]) -> None:
    write_json(config.ACCOUNT_STATE_FILE, _accounts_adapter.dump_python(accounts, mode="json"))


# ---------- Gemini usage (requests per model on the current quota day) ----------


def load_gemini_usage() -> dict[str, Any]:
    usage: dict[str, Any] = read_json(config.GEMINI_USAGE_FILE, {})
    return usage


def save_gemini_usage(usage: dict[str, Any]) -> None:
    write_json(config.GEMINI_USAGE_FILE, usage)


# ---------- accounts ----------


def read_accounts() -> list[str]:
    """Usernames from accounts.txt: one per line, '@' optional, '#' starts a comment."""
    lines = config.ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip().lstrip("@") for line in lines if line.strip() and not line.strip().startswith("#")]


ADDED_BY_ADMIN = "# Added with the admin tools (admin add-account, sweep --post)"
_ADDED_BY_ADMIN_BEFORE = "# Added with the admin tools (admin add-account, add-post)"  # renamed when found


def add_account(account: str) -> bool:
    """Add an account to accounts.txt, in the admin tools' section (created before the commented-out notes at
    the end, if needed). False if it's already swept."""
    if account in read_accounts():
        return False
    lines = config.ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
    lines = [ADDED_BY_ADMIN if line == _ADDED_BY_ADMIN_BEFORE else line for line in lines]
    if ADDED_BY_ADMIN in lines:
        at = lines.index(ADDED_BY_ADMIN) + 1
        while at < len(lines) and lines[at].strip() and not lines[at].startswith("#"):
            at += 1  # after the section's last account
        lines.insert(at, account)
    else:
        # Before the first "# ----" separator (the notes that aren't swept), or at the end.
        at = next((i for i, line in enumerate(lines) if line.startswith("# ----")), len(lines))
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        lines[at:at] = ["", ADDED_BY_ADMIN, account]
    config.ACCOUNTS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return True


# ---------- flyers ----------


def save_flyer(image_bytes: bytes, name: str) -> str:
    """Save a compressed WebP copy (Instagram image links expire). Returns the path relative to data/."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    config.FLYERS_DIR.mkdir(parents=True, exist_ok=True)
    image.thumbnail(config.FLYER_MAX_SIZE)
    path = config.FLYERS_DIR / f"{name}.webp"
    image.save(path, "WEBP", quality=config.FLYER_WEBP_QUALITY)
    return path.relative_to(config.DATA_DIR).as_posix()


def remove_unused_flyers(events: list[StoredEvent]) -> int:
    """Delete flyer and clip files no event points to. Returns how many were deleted."""
    used = {path for event in events for media in event.media for path in (media.flyer, media.preview) if path}
    files = [*config.FLYERS_DIR.glob("*.webp"), *config.PREVIEWS_DIR.glob("*.mp4")]
    unused = [path for path in files if path.relative_to(config.DATA_DIR).as_posix() not in used]
    for path in unused:
        path.unlink()
    return len(unused)
