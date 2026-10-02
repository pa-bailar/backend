# Data contract

The backend writes `data/`; the frontend only reads it. The Pydantic models in
[`backend/pabailar/models.py`](../backend/pabailar/models.py) are the source of truth, and
[`frontend/src/scripts/types.ts`](../frontend/src/scripts/types.ts) mirrors them.
Breaking changes bump `schema_version` in `meta.json` and update both sides in the same PR.

## Files

| File | Written by | Read by | Content |
|---|---|---|---|
| `data/events.json` | backend | frontend (build) | Array of events, sorted by date and start time |
| `data/meta.json` | backend | frontend (build) | `schema_version`, `generated_at` (Bogotá time) and stats of the last sweep that changed data. Only committed with a real change; the site's "Actualizado el" uses the daily check time passed by the deploy, falling back to `generated_at`. |
| `data/flyers/*.webp` | backend | frontend (static files) | Flyer copies, max 1080×1350, WebP q80 |
| `backend/state/processed_posts.json` | backend | backend | Posts already analyzed, keyed by post id; `provisional: true` when the light model extracted it (re-extracted with Flash later). |
| `backend/state/accounts.json` | backend | backend | Per account: `first_seen` and `backfill_done` (its first, deeper sweep is complete). |
| `backend/state/gemini_usage.json` | backend | backend | Requests per Gemini model on the current quota day (Pacific time), shared by same-day runs. |

On CI the whole `backend/state/` folder lives in the Actions cache between runs and is committed with
the next real data change.
| `backend/accounts.txt` | people | backend | Instagram usernames to follow |

## Event (`events.json` item)

| Field | Type | Notes |
|---|---|---|
| `id` | string | `<first post id>-<index>`. Stable when more posts are merged in. |
| `title` | string | As written on the flyer |
| `event_type` | `social` · `workshop` · `concert` · `festival` · `competition` · `show` · `other` | `social` includes parties; `workshop` includes one-time special classes |
| `is_recurring` | boolean | Always `false` in stored data (recurring events are discarded) |
| `styles` | Style[] | From the fixed list below; de-duplicated |
| `organizer`, `venue`, `address`, `area` | string \| null | |
| `date` | `YYYY-MM-DD` | Always a valid date (events without one are discarded) |
| `weekday` | string \| null | Spanish, as Gemini read it |
| `start_time`, `end_time` | `HH:MM` \| null | 24-hour; invalid times become `null` and are noted in `doubts` |
| `prices` | `{label, amount_cop, condition}[]` | `amount_cop` ≥ 0; `0` means free |
| `artists`, `activities` | string[] | |
| `contact` | string \| null | Phone/WhatsApp or @username |
| `confidence` | `high` · `medium` · `low` | Gemini's own estimate |
| `doubts` | string[] | Missing or assumed details, in Spanish |
| `account` | string | Instagram username of the organizer |
| `media` | `EventMedia[]` | Every post announcing the event. Main post first (images before videos, then oldest). At least one. |

### EventMedia

| Field | Type | Notes |
|---|---|---|
| `post_id` | string | Instagram media id |
| `permalink` | string | Link to the post |
| `media_type` | `IMAGE` · `CAROUSEL_ALBUM` · `VIDEO` | |
| `published` | string | Instagram timestamp, e.g. `2026-09-30T12:00:00+0000` |
| `flyer` | string \| null | Path relative to `data/`, e.g. `flyers/<post id>-<slide>.webp`. Shared by events announced on the same image. |
| `caption` | string \| null | Post text |

### Dance styles

Salsa and bachata have one level of specificity. The plain name is used when the variant can't be told, and it's dropped when a variant is known. Every other style stays general. The list is `Style` in `models.py`, and the synonyms are in `normalize.py`.

| Style | Includes |
|---|---|
| `salsa` | salsa, variant not stated |
| `salsa cubana` | casino, rueda de casino, timba |
| `salsa en línea` | on1, on2, mambo, New York / Los Angeles style |
| `salsa caleña` | estilo caleño |
| `bachata` | bachata, variant not stated (also moderna / fusión) |
| `bachata sensual` | |
| `bachata dominicana` | tradicional |
| `merengue`, `cha cha chá`, `son`, `kizomba`, `zouk`, `champeta`, `dancehall`, `heels`, `tango`, `swing` | as named |
| `urbano` | reguetón, hip hop, street |
| `afro` | afro, afrobeat, rumba cubana |
| `otro` | anything else |

On the site, filtering by **Salsa** or **Bachata** also shows their variants.

## Rules

- **Only one-time events with a valid date** are stored. Regular classes and recurring nights are dropped.
- **One event, many posts:** a flyer, a video and a reminder of the same event are one event with several `media` (see `backend/pabailar/merging.py`).
- **Re-analyzing a post** first removes what it contributed, so nothing is duplicated.
- **Writes are atomic** (temp file + rename) and every load/save is validated against the models.
- **Line endings are LF**, so files are identical on Windows and on the Linux CI runner.
- **Retention:** every sweep deletes events dated more than 30 days ago and their flyers, and forgets analyzed posts older than 45 days; see `docs/PLAN.md`.
