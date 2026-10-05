"""A snapshot of the site's events for a video: real titles, dates, prices and flyers, never made up.

  .venv/Scripts/python media/tools/events.py <video> --from 2026-10-09 --to 2026-10-11 [--styles salsa,bachata]
      [--limit 12] [--checkout] [--allow-empty]
  .venv/Scripts/python media/tools/events.py <video> --weekend [2026-10-10]   (the weekend rule below; today's)
  → projects/<video>/data/events.json (the events on any day of the range, trimmed to what videos use, plus "flyer"
    and "ratio", and the occurrence the video shows: "day", the first day of the event inside the range, with that
    day's "day_start"/"day_end", since a run of days or a workshop series has its own times per session), sorted by
    that day and time, and their cover flyers in the media home's public/<video>/flyers/. An empty result writes
    nothing (the last snapshot stays) unless --allow-empty.

The source is the published data on GitHub (what the site shows now). When it can't be reached, or with --checkout,
it's the site checkout next to the backend (pa-bailar-web/data), and the tool says how old that checkout's data is.
Both files are written whole or not at all: the flyers go to a fresh folder that replaces the old one, then
events.json is replaced, so a failed run leaves the last snapshot and its flyers together.

The weekend rule (the same in src/data/events.ts weekend() and tools/capture.mjs weekendClock()): Friday to Sunday;
Monday to Thursday → the coming one; Friday, Saturday or Sunday → the one under way (on Sunday, the weekend ending
today). Composition code reads the snapshot with the helpers in src/data/events.ts (between, weekend, dateLabel,
timeLabel, priceLabel). Events go stale: a video built on them has a shelf life (render.py warns past "to").
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from common import BACKEND, Video, bogota_today, probe, shown, video

SITE = BACKEND.parent / "pa-bailar-web"
SITE_DATA = SITE / "data"
RAW = "https://raw.githubusercontent.com/pa-bailar/pa-bailar.github.io/main/data/"
KEEP = [
    "id",
    "title",
    "event_type",
    "styles",
    "organizer",
    "venue",
    "area",
    "date",
    "end_date",
    "sessions",
    "start_time",
    "end_time",
    "prices",
    "account",
]


def fetch(rel: str, live: bool) -> bytes:
    if live:
        with urllib.request.urlopen(RAW + rel, timeout=30) as r:
            return r.read()
    return (SITE_DATA / rel).read_bytes()


def checkout_age() -> str:
    """How old the site checkout's events are: its last commit touching data/events.json, else the file's time."""
    done = subprocess.run(
        ["git", "-C", str(SITE), "log", "-1", "--format=%cr (%cs)", "--", "data/events.json"],
        capture_output=True,
        text=True,
    )
    if done.returncode == 0 and done.stdout.strip():
        return f"last commit {done.stdout.strip()}"
    path = SITE_DATA / "events.json"
    if path.exists():
        return f"file from {datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M}"
    return "missing"


def load_events(checkout: bool) -> tuple[list[dict], bool]:
    """The site's events and whether they came live (else from the checkout, with a note of its age)."""
    if not checkout:
        try:
            return json.loads(fetch("events.json", True)), True
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"WARNING: the published data can't be reached ({error}); using the site checkout", file=sys.stderr)
    print(f"site checkout {SITE_DATA}: {checkout_age()}", file=sys.stderr)
    return json.loads(fetch("events.json", False)), False


def days_of(e: dict) -> list[str]:
    if e.get("sessions"):
        return [s["date"] for s in e["sessions"]]
    first = date.fromisoformat(e["date"])
    last = date.fromisoformat(e["end_date"]) if e.get("end_date") else first
    return [(first + timedelta(d)).isoformat() for d in range((last - first).days + 1)]


def occurrence(e: dict, start: str, end: str) -> tuple[str, str | None, str | None]:
    """The first day of `e` inside [start, end] and that day's times (a session's own, for a workshop series)."""
    for session in e.get("sessions") or []:
        if start <= session["date"] <= end:
            return session["date"], session["start_time"], session["end_time"]
    day = next(d for d in days_of(e) if start <= d <= end)
    return day, e.get("start_time"), e.get("end_time")


