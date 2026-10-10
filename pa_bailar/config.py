"""Paths, settings and secrets for the backend.

Secrets come from environment variables: from .env (repository root) locally, from GitHub Actions secrets on CI.
"""

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent  # the repository
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE)

# ---------- Files ----------
# Public output, read by the website: the data/ folder of the site repository (pa-bailar.github.io).
# Locally a clone next to this repository (Code/pa-bailar-web); on CI the workflow checks the site out
# and sets DATA_DIR.
DATA_DIR = Path(os.environ.get("DATA_DIR") or ROOT_DIR.parent / "pa-bailar-web" / "data").resolve()
EVENTS_FILE = DATA_DIR / "events.json"
META_FILE = DATA_DIR / "meta.json"
# The images live in their own repository (pa-bailar/media, media_store.py): the workflow copies them into
# data/flyers/ and data/previews/ before a run and pushes what changed after it; the site repository ignores them.
FLYERS_DIR = DATA_DIR / "flyers"
# Past events, archived instead of deleted (storage.archive_events): their records by the year of their last day
# (archive/<year>.json, in the site repository) and a small copy of their flyers (archive/flyers/, in the media one).
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_FLYERS_DIR = ARCHIVE_DIR / "flyers"
# Backend-only input and state (on CI the state is kept in this repository's sweep-state branch).
ACCOUNTS_FILE = ROOT_DIR / "accounts.txt"
STATE_DIR = ROOT_DIR / "state"
PRIVATE_DIR = ROOT_DIR / "private"  # your own files (Instagram export, keys): git-ignored
PROCESSED_POSTS_FILE = STATE_DIR / "processed_posts.json"
ACCOUNT_STATE_FILE = STATE_DIR / "accounts.json"
GEMINI_USAGE_FILE = STATE_DIR / "gemini_usage.json"
RUN_HISTORY_FILE = STATE_DIR / "run_history.json"  # each sweep in short, for the health checks (health.py)
# Events taken off the site by hand ("Ocultar", Sweep.hide_event): never published again from the same posts.
HIDDEN_EVENTS_FILE = STATE_DIR / "hidden_events.json"
# The admin requests that changed events (Agregar, a story, Ocultar), for the admin page's history (changes.py).
ADMIN_RUNS_FILE = STATE_DIR / "admin_runs.json"

