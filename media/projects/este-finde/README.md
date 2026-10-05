# Este finde

A 12 s Story of the coming weekend's events, built only from the site's data, with no voice: the owner adds
Instagram's music and a link sticker. It's an example of a data-driven video from the kit. It hasn't been reviewed
by the owner and was never posted.

It opens on the page head (stripes and "Este finde", the dates and the count), then shows up to four events, one per
beat (flyer, day, title, time · price · area · @account). The cards leave on a downbeat, and the app icon, the
record, the wordmark and "Link aquí abajo 👇" follow.

## Each week

From the backend root:

```bash
.venv/Scripts/python media/tools/events.py este-finde --from 2026-10-09 --to 2026-10-11 --live
```

```bash
.venv/Scripts/python media/tools/render.py este-finde
```

Then check `media/out/este-finde/story.mp4` with `review.py sheet`. Nothing in `EsteFinde.tsx` names an event. Long
titles clip at two lines, and more than four events show as the count in the subtitle.
