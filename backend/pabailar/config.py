"""Paths, settings and secrets for the backend.

Secrets come from environment variables: from backend/.env locally, from GitHub Actions secrets on CI.
"""

import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
ENV_FILE = BACKEND_DIR / ".env"
load_dotenv(ENV_FILE)

# ---------- Files ----------
# Public output, read by the website.
DATA_DIR = PROJECT_DIR / "data"
EVENTS_FILE = DATA_DIR / "events.json"
META_FILE = DATA_DIR / "meta.json"
FLYERS_DIR = DATA_DIR / "flyers"
# Backend-only input and state (on CI the state folder lives in the Actions cache between runs).
ACCOUNTS_FILE = BACKEND_DIR / "accounts.txt"
STATE_DIR = BACKEND_DIR / "state"
PROCESSED_POSTS_FILE = STATE_DIR / "processed_posts.json"
ACCOUNT_STATE_FILE = STATE_DIR / "accounts.json"
GEMINI_USAGE_FILE = STATE_DIR / "gemini_usage.json"

# ---------- Instagram (Meta Graph API) ----------
GRAPH_API_URL = "https://graph.facebook.com/v26.0"
POSTS_PER_ACCOUNT = 10  # regular sweep; one API call per account regardless of this number
MAX_IMAGES_PER_POST = 10  # monthly schedules often show an event on slide 5 or later; still one request
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
# Each model has its own quota. Roles:
TRIAGE_MODELS = ["gemini-3.5-flash-lite"]  # cheap yes/no: does the post announce an event?
EXTRACTION_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash"]  # full details, best quality
PROVISIONAL_MODELS = ["gemini-3.5-flash-lite"]  # when Flash is out: saved, then upgraded on a later run
DAILY_BUDGET_MARGIN = 2  # requests kept unused per model, for manual runs and retries
PACING_MARGIN_SECONDS = 0.5  # added to 60 / requests_per_minute between calls to the same model
QUOTA_TIMEZONE = "America/Los_Angeles"  # Gemini daily quotas reset at midnight Pacific time

# ---------- Flyers ----------
FLYER_MAX_SIZE = (1080, 1350)  # 4:5, Instagram's tallest feed ratio
FLYER_WEBP_QUALITY = 80

# ---------- Pipeline ----------
DEFAULT_LOOKBACK_DAYS = 7
# A newly added account is swept more deeply until all of these posts have been analyzed
# (it can take a few runs if the daily Gemini budget runs out); then it joins the regular sweep.
BACKFILL_POSTS = 30
BACKFILL_DAYS = 30

# A run stops starting new Gemini work after this long and leaves the rest for the next run, well inside
# the workflow's 45-minute timeout: a timed-out run loses everything it did (and its quota).
MAX_RUN_MINUTES = 30

# ---------- Retention ----------
# Events dated more than this many days ago are deleted, and their flyers with them (git history keeps both).
EVENT_RETENTION_DAYS = 60
# Records of analyzed posts are forgotten after this many days. Must exceed BACKFILL_DAYS and the lookback:
# older posts are never fetched again, so forgetting them can't cause a second analysis.
PROCESSED_RETENTION_DAYS = 45

BOGOTA_TZ = timezone(timedelta(hours=-5))  # Colombia has no daylight saving time


def require_env(name: str) -> str:
    """Return a required environment variable or stop with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing environment variable {name}. Set it in {ENV_FILE} or as a GitHub secret.")
    return value