# ---------- Instagram (Meta Graph API) ----------
GRAPH_API_URL = "https://graph.facebook.com/v26.0"
POSTS_PER_ACCOUNT = 10  # regular sweep; one API call per account regardless of this number
# The admin tools look for a post among this many of the account's latest (one API call): `admin why`, add-post.
ADMIN_POST_SEARCH = 50
SITE_URL = "https://pa-bailar.github.io"  # the public site, for links to events in the admin tools' answers
# The admin page (admin-web/): "Ocultar"'s answer links to it with a post filled in, to publish it again in one tap.
ADMIN_URL = "https://pa-bailar-admin.jzamorac-9.workers.dev"
# Instagram's quota for our app, as a share used (0-100, from its usage headers, over a rolling hour; at 100 every
# call fails until the hour rolls on). The sweep stops before a read that would take it past the ceiling: the share
# now plus the next read's expected cost (instagram_usage.ReadCosts), never starting one at the ceiling or above. Until
# 9 Oct 2026 it stopped flat at 90%: that morning Meta took three times its usual time per read (a median 4.3 s,
# against 1.6 s), the sweep reached 90% after 28 accounts and 23 waited; on a normal day the forecast lets a few more
# in. discover pauses earlier (its own setting).
INSTAGRAM_USAGE_CEILING = 98
# The expected cost of a read: the highest of this run's last few (each read's share before and after it, in the same
# header), and this before the run has measured one (a slow day's cost, so the first read never overshoots). Meta's
# cost of a read is its processing time ("total_time"): ~1.3% normally (8 Oct 2026), about three times that on the slow
# morning of 9 Oct.
INSTAGRAM_READ_COST = 4
INSTAGRAM_COST_WINDOW = 5
# Each account is read about once a day (pipeline.Sweep._due_accounts): a sweep reads the accounts whose turn
# has come, those that waited longest first, and stops at its share (a third of the accounts plus a margin, for the
# three daily sweeps) or Instagram's limit; whoever it didn't reach is first next time. Quiet accounts (no post in
# QUIET_AFTER_DAYS) and unproductive ones (UNPRODUCTIVE_AFTER_POSTS of their posts on record, PROCESSED_RETENTION_DAYS,
# and none an event) take their turn every other day, dormant ones (no post in DORMANT_AFTER_DAYS) once a week: each
# read is an Instagram call that rarely finds anything new, and each costs ~1.3% of the app's hourly allowance whatever
# it asks for (measured 8 Oct 2026; 128 accounts then: the owner chose these two tiers over a third sweep, then added
# one on 9 Oct when Meta slowed down). A bit under 24 h, so the same sweep the next day finds the account due (one read
# at 6:30 is due at 2:30: the 3:00 sweep takes it if it has room, and the 6:30 one reads the rest), and over 18 h (3:00
# to 21:00), so no sweep of the same day reads it again.
SWEEP_EVERY_HOURS = 20
QUIET_SWEEP_EVERY_HOURS = 44
QUIET_AFTER_DAYS = 30  # 45 until 8 Oct 2026
UNPRODUCTIVE_AFTER_POSTS = 10
DORMANT_SWEEP_EVERY_HOURS = 164  # a bit under a week
DORMANT_AFTER_DAYS = 180
EXTRA_ACCOUNTS_PER_RUN = 5  # over each sweep's share, so a few late accounts still get read
MAX_IMAGES_PER_POST = 10  # monthly schedules often show an event on slide 5 or later; still one request
OCR_MIN_SCORE = 0.6  # pieces of text read with less confidence are left out (stray marks on a photo; ocr.py)
OCR_ROW_OVERLAP = 0.6  # pieces this close (in line heights) to a row's first piece share its row (ocr.group_rows)
# Videos' preview clips (clips.py): when an event's image comes from a video (a reel, or a carousel's video slide),
# a short silent clip of it plays on the site. Made with ffmpeg (on GitHub's runners; locally FFMPEG or the PATH);
# without ffmpeg there are just no clips.
PREVIEWS_DIR = DATA_DIR / "previews"
CLIP_SECONDS = 6
CLIP_WIDTH = 480
CLIP_MAX_DOWNLOAD_MB = 80  # longer videos are skipped
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
HTTP_TIMEOUT_SECONDS = 30

# ---------- Gemini ----------
# Free-tier limits as shown in AI Studio (aistudio.google.com/rate-limit): update them here if Google changes the
# quotas. The model ids: list them with the API (client.models.list()); one listed may still be refused to this key
# (gemini-2.5-flash: "no longer available to new users", 6 Oct 2026).


@dataclass(frozen=True)
class ModelLimit:
    requests_per_minute: int
    requests_per_day: int


