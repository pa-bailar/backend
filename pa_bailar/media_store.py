"""The images' own repository, pa-bailar/media (the owner, 5 Oct 2026): flyers and clips grew the site repository's
history by hundreds of MB a year, and its data pull requests keep every old image alive for good. The site
repository now ignores data/flyers/ and data/previews/; this repository holds them, plus the archive's small flyers.

Every run copies the images into the site checkout's data/ (`pull`), works on them there as before, then copies
back what changed (`push`); the workflow commits and pushes the media repository before it opens the data PR.
The site's build copies flyers/ and previews/ into its data/ the same way, so the images keep their addresses.

    python -m pa_bailar.media_store pull <media checkout> <data folder>
    python -m pa_bailar.media_store push <data folder> <media checkout> [--published <events.json>]
"""

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

CURRENT = ("flyers", "previews")  # the images of the events on the site: copied both ways, the unused removed
ARCHIVE = "archive/flyers"  # the archive's small flyers: only ever added


@dataclass
class PushReport:
    added: int = 0
    updated: int = 0
    removed: int = 0


def pull(media: Path, data: Path) -> int:
    """Copy the current images from the media checkout into data/. Returns how many files were copied."""
    copied = 0
    for folder in CURRENT:
        source = media / folder
        if not source.is_dir():
            continue
        (data / folder).mkdir(parents=True, exist_ok=True)
        for file in source.iterdir():
            if file.is_file():
                shutil.copy2(file, data / folder / file.name)
                copied += 1
    return copied


def used_images(events_file: Path) -> set[str]:
    """Every image the events in `events_file` point to, as paths relative to data/ ("flyers/x.webp")."""
    if not events_file.exists():  # never decide what to remove without the events
        raise SystemExit(f"{events_file} is missing: not touching the media repository.")
    events = json.loads(events_file.read_text(encoding="utf-8"))
    return {
        path for event in events for item in event.get("media", []) for path in (item.get("flyer"), item.get("preview"))
        if path
    }  # fmt: skip


def push(data: Path, media: Path, published: Path | None = None) -> PushReport:
    """Copy new and changed images from data/ into the media checkout, and remove from it the current images no
    longer used. A file is removed only when no event points to it AND it's gone from data/ too, so a run that
    couldn't pull (an empty data/flyers/) never empties the repository: its events still point to the images.

    `published`: the events the site has now (its main when the run started). Their images stay too: the data PR
    merges minutes after this push, and until then every build and check reads those events (removing an
    archived event's image at once failed them, 5 Oct 2026). The next run removes them, once the PR has merged."""
    report = PushReport()
    used = used_images(data / "events.json") | (used_images(published) if published else set())
    for folder in (*CURRENT, ARCHIVE):
        source = data / folder
        if not source.is_dir():
            continue
        (media / folder).mkdir(parents=True, exist_ok=True)
        for file in source.iterdir():
            target = media / folder / file.name
            if not file.is_file() or (target.exists() and target.read_bytes() == file.read_bytes()):
                continue
            report.updated += target.exists()
            report.added += not target.exists()
            shutil.copy2(file, target)
    for folder in CURRENT:
        for file in (media / folder).glob("*") if (media / folder).is_dir() else []:
            path = f"{folder}/{file.name}"
            if file.is_file() and path not in used and not (data / path).exists():
                file.unlink()
                report.removed += 1
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m pa_bailar.media_store", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    pull_args = sub.add_parser("pull", help="media checkout → data/")
    pull_args.add_argument("media", type=Path)
    pull_args.add_argument("data", type=Path)
    push_args = sub.add_parser("push", help="data/ → media checkout")
    push_args.add_argument("data", type=Path)
    push_args.add_argument("media", type=Path)
    push_args.add_argument("--published", type=Path, help="the site's events.json before the run: its images stay")
    args = parser.parse_args()
    if args.action == "pull":
        print(f"Copied {pull(args.media, args.data)} images from {args.media} into {args.data}.")
    else:
        report = push(args.data, args.media, args.published)
        print(f"Media: {report.added} added, {report.updated} updated, {report.removed} removed.")


if __name__ == "__main__":
    main()
