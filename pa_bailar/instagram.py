"""Fetch public posts with the Instagram Graph API (Business Discovery)."""

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

import requests

from . import config


class MediaItem(TypedDict, total=False):
    """A carousel slide (or the post itself when it has no slides)."""

    media_type: str
    media_url: str
    thumbnail_url: str


class Post(TypedDict):
    """One media object as returned by Business Discovery (the fields fetch_recent_posts asks for)."""

    id: str
    timestamp: str  # "2026-10-01T23:56:57+0000"
    permalink: str
    media_type: str  # IMAGE, CAROUSEL_ALBUM or VIDEO
    caption: NotRequired[str]
    media_url: NotRequired[str]
    thumbnail_url: NotRequired[str]
    children: NotRequired[dict[str, list[MediaItem]]]


class Profile(TypedDict, total=False):
    """An account's public profile (the fields fetch_profile asks for)."""

    username: str
    name: str
    biography: str
    website: str
    followers_count: int
    media_count: int
    media: dict[str, list[dict[str, str]]]  # {"data": [{"caption": ..., "timestamp": ...}]}


# Graph API error codes (https://developers.facebook.com/docs/graph-api/guides/error-handling).
_NOT_VISIBLE_CODES = {100, 110}  # Business Discovery can't see the account: personal, private or missing
_RATE_LIMIT_CODES = {4, 17, 32, 613, *range(80001, 80010)}  # app, user, page or business use case limits


