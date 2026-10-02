"""Paths and settings shared by the backend."""

import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

# Output read by the website (public)
DATA_DIR = PROJECT_DIR / "data"
EVENTS_FILE = DATA_DIR / "events.json"
FLYERS_DIR = DATA_DIR / "flyers"

# Backend-only state
ACCOUNTS_FILE = BACKEND_DIR / "accounts.txt"
PROCESSED_FILE = BACKEND_DIR / "state" / "processed_posts.json"

# Instagram (Meta Graph API)
GRAPH_API = "https://graph.facebook.com/v26.0"
META_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
POSTS_PER_ACCOUNT = 10  # one API call per account no matter the number
MAX_IMAGES_PER_POST = 4

# Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = [os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), "gemini-3.5-flash", "gemini-flash-lite-latest"]
SECONDS_BETWEEN_GEMINI_CALLS = 6  # stay under the free tier's requests-per-minute limit

DEFAULT_LOOKBACK_DAYS = 7
BOGOTA = timezone(timedelta(hours=-5))
