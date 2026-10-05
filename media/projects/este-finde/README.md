# Este finde

A 12 s Story of the coming weekend's events, built only from the site's data, with no voice: the owner adds
Instagram's music and a link sticker. It's an example of a data-driven video from the kit. It hasn't been reviewed
by the owner and was never posted.

It opens on the page head (stripes and "Este finde", the dates and the count, in the sans: no digits in the Bodoni),
then shows up to four events, one per beat (flyer, day, title, time · price · @account). The cards leave on a
downbeat, and the end card follows, laid out like the teaser's: "Link aquí arriba" with the drawn arrow right under
the band at the top where the owner puts the link sticker (nothing enters y < 250 on any frame), the app icon and the
record, the wordmark and "Nos vemos bailando." It fades in and doesn't fade out (a Story).

## Each week

From the backend root:

```bash
.venv/Scripts/python media/tools/events.py este-finde --weekend
```

```bash
.venv/Scripts/python media/tools/make.py este-finde
```

`--weekend` follows the weekend rule (Monday to Thursday the coming one, Friday to Sunday the one under way). The
render is `out/este-finde/este-finde-v<version>-story.mp4` in the media home, with its keyframe sheet and the
sticker-band check (`make.py` runs them); bump `version` in `video.json` for each week's cut. Nothing in `EsteFinde.tsx` names an event. Long
titles clip at two lines, and more than four events show as the count in the subtitle.
