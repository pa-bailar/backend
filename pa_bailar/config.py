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
FLYERS_DIR = DATA_DIR / "flyers"
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

# ---------- Instagram (Meta Graph API) ----------
GRAPH_API_URL = "https://graph.facebook.com/v26.0"
POSTS_PER_ACCOUNT = 10  # regular sweep; one API call per account regardless of this number
# The admin tools look for a post among this many of the account's latest (one API call): `admin why`, add-post.
ADMIN_POST_SEARCH = 50
SITE_URL = "https://pa-bailar.github.io"  # the public site, for links to events in the admin tools' answers
# Instagram's quota for our app, as a share used (0-100, from its usage headers): the sweep stops reading
# accounts at this level instead of running into the limit, and discover pauses earlier (its own setting).
INSTAGRAM_USAGE_STOP = 90
# Each account is read about once a day (pipeline.Sweep._due_accounts): a sweep reads the accounts whose turn
# has come, those that waited longest first, and stops at its share (half the accounts plus a margin, for the
# two daily sweeps) or Instagram's limit; whoever it didn't reach is first next time. Quiet accounts (no post
# in QUIET_AFTER_DAYS) take their turn every other day. A bit under 24 h, so the same sweep the next day finds
# the account due.
SWEEP_EVERY_HOURS = 20
QUIET_SWEEP_EVERY_HOURS = 44
QUIET_AFTER_DAYS = 45
EXTRA_ACCOUNTS_PER_RUN = 5  # over each sweep's share, so a few late accounts still get read
MAX_IMAGES_PER_POST = 10  # monthly schedules often show an event on slide 5 or later; still one request
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
# Free-tier limits as shown in AI Studio (aistudio.google.com/rate-limit) on 2026-10-02.
# Update them here if Google changes the quotas.


@dataclass(frozen=True)
class ModelLimit:
    requests_per_minute: int
    requests_per_day: int


MODEL_LIMITS = {
    "gemini-3.8-flash": ModelLimit(requests_per_minute=5, requests_per_day=20),
    "gemini-3.5-flash": ModelLimit(requests_per_minute=5, requests_per_day=20),
    "gemini-3.5-flash-lite": ModelLimit(requests_per_minute=15, requests_per_day=500),
}
# Lite-only mode (GEMINI_LITE_ONLY=1, a repository variable on CI): Flash-Lite also does extraction, as final
# results, not provisional ones. For when Flash isn't available, e.g. if Google took it out of the free tier.
LITE_ONLY = os.environ.get("GEMINI_LITE_ONLY", "").strip() == "1"
# Each model has its own quota. Roles:
TRIAGE_MODELS = ("gemini-3.5-flash-lite",)  # cheap yes/no: does the post announce an event?
# Full details, best quality.
EXTRACTION_MODELS = ("gemini-3.5-flash-lite",) if LITE_ONLY else ("gemini-3.8-flash", "gemini-3.5-flash")
# When Flash is out: saved, then upgraded on a later run (none in lite-only mode).
PROVISIONAL_MODELS: tuple[str, ...] = () if LITE_ONLY else ("gemini-3.5-flash-lite",)
DAILY_BUDGET_MARGIN = 2  # requests kept unused per model, for manual runs and retries
# discover (run on your computer) shares the Gemini key with the sweeps, but its usage isn't in theirs: it
# reads what the sweeps used today (sweep-state branch) and leaves them at least this many Flash-Lite requests.
DISCOVERY_LEAVES_FOR_SWEEPS = 250
PACING_MARGIN_SECONDS = 0.5  # added to 60 / requests_per_minute between calls to the same model
GEMINI_TIMEOUT_SECONDS = 120  # one request; a stuck call fails instead of hanging the run
QUOTA_TIMEZONE = "America/Los_Angeles"  # Gemini daily quotas reset at midnight Pacific time

# ---------- Flyers ----------
FLYER_MAX_SIZE = (1080, 1350)  # 4:5, Instagram's tallest feed ratio
FLYER_WEBP_QUALITY = 80

# ---------- Pipeline ----------
DEFAULT_LOOKBACK_DAYS = 7
# The most a run may look back (--days, the workflow's `days` input): anyone able to start the workflow
# can't make one run spend the day's quotas on old posts. New accounts get BACKFILL_DAYS on their own.
MAX_LOOKBACK_DAYS = 30
# When cron-job.org starts the daily sweep (Bogotá time, README "What starts the sweep"). Other jobs that
# use the Instagram app's hourly quota (discover) keep clear of these times so the sweep finds it free.
SWEEP_TIMES = ("09:00", "21:00")
# A newly added account is swept more deeply until all of these posts have been analyzed
# (it can take a few runs if the daily Gemini budget runs out); then it joins the regular sweep.
BACKFILL_POSTS = 30
BACKFILL_DAYS = 30

# A run stops starting new Gemini work after this long and leaves the rest for the next run, inside the
# sweep step's 35-minute timeout (the job's is 60): the steps after it still save the state and the data.
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
# Events whose last day was more than this many days ago are deleted, and their flyers with them (git history
# keeps both).
EVENT_RETENTION_DAYS = 60
# Records of analyzed posts are forgotten after this many days. Must exceed BACKFILL_DAYS and the lookback:
# older posts are never fetched again, so forgetting them can't cause a second analysis.
PROCESSED_RETENTION_DAYS = 45

BOGOTA_TZ = ZoneInfo("America/Bogota")


def now_bogota() -> datetime:
    """The current time in Bogotá: dates and "today" are always Bogotá's, wherever the code runs."""
    return datetime.now(BOGOTA_TZ)


def bogota_date(moment: datetime) -> date:
    """The day a moment falls on in Bogotá: Instagram's times are UTC, and a post at 9 p.m. is that day's."""
    return moment.astimezone(BOGOTA_TZ).date()


def require_env(name: str) -> str:
    """Return a required environment variable or stop with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing environment variable {name}. Set it in {ENV_FILE} or as a GitHub secret.")
    return value
