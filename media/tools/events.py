"""A snapshot of the site's events for a video: real titles, dates, prices and flyers, never made up.

  .venv/Scripts/python media/tools/events.py <video> --from 2026-10-09 --to 2026-10-11 [--styles salsa,bachata]
      [--limit 12] [--live] [--allow-empty]
  .venv/Scripts/python media/tools/events.py <video> --weekend [2026-10-10]   (Friday to Sunday of that week; today's)
  → projects/<video>/data/events.json (the events on any day of the range, trimmed to what videos use, plus "flyer"
    and "ratio", and the occurrence the video shows: "day", the first day of the event inside the range, with that
    day's "day_start"/"day_end", since a run of days or a workshop series has its own times per session), sorted by
    that day and time, and their cover flyers in public/<video>/flyers/. An empty result writes nothing (the last
    snapshot stays) unless --allow-empty.

The source is the site checkout next to the backend (pa-bailar-web/data, as fresh as its last pull), or with
--live the published data on GitHub. Composition code reads it with the helpers in src/data/events.ts (between,
weekend, dateLabel, timeLabel, priceLabel). Events go stale: a video built on them has a shelf life.
"""

import argparse
import json
import shutil
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from common import BACKEND, bogota_today, probe, shown, video

SITE_DATA = BACKEND.parent / "pa-bailar-web" / "data"
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
    """Friday to Sunday of the week of `of` (on a weekend day, that weekend)."""
    friday = of + timedelta(days=4 - of.weekday() if of.weekday() <= 4 else -(of.weekday() - 4))
    return friday, friday + timedelta(days=2)


def iso_day(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--from", dest="start", type=iso_day)
    parser.add_argument("--to", dest="end", type=iso_day)
    parser.add_argument("--weekend", nargs="?", const="", metavar="DATE")
    parser.add_argument("--styles", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--live", action="store_true")
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

    events = json.loads(fetch("events.json", args.live))
    picked = [
        e
        for e in events
        if any(args.start <= d <= args.end for d in days_of(e))
        and (not wanted or any(s.startswith(w) for s in e["styles"] for w in wanted))
    ]
    # By the day the video shows each one and its time there (the data is sorted by each event's first day).
    picked.sort(key=lambda e: (occurrence(e, args.start, args.end)[0], occurrence(e, args.start, args.end)[1] or "99"))
    if args.limit:
        picked = picked[: args.limit]
    if not picked and not args.allow_empty:
        raise SystemExit(
            f"no events from {args.start} to {args.end}: nothing written (--allow-empty to write it anyway)"
        )

    flyers = v.public / "flyers"
    if flyers.exists():
        shutil.rmtree(flyers)
    flyers.mkdir(parents=True)
    out = []
    for e in picked:
        item = {k: e.get(k) for k in KEEP}
        item["day"], item["day_start"], item["day_end"] = occurrence(e, args.start, args.end)
        cover = next((m["flyer"] for m in e["media"] if m.get("flyer")), None)
        item["flyer"] = item["ratio"] = None
        if cover:
            dest = flyers / Path(cover).name
            dest.write_bytes(fetch(cover, args.live))
            stream = probe(dest)["streams"][0]
            item["flyer"] = f"flyers/{dest.name}"
            item["ratio"] = round(stream["width"] / stream["height"], 4)
        out.append(item)

    v.data.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "from": args.start,
        "to": args.end,
        "styles": wanted,
        "source": "live" if args.live else "site checkout",
    }
    (v.data / "events.json").write_text(
        json.dumps({**snapshot, "events": out}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for item in out:
        print(f"{item['day']} {item['day_start'] or '--:--'} {item['title']} (@{item['account']})")
    print(f"{len(out)} events → {shown(v.data / 'events.json')}")


if __name__ == "__main__":
    main()