class InstagramError(RuntimeError):
    """The Graph API returned an error (bad token, unknown or personal account, rate limit...)."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


# What Meta's usage headers measure, each as a share (0-100) of what the app may use: calls, CPU time, total time.
USAGE_MEASURES = ("call_count", "total_cputime", "total_time")
# Meta's two usage headers, by the names the run's records give them.
APP_HEADER = "X-App-Usage"
BUSINESS_HEADER = "X-Business-Use-Case-Usage"


def _measures(readings: list[dict[str, Any]]) -> dict[str, int]:
    detail: dict[str, int] = {}
    for reading in readings:
        for key in USAGE_MEASURES:
            if key in reading:
                detail[key] = max(detail.get(key, 0), int(reading[key]))
    return detail


def usage_by_header(app_header: str | None, business_header: str | None) -> dict[str, dict[str, int]]:
    """Each header's measures (its highest share used, in percent, per measure), apart: Meta has used each, and a
    run's cost per read is only measured within one of them. A header that's missing or odd is left out:
    - X-App-Usage: {"call_count": 28, "total_time": 25, "total_cputime": 25} (Business Discovery's on 8 Oct 2026);
    - X-Business-Use-Case-Usage: {"<id>": [{"type": "instagram", "call_count": 1, "total_cputime": 1, "total_time": 1,
      "estimated_time_to_regain_access": 0}]} (what Meta used on 3 Oct 2026)."""
    usage: dict[str, dict[str, int]] = {}
    for name, header in ((APP_HEADER, app_header), (BUSINESS_HEADER, business_header)):
        if not header:
            continue
        try:
            parsed = json.loads(header)
            readings = [parsed] if name == APP_HEADER else [entry for entries in parsed.values() for entry in entries]
            if detail := _measures(readings):
                usage[name] = detail
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
    return usage


def usage_measures(app_header: str | None, business_header: str | None) -> dict[str, int]:
    """Each measure's highest share used, in percent, of what both headers report (usage_by_header); empty for no
    header or odd ones."""
    return _measures(list(usage_by_header(app_header, business_header).values()))


@dataclass(frozen=True)
class CallReading:
    """One Graph API call: how long Meta took to answer (seconds, the request's whole round trip) and the usage its
    answer reported, per header (usage_by_header; empty when it reported none)."""

    seconds: float
    usage: dict[str, dict[str, int]]

    @property
    def header(self) -> str | None:
        """The header with the highest share: the one the sweep's stop reads."""
        return max(self.usage, key=lambda name: max(self.usage[name].values()), default=None)

    @property
    def percent(self) -> int | None:
        """The highest share used of any measure in any header; None when the answer reported none."""
        return max(self.usage[self.header].values()) if self.header else None


class InstagramClient:
    def __init__(self, access_token: str, ig_user_id: str):
        self._access_token = access_token
        self._ig_user_id = ig_user_id
        # Share of the app's Graph API quota already used (0-100), from Meta's usage headers (_read_usage): the
        # highest of its measures ("call_count", "total_cputime", "total_time").
        self.app_usage_percent = 0
        # The highest reading so far (a run's peak), and each of its measures: which one Meta's limit binds on.
        self.peak_usage_percent = 0
        self.peak_usage_detail: dict[str, int] = {}
        # The latest call that got an answer: Meta's time and the usage after it, per header (the sweep's
        # per-read record and its forecast of the next read's cost: instagram_usage.py).
        self.last_call: CallReading | None = None

    def _get(self, fields: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = requests.get(
                f"{config.GRAPH_API_URL}/{self._ig_user_id}",
                params={"fields": fields, "access_token": self._access_token},
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            data: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as error:
            # Network failure or a non-JSON answer (e.g. an HTML 5xx page): one account fails, not the run.
            # The token is in the URL, and connection errors quote the URL: never let it reach logs or answers.
            raise InstagramError(f"request failed: {redact(str(error))}") from error
        app_header = response.headers.get("x-app-usage")
        business_header = response.headers.get("x-business-use-case-usage")
        self.last_call = CallReading(time.monotonic() - started, usage_by_header(app_header, business_header))
        self._read_usage(app_header, business_header)
        if "error" in data:
            payload = data["error"]
            raise InstagramError(payload.get("message", "unknown error"), code=payload.get("code"))
        return data

    @classmethod
    def from_env(cls) -> "InstagramClient":
        """The client for our own Instagram account, from META_ACCESS_TOKEN and IG_USER_ID."""
        return cls(config.require_env("META_ACCESS_TOKEN"), config.require_env("IG_USER_ID"))

    def _business_discovery(self, fields: str) -> dict[str, Any]:
        """Business Discovery's answer for one account; an answer without it is an error, not a crash."""
        answer = self._get(fields).get("business_discovery")
        if not isinstance(answer, dict):
            raise InstagramError("the answer has no business_discovery data")
        return answer

    def _read_usage(self, app_header: str | None, business_header: str | None) -> None:
        """The highest share used, in percent, of what Meta reports (usage_measures), and the run's peak so far. No
        header (or an odd one) keeps the last value: it never stops the sweep."""
        detail = usage_measures(app_header, business_header)
        if not detail:
            return
        self.app_usage_percent = max(detail.values())
        if self.app_usage_percent >= self.peak_usage_percent:
            self.peak_usage_percent, self.peak_usage_detail = self.app_usage_percent, detail

    def check_token(self) -> str:
        """Cheap call that fails fast if the token is invalid. Returns our own username."""
        return str(self._get("username")["username"])

    def fetch_recent_posts(self, account: str, limit: int = config.POSTS_PER_ACCOUNT) -> list[Post]:
        """The latest `limit` posts of a public Business/Creator account. Costs one API call."""
        media_fields = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
        child_fields = "media_type,media_url,thumbnail_url"
        fields = (
            f"business_discovery.username({account})"
            f"{{media.limit({limit}){{{media_fields},children{{{child_fields}}}}}}}"
        )
        return cast(list[Post], self._business_discovery(fields).get("media", {}).get("data", []))

    def fetch_profile(self, account: str, recent_posts: int = 5) -> Profile:
        """Public profile and latest captions of a Business/Creator account. Costs one API call.

        Raises InstagramError for personal, private or missing accounts (Business Discovery can't see them).
        """
        fields = (
            f"business_discovery.username({account})"
            f"{{username,name,biography,website,followers_count,media_count,"
            f"media.limit({recent_posts}){{caption,timestamp}}}}"
        )
        return cast(Profile, self._business_discovery(fields))


def redact(text: str) -> str:
    """Text without access tokens or the app's secret (error messages that quote a Graph API URL)."""
    return re.sub(r"((?:access_token|client_secret|fb_exchange_token|input_token)=)[^&\s'\"]+", r"\1***", text)


def is_rate_limited(error: InstagramError) -> bool:
    """True when Meta is throttling the app or user: stop and try again later (nothing is wrong with the account)."""
    return error.code in _RATE_LIMIT_CODES


def is_not_visible(error: InstagramError) -> bool:
    """True when Business Discovery can't see the account: personal, private or missing."""
    return error.code in _NOT_VISIBLE_CODES


def published_at(post: Post) -> datetime:
    return datetime.fromisoformat(post["timestamp"].replace("+0000", "+00:00"))


def api_timestamp(moment: datetime) -> str:
    """A moment written as the API writes a post's `timestamp` ("2026-10-04T23:30:00+0000"; published_at reads it),
    for the posts and stories that don't come from the API."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _image_url(item: MediaItem) -> str | None:
    return item.get("media_url") if item.get("media_type") == "IMAGE" else item.get("thumbnail_url")


def analyzed_items(post: Post) -> list[MediaItem]:
    """The slides whose images are analyzed (image_urls), in the same order: a flyer's index points here."""
    items: list[MediaItem] = post.get("children", {}).get("data", []) or [cast(MediaItem, post)]
    return [item for item in items if _image_url(item)][: config.MAX_IMAGES_PER_POST]


def image_urls(post: Post) -> list[str]:
    """Images to analyze: the photo, every carousel slide, or a video's preview frame."""
    return [cast(str, _image_url(item)) for item in analyzed_items(post)]


def video_url(post: Post, image_index: int) -> str | None:
    """The video behind the image at `image_index` (a reel, or a carousel's video slide); None for photos, and
    for videos whose file Instagram doesn't give (e.g. with licensed music)."""
    items = analyzed_items(post)
    if not 0 <= image_index < len(items) or items[image_index].get("media_type") != "VIDEO":
        return None
    return items[image_index].get("media_url")


def slide_count(post: Post) -> int | None:
    """How many slides a carousel has; None for a single photo or video."""
    children = post.get("children", {}).get("data", [])
    return len(children) if post["media_type"] == "CAROUSEL_ALBUM" and children else None


def download_image(url: str) -> bytes:
    response = requests.get(url, timeout=config.HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content
