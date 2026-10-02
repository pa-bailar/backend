"""Fetch public posts with the Instagram Graph API (Business Discovery)."""

import json
from datetime import datetime
from typing import Any

import requests

from . import config

Post = dict[str, Any]  # one media object as returned by the Graph API


# Graph API error codes (https://developers.facebook.com/docs/graph-api/guides/error-handling).
_NOT_VISIBLE_CODES = {100, 110}  # Business Discovery can't see the account: personal, private or missing
_RATE_LIMIT_CODES = {4, 17, 32, 613, *range(80001, 80010)}  # app, user, page or business use case limits


class InstagramError(RuntimeError):
    """The Graph API returned an error (bad token, unknown or personal account, rate limit...)."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class InstagramClient:
    def __init__(self, access_token: str, ig_user_id: str):
        self._access_token = access_token
        self._ig_user_id = ig_user_id
        # Share of the app's hourly Graph API quota already used (0-100), from Meta's X-App-Usage header.
        self.app_usage_percent = 0

    def _get(self, fields: str) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{config.GRAPH_API_URL}/{self._ig_user_id}",
                params={"fields": fields, "access_token": self._access_token},
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            # Network failure or a non-JSON answer (e.g. an HTML 5xx page): one account fails, not the run.
            raise InstagramError(f"request failed: {error}") from error
        self._read_usage(response.headers.get("x-app-usage"))
        if "error" in data:
            error = data["error"]
            raise InstagramError(error.get("message", "unknown error"), code=error.get("code"))
        return data

    def _read_usage(self, header: str | None) -> None:
        """X-App-Usage: {"call_count": 28, "total_time": 25, "total_cputime": 25}, percents of the hourly quota."""
        try:
            usage = json.loads(header) if header else {}
            self.app_usage_percent = max(int(value) for value in usage.values()) if usage else 0
        except (ValueError, TypeError, AttributeError):
            pass  # an odd header never stops the sweep

    def check_token(self) -> str:
        """Cheap call that fails fast if the token is invalid. Returns our own username."""
        return self._get("username")["username"]

    def fetch_recent_posts(self, account: str, limit: int = config.POSTS_PER_ACCOUNT) -> list[Post]:
        """The latest `limit` posts of a public Business/Creator account. Costs one API call."""
        media_fields = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
        child_fields = "media_type,media_url,thumbnail_url"
        fields = (
            f"business_discovery.username({account})"
            f"{{media.limit({limit}){{{media_fields},children{{{child_fields}}}}}}}"
        )
        return self._get(fields)["business_discovery"].get("media", {}).get("data", [])

    def fetch_profile(self, account: str, recent_posts: int = 5) -> dict[str, Any]:
        """Public profile and latest captions of a Business/Creator account. Costs one API call.

        Raises InstagramError for personal, private or missing accounts (Business Discovery can't see them).
        """
        fields = (
            f"business_discovery.username({account})"
            f"{{username,name,biography,website,followers_count,media_count,"
            f"media.limit({recent_posts}){{caption,timestamp}}}}"
        )
        return self._get(fields)["business_discovery"]


def is_rate_limited(error: InstagramError) -> bool:
    """True when Meta is throttling the app or user: stop and try again later (nothing is wrong with the account)."""
    return error.code in _RATE_LIMIT_CODES


def is_not_visible(error: InstagramError) -> bool:
    """True when Business Discovery can't see the account: personal, private or missing."""
    return error.code in _NOT_VISIBLE_CODES


def published_at(post: Post) -> datetime:
    return datetime.fromisoformat(post["timestamp"].replace("+0000", "+00:00"))


def image_urls(post: Post) -> list[str]:
    """Images to analyze: the photo, every carousel slide, or a video's preview frame."""
    items = post.get("children", {}).get("data", []) or [post]
    urls = [item.get("media_url") if item.get("media_type") == "IMAGE" else item.get("thumbnail_url") for item in items]
    return [url for url in urls if url][: config.MAX_IMAGES_PER_POST]


def download_image(url: str) -> bytes:
    response = requests.get(url, timeout=config.HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content