# The free tier's limits per model (AI Studio's rate-limit page, 6 Oct 2026): each model has its own daily quota.
MODEL_LIMITS = {
    "gemini-3.8-flash": ModelLimit(requests_per_minute=5, requests_per_day=20),
    "gemini-3.6-flash": ModelLimit(requests_per_minute=5, requests_per_day=20),
    "gemini-3.5-flash": ModelLimit(requests_per_minute=5, requests_per_day=20),
    "gemini-3-flash-preview": ModelLimit(requests_per_minute=5, requests_per_day=20),
    "gemini-3.5-flash-lite": ModelLimit(requests_per_minute=15, requests_per_day=500),
    "gemini-3.1-flash-lite": ModelLimit(requests_per_minute=15, requests_per_day=500),
}
# Lite-only mode (GEMINI_LITE_ONLY=1, a repository variable on CI): Flash-Lite also does extraction, as final
# results, not provisional ones. For when Flash isn't available, e.g. if Google took it out of the free tier.
LITE_ONLY = os.environ.get("GEMINI_LITE_ONLY", "").strip() == "1"
# Each model has its own quota, so each role takes several, in order (the owner, 6 Oct 2026: Flash's 40 a day were
# the binding limit while 3.7 and 3.6 Flash and a second Flash-Lite sat unused). Roles:
LITE_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
TRIAGE_MODELS = LITE_MODELS  # cheap yes/no: does the post announce an event?
# Full details, best quality: Flash of this generation (60 a day; the bake-off's baseline). Lite-only mode:
# Flash-Lite, as final results.
# Not gemini-3.7-flash: deprecated on 9 Oct 2026, its calls are answered by 3.8 Flash (checked: response model_version),
# so in the pool it only spent 3.8's quota under another name, and its own budget of 20 was never real.
FLASH_MODELS = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash")
EXTRACTION_MODELS = LITE_MODELS if LITE_ONLY else FLASH_MODELS
# When those are out: saved, then upgraded on a later run (none in lite-only mode). An older Flash first (its reads
# weren't compared with this generation's yet: a 6 Oct bake-off met Google's overload), then Flash-Lite.
PROVISIONAL_MODELS: tuple[str, ...] = () if LITE_ONLY else ("gemini-3-flash-preview", *LITE_MODELS)
DAILY_BUDGET_MARGIN = 2  # requests kept unused per model, for manual runs and retries
# A post no model gives valid JSON for (gemini.UnreadableAnswerError) is retried on this many runs, then recorded as
# rejected: each run spends Flash's small quota on it.
UNREADABLE_RUNS = 3
# discover (run on your computer) shares the Gemini key with the sweeps, but its usage isn't in theirs: it
# reads what the sweeps used today (sweep-state branch) and leaves them at least this many Flash-Lite requests.
DISCOVERY_LEAVES_FOR_SWEEPS = 250
PACING_MARGIN_SECONDS = 0.5  # added to 60 / requests_per_minute between calls to the same model
GEMINI_TIMEOUT_SECONDS = 120  # one request; a stuck call fails instead of hanging the run
QUOTA_TIMEZONE = "America/Los_Angeles"  # Gemini daily quotas reset at midnight Pacific time
# A sweep whose upgrades find Flash only paused as busy waits for the pause to end, once (Sweep._wait_for_flash), if
# this much of its time budget (MAX_RUN_MINUTES) is still left after the wait: for the upgrades themselves.
FLASH_WAIT_MARGIN_SECONDS = 4 * 60

# ---------- External providers (the last resort) ----------
# Models outside Gemini, on OpenAI-compatible chat APIs (external.py), used only for the extraction, when Flash and
# Flash-Lite are both out of today's quota or not available to the key. Never for the triage: with Flash-Lite out
# and Flash out too, the post goes straight to the extraction, which decides alone (Groq's tokens per minute don't
# fit a triage and an extraction of the same post). Their answers are always provisional (re-read with Gemini on a
# later run, as Flash-Lite's are).
# Providers are tried in this order, each only if its key is set. Lite-only mode keeps them as the last resort
# (their reads are then re-read by Flash-Lite). `admin bakeoff` compares the models with Flash, to re-check them
# from time to time: free models come and go without notice. The list stays explicit: nothing switches by itself.


@dataclass(frozen=True)
class ExternalModel:
    name: str
    # Structured output (OpenRouter): `response_format` json_schema (strict) and `provider.require_parameters`, so
    # only providers that honor the schema serve it. Otherwise json_object, with the schema in the prompt. Either way
    # the answer is checked against the Pydantic schema.
    structured: bool = False


@dataclass(frozen=True)
class ExternalProvider:
    name: str  # also the prefix of the model recorded for a post: "groq:qwen/qwen3.8-27b"
    url: str  # its chat/completions endpoint
    key_env: str  # the environment variable with its key: unset, the provider is skipped
    models: tuple[ExternalModel, ...]  # in order of preference
    requests_per_minute: int
    daily_requests: int  # our budget: kept under the provider's free daily limit
    tokens_per_minute: int | None = None  # paced by an estimate of each request's tokens (external.py)
    daily_tokens: int | None = None
    max_images: int | None = None  # per request: the first ones are sent
    # OpenRouter's routing: one request names several models (`models`, at most 3) and OpenRouter tries the next one
    # itself when a model is rate-limited, down or fails. Models of the same output mode go in one request.
    routing: bool = False


