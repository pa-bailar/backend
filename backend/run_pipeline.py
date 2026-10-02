"""Collect one-time dance events from the Instagram accounts in accounts.txt.

Fetches each account's recent posts, skips posts already analyzed, asks Gemini to extract
events, and writes the result to data/events.json plus the flyers in data/flyers/.

Usage (from the backend folder):
    .venv\\Scripts\\python run_pipeline.py             # posts from the last 7 days
    .venv\\Scripts\\python run_pipeline.py --days 14   # look further back
"""

import argparse
from datetime import datetime, timedelta, timezone

from agenda import config, instagram, storage
from agenda.extractor import Extractor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=config.DEFAULT_LOOKBACK_DAYS,
                        help="Only analyze posts published in the last N days")
    args = parser.parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    extractor = Extractor()
    events = storage.load_json(config.EVENTS_FILE, [])
    processed = storage.load_json(config.PROCESSED_FILE, {})
    stats = {"analyzed": 0, "events": 0, "discarded": 0, "errors": 0}

    for account in storage.read_accounts():
        print(f"\n== @{account}")
        try:
            posts = instagram.fetch_recent_posts(account)
        except Exception as e:
            print(f"   ERROR fetching posts: {e}")
            stats["errors"] += 1
            continue

        for post in posts:
            published = instagram.published_at(post)
            if post["id"] in processed or published < cutoff:
                continue
            print(f"   - {published:%Y-%m-%d} {post['media_type']:<14} {post['permalink']}")
            try:
                images = [instagram.download(u) for u in instagram.image_urls(post)]
                analysis, model = extractor.analyze(account, post, published, images)
            except Exception as e:
                print(f"     ERROR: {e}")
                stats["errors"] += 1
                continue  # not marked as processed, so it is retried next run

            stats["analyzed"] += 1
            processed[post["id"]] = {
                "account": account,
                "permalink": post["permalink"],
                "processed_at": datetime.now(config.BOGOTA).isoformat(timespec="seconds"),
                "is_event_post": analysis.is_event_post,
                "reason": analysis.reason,
                "model": model,
            }

            # Only one-time events with a date make it to the website.
            kept = [e for e in analysis.events if not e.is_recurring and e.date]
            stats["discarded"] += len(analysis.events) - len(kept)
            events = [e for e in events if e["source"]["post_id"] != post["id"]]

            if analysis.is_event_post and kept:
                for i, event in enumerate(kept):
                    # Each event gets the image that shows it; fall back to the first image.
                    index = event.image_index if event.image_index is not None and event.image_index < len(images) else 0
                    flyer = storage.save_flyer(images[index], f"{post['id']}-{index}") if images else None
                    events.append({
                        "id": f"{post['id']}-{i}",
                        **event.model_dump(exclude={"image_index"}),
                        "flyer": flyer,
                        "source": {
                            "account": account,
                            "post_id": post["id"],
                            "permalink": post["permalink"],
                            "published": post["timestamp"],
                            "caption": post.get("caption"),
                        },
                    })
                    stats["events"] += 1
                    print(f"     EVENT: {event.date} {event.start_time or ''} | {event.title} [{event.event_type}]")
            else:
                print(f"     skipped: {analysis.reason}")

            # Save after every post so progress survives an interrupted run.
            storage.save_json(config.EVENTS_FILE, storage.sort_events(events))
            storage.save_json(config.PROCESSED_FILE, processed)

    removed = storage.remove_unused_flyers(events)
    if removed:
        print(f"\nRemoved {removed} flyer images no event uses anymore.")
    print(f"\nDone: {stats['analyzed']} posts analyzed, {stats['events']} events saved, "
          f"{stats['discarded']} recurring/undated discarded, {stats['errors']} errors.")


if __name__ == "__main__":
    main()
