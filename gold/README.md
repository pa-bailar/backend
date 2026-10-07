# The test set

Forty posts whose events were checked by hand against their flyers (7 Oct 2026), so a model's reading can be scored
against the truth instead of against Flash: `python -m pa_bailar admin bakeoff --gold [--models …]`
(`pa_bailar/bakeoff.py`, section 4; docs/ADMIN.md). It spends one request per post and model, from the same quotas
as the sweeps; answers are cached in `state/bakeoff/gold/`, so a rerun only asks what's missing.

- `posts.json`: each post's account, caption, publication time, the day it's read on (`processed_at`), its flyer,
  `why` it's in the set, and its expected `events`.
- `flyers/`: the one image each post is read from (the slide its events are on), copied here so the set outlives
  the site's data (past events lose their flyers).

## What it covers

This weekend's backup reads (9–11 Oct 2026) and their errors, a venue's month as a grid (the "Salsoteca DC" error),
a date range read as one day ("11 OCT — 01 NOV"), workshop series, festivals over several days, several events in
one image or caption, relative dates ("este sábado"), doors versus show times, free nights, a venue other than the
account's, prices in the caption only, and posts with no time at all.

## An expected event

Only the fields the flyer and caption settle are written; a field left out isn't checked. A list means any of those
values is right (a title, a type, a start time: doors or show).

| Key | Checked how |
|---|---|
| `title` | half of the words of one of the right titles; `title_wrong`: words that make it wrong |
| `date`, `end_date`, `sessions` | exactly (`end_date` may list `null` as right) |
| `start_time`, `end_time` | HH:MM, `null` when the post gives none |
| `event_type` | one of the listed types |
| `venue` | a word in common with one of the listed names; `null`: none given |
| `prices` | the same set of amounts (`[]`: no price given, `[0]`: free) |
| `styles` | all of these, and nothing outside them and `styles_ok` |
| `optional` | neither missed nor extra (a meet & greet only in a VIP pack) |

## Adding posts

Pick posts whose events are on one image plus the caption (the bake-off sends one image), copy that image to
`flyers/`, and write what the flyer says, not what the site shows (the site merges several posts). Add the post's
known mistake to `why`. `tests/test_bakeoff.py` checks the file is well formed.