EXTERNAL_PROVIDERS = (
    # Groq's free plan (console.groq.com/docs/rate-limits, 2026-10-05): 30 requests/minute and 1,000/day, but only
    # 8,000 tokens/minute and 200,000/day; each image counts as 2,048 input tokens, and a request takes at most 3.
    # Its only vision model: qwen/qwen3.8-27b. JSON mode works with images.
    ExternalProvider(
        name="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        key_env="GROQ_API_KEY",
        models=(ExternalModel("qwen/qwen3.8-27b"),),
        requests_per_minute=30,
        daily_requests=900,
        tokens_per_minute=8_000,
        daily_tokens=180_000,
        max_images=3,
    ),
    # OpenRouter's free models without credit on the account: 20 requests/minute and 50/day, all free models
    # together. Free models come and go: qwen/qwen3.8-27b:free went paid-only on 2026-10-05 (it answered 404), so
    # check with `admin bakeoff --discover`. Gemma takes only json_object; `openrouter/free` routes to a random free
    # model that takes the schema (strict json_schema with require_parameters): the very last try.
    ExternalProvider(
        name="openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        key_env="OPENROUTER_API_KEY",
        models=(
            ExternalModel("google/gemma-4-31b-it:free"),
            ExternalModel("google/gemma-4-26b-a4b-it:free"),
            ExternalModel("openrouter/free", structured=True),
        ),
        requests_per_minute=20,
        daily_requests=40,
        routing=True,
    ),
)
EXTERNAL_TIMEOUT_SECONDS = 60  # one request, then the next model: no retries
EXTERNAL_IMAGE_TOKENS = 2_048  # an image's input tokens, for the token estimate (Groq's count)
EXTERNAL_ANSWER_TOKENS = 800  # an answer's tokens, estimated before the request (the real count replaces it)
# The smallest request the sweep sends to a token-limited provider (an extraction without images: its prompt and
# schema, about 4,200 tokens, and the answer; a test keeps it a floor): a provider with fewer of its daily tokens
# left can't be asked today (ExternalTier.has_budget), so no post downloads its images just to be skipped.
EXTERNAL_MIN_REQUEST_TOKENS = 5_000
# When a provider's per-minute tokens are used, wait for them at most this long; longer, and the post goes on without
# it. A minute: Groq's 8,000 tokens a minute fit one extraction (about 7,250 tokens with one image), so each
# extraction waits for the one before to leave the minute.
EXTERNAL_MAX_WAIT_SECONDS = 60
# The most one post may spend on the last resort, waits included (also never past the run's time budget): Groq's
# wait and request (60 + 60 s), then OpenRouter only if a request (60 s) still fits.
EXTERNAL_MAX_SECONDS_PER_POST = 180
# A model that fails this many times in a run (busy upstream, a 5xx, a timeout, an answer that isn't the schema's
# JSON) is set aside for the rest of the run.
EXTERNAL_FAILURES_TO_QUARANTINE = 2
EXTERNAL_USAGE_FILE = STATE_DIR / "external_usage.json"  # today's use per provider (the day is UTC's)
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"  # `admin bakeoff --discover`: the free models now

# ---------- Flyers ----------
FLYER_MAX_SIZE = (1080, 1350)  # 4:5, Instagram's tallest feed ratio
# 75: measured on all 152 flyers (5 Oct 2026), 15% smaller than 80 with no visible difference in their fine print
# (SSIM 0.990 against 0.995; a side-by-side at 2× zoom showed none). Lower starts to cost text edges for little.
FLYER_WEBP_QUALITY = 75
# The archive's copy: enough to recognize the flyer, about a fifth of its size.
ARCHIVE_FLYER_MAX_SIZE = (480, 600)
ARCHIVE_FLYER_WEBP_QUALITY = 60

