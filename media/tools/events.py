"""A snapshot of the site's events for a video: real titles, dates, prices and flyers, never made up.

  .venv/Scripts/python media/tools/events.py <video> --from 2026-10-09 --to 2026-10-11 [--styles salsa,bachata]
      [--limit 12] [--live]
  → projects/<video>/data/events.json (the events on any day of the range, in date order, trimmed to what videos
    use, plus "flyer" and "ratio") and their cover flyers in public/<video>/flyers/

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

from common import BACKEND, MEDIA, probe, video

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--styles", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    v = video(args.video)
    wanted = [s.strip().lower() for s in args.styles.split(",") if s.strip()]

    events = json.loads(fetch("events.json", args.live))
    picked = [
        e
        for e in events
        if any(args.start <= d <= args.end for d in days_of(e))
        and (not wanted or any(s.startswith(w) for s in e["styles"] for w in wanted))
    ]
    if args.limit:
        picked = picked[: args.limit]

    flyers = v.public / "flyers"
    if flyers.exists():
        shutil.rmtree(flyers)
    flyers.mkdir(parents=True)
    out = []
    for e in picked:
        item = {k: e.get(k) for k in KEEP}
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
        print(f"{item['date']} {item['start_time'] or '--:--'} {item['title']} (@{item['account']})")
    print(f"{len(out)} events → {(v.data / 'events.json').relative_to(MEDIA).as_posix()}")


if __name__ == "__main__":
    main()
