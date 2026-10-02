"""Paths, settings and secrets for the backend.

Secrets come from environment variables: from backend/.env locally, from GitHub Actions secrets on CI.
"""

import os
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
FLYERS_DIR = DATA_DIR / "flyers"
# Backend-only input and state.
ACCOUNTS_FILE = BACKEND_DIR / "accounts.txt"
PROCESSED_POSTS_FILE = BACKEND_DIR / "state" / "processed_posts.json"

# ---------- Instagram (Meta Graph API) ----------
GRAPH_API_URL = "https://graph.facebook.com/v26.0"
POSTS_PER_ACCOUNT = 10  # one API call per account regardless of this number
MAX_IMAGES_PER_POST = 4
HTTP_TIMEOUT_SECONDS = 30

# ---------- Gemini ----------
# Tried in order: if a model is busy, out of quota or unavailable, the next one is used.
GEMINI_MODELS = list(
    dict.fromkeys(  # GEMINI_MODEL (optional) goes first; duplicates are dropped
        [os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), "gemini-3.5-flash", "gemini-flash-lite-latest"]
    )
)
SECONDS_BETWEEN_GEMINI_CALLS = 6  # stay under the free tier's requests-per-minute limit

# ---------- Flyers ----------
FLYER_MAX_SIZE = (1080, 1350)  # 4:5, Instagram's tallest feed ratio
FLYER_WEBP_QUALITY = 80

# ---------- Pipeline ----------
DEFAULT_LOOKBACK_DAYS = 7
BOGOTA_TZ = timezone(timedelta(hours=-5))  # Colombia has no daylight saving time


def require_env(name: str) -> str:
    """Return a required environment variable or stop with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing environment variable {name}. Set it in {ENV_FILE} or as a GitHub secret.")
    return value