# ---------- Pipeline ----------
DEFAULT_LOOKBACK_DAYS = 7
# The most a run may look back (--days, the workflow's `days` input): anyone able to start the workflow
# can't make one run spend the day's quotas on old posts. New accounts get BACKFILL_DAYS on their own.
MAX_LOOKBACK_DAYS = 30
# When the daily sweep starts (Bogotá time, README "What starts the sweep"): 3:00 by GitHub's own schedule
# (daily-sweep.yml's cron, 08:00 UTC), 6:30 and 21:00 by cron-job.org; each must match. Other jobs that use the
# Instagram app's hourly quota (discover) keep clear of these times so the sweep finds it free. The morning one was
# 09:00 until 7 Oct 2026: Google's Flash refused 97% of weekday 9:00 requests as busy (the owner). The 3:00 one was
# added on 9 Oct 2026 (the owner): Meta took three times its usual time per read that morning, so the 6:30 sweep reached
# Instagram's hourly limit with 23 accounts left; a third sweep reads a third of the accounts each, and at 3:00 Meta and
# Google are quiet. It's the first of the Gemini quota day, which starts at midnight Pacific: 2:00 Bogotá, or 3:00 sharp
# in the Pacific's winter (November to March), when GitHub's start (never early, often late) still falls in the new day.
SWEEP_TRIGGERS = {
    "03:00": "GitHub's schedule (daily-sweep.yml's cron)",  # tests/test_workflows.py checks the cron matches
    "06:30": "cron-job.org",
    "21:00": "cron-job.org",
}
SWEEP_TIMES = tuple(SWEEP_TRIGGERS)
# Flash's few daily requests are shared by every sweep of a Gemini quota day (midnight to midnight Pacific: the 3:00,
# 6:30 and 21:00 sweeps fall in one). A sweep leaves the later ones of that day an equal share each (flash_reserve in
# pipeline/sweep.py): before, the morning's (academies, few posts) could take them all and the evening's (the busy
# organizers and bars) got none (the owner, 6 Oct 2026). A scheduled sweep starting within this margin is the current
# run (a late start), not a later one.
LATER_SWEEP_MARGIN_MINUTES = 60
# A newly added account is swept more deeply until all of these posts have been analyzed
# (it can take a few runs if the daily Gemini budget runs out); then it joins the regular sweep.
BACKFILL_POSTS = 30
BACKFILL_DAYS = 30

# A run stops starting new Gemini work after this long and leaves the rest for the next run, inside the
# sweep step's 35-minute timeout (the job's is 90): the steps after it still save the state and the data. No request
# starts after it (EventExtractor's deadline), so a run ends at most one Gemini request and one pause later (120 s +
# 60 s), and the last resort never starts a request (or a wait) that wouldn't end before it.
MAX_RUN_MINUTES = 30

# Events over several consecutive days (a congress, a festival weekend) have an end_date: at most this many
# days in all. A longer range is dropped as a misreading (normalize.py), and the event keeps its first day.
MAX_EVENT_DAYS = 7
# A workshop series (a finite program on separate, non-consecutive dates, every one of them written in the post: a
# "programa intensivo" on four Sundays) is one event with its `sessions`: from MIN to MAX sessions, the last one at
# most MAX_SERIES_DAYS days in all after the first (4 months). Anything longer is a course: not published.
MIN_SERIES_SESSIONS = 2
MAX_SERIES_SESSIONS = 12
MAX_SERIES_DAYS = 123
# New series are listed for a look in `admin status` (and the admin page) this long after first published.
NEW_SERIES_DAYS = 14

# ---------- Retention ----------
# Events whose last day was more than this many days ago leave the site: archived (storage.archive_events), their
# full flyers and clips deleted (the media repository's history keeps them until it's reset).
EVENT_RETENTION_DAYS = 60
# Records of analyzed posts are forgotten after this many days. Must exceed BACKFILL_DAYS and the lookback:
# older posts are never fetched again, so forgetting them can't cause a second analysis.
PROCESSED_RETENTION_DAYS = 45

# ---------- The admin page's history (changes.py) ----------
# What happened to which event in a run (added, merged, corrected, cancelled...), kept with the run for the admin page's
# "Historial": at most this many per run, the most telling first (changes.KIND_ORDER); the rest are only counted.
RUN_CHANGES_KEPT = 80
# Kept for the latest runs only (a week of sweeps): older records keep their counts, so run_history.json stays small.
CHANGES_KEPT_RUNS = 14
# The admin requests' runs kept (state/admin_runs.json).
ADMIN_RUNS_KEPT = 20

BOGOTA_TZ = ZoneInfo("America/Bogota")


def now_bogota() -> datetime:
    """The current time in Bogotá: dates and "today" are always Bogotá's, wherever the code runs."""
    return datetime.now(BOGOTA_TZ)


def bogota_date(moment: datetime) -> date:
    """The day a moment falls on in Bogotá: Instagram's times are UTC, and a post at 9 p.m. is that day's."""
    return moment.astimezone(BOGOTA_TZ).date()


def optional_env(name: str) -> str | None:
    """An environment variable that may be unset (an optional service's key): None when it's missing or empty."""
    return os.environ.get(name, "").strip() or None


def require_env(name: str) -> str:
    """Return a required environment variable or stop with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing environment variable {name}. Set it in {ENV_FILE} or as a GitHub secret.")
    return value