def weekend(of: date) -> tuple[date, date]:
    """Friday to Sunday: Monday to Thursday → the coming weekend; Friday to Sunday → the one under way (on Sunday,
    the weekend ending today)."""
    friday = of + timedelta(days=4 - of.weekday() if of.weekday() <= 4 else -(of.weekday() - 4))
    return friday, friday + timedelta(days=2)


def pick(events: list[dict], start: str, end: str, wanted: list[str], limit: int) -> list[dict]:
    """The events on any day of [start, end] (of the wanted styles), by the day the video shows and its time."""
    picked = [
        e
        for e in events
        if any(start <= d <= end for d in days_of(e))
        and (not wanted or any(s.startswith(w) for s in e["styles"] for w in wanted))
    ]
    picked.sort(key=lambda e: (occurrence(e, start, end)[0], occurrence(e, start, end)[1] or "99"))
    return picked[:limit] if limit else picked


def iso_day(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text}") from error


def write_snapshot(v: Video, picked: list[dict], meta: dict, live: bool) -> list[dict]:
    """The flyers into a fresh folder that then replaces the old one, then events.json replaced whole."""
    flyers = v.public / "flyers"
    fresh = flyers.with_name(f".flyers-{os.getpid()}")
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir(parents=True)
    out = []
    for e in picked:
        item = {k: e.get(k) for k in KEEP}
        item["day"], item["day_start"], item["day_end"] = occurrence(e, meta["from"], meta["to"])
        cover = next((m["flyer"] for m in e["media"] if m.get("flyer")), None)
        item["flyer"] = item["ratio"] = None
        if cover:
            dest = fresh / Path(cover).name
            dest.write_bytes(fetch(cover, live))
            stream = probe(dest)["streams"][0]
            item["flyer"] = f"flyers/{dest.name}"
            item["ratio"] = round(stream["width"] / stream["height"], 4)
        out.append(item)
    old = flyers.with_name(f".flyers-old-{os.getpid()}")
    if flyers.exists():
        flyers.rename(old)
    fresh.rename(flyers)
    shutil.rmtree(old, ignore_errors=True)
    v.data.mkdir(parents=True, exist_ok=True)
    tmp = v.data / ".events.json.tmp"
    tmp.write_text(json.dumps({**meta, "events": out}, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    os.replace(tmp, v.data / "events.json")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--from", dest="start", type=iso_day)
    parser.add_argument("--to", dest="end", type=iso_day)
    parser.add_argument("--weekend", nargs="?", const="", metavar="DATE")
    parser.add_argument("--styles", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--checkout", action="store_true", help="read the site checkout instead of the live data")
    parser.add_argument("--live", action="store_true", help=argparse.SUPPRESS)  # the default now; kept for old notes
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()
    if args.weekend is not None:
        friday, sunday = weekend(date.fromisoformat(iso_day(args.weekend)) if args.weekend else bogota_today())
        args.start, args.end = friday.isoformat(), sunday.isoformat()
    if not args.start or not args.end:
        parser.error("give --from and --to, or --weekend")
    if args.start > args.end:
        parser.error(f"--from {args.start} is after --to {args.end}")
    v = video(args.video)
    wanted = [s.strip().lower() for s in args.styles.split(",") if s.strip()]

    events, live = load_events(args.checkout)
    picked = pick(events, args.start, args.end, wanted, args.limit)
    if not picked and not args.allow_empty:
        raise SystemExit(
            f"no events from {args.start} to {args.end}: nothing written (--allow-empty to write it anyway)"
        )
    meta = {"from": args.start, "to": args.end, "styles": wanted, "source": "live" if live else "site checkout"}
    out = write_snapshot(v, picked, meta, live)
    for item in out:
        print(f"{item['day']} {item['day_start'] or '--:--'} {item['title']} (@{item['account']})")
    print(f"{len(out)} events → {shown(v.data / 'events.json')}")


if __name__ == "__main__":
    main()
