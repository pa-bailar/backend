"""Fetch public posts with the Instagram Graph API (Business Discovery)."""

from datetime import datetime
from typing import Any

import requests

from . import config

Post = dict[str, Any]  # one media object as returned by the Graph API


class InstagramError(RuntimeError):
    """The Graph API returned an error (bad token, unknown or personal account, rate limit...)."""


class InstagramClient:
    def __init__(self, access_token: str, ig_user_id: str):
        self._access_token = access_token
        self._ig_user_id = ig_user_id

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
        if "error" in data:
            raise InstagramError(data["error"].get("message", "unknown error"))
        return data

    def check_token(self) -> str:
        """Cheap call that fails fast if the token is invalid. Returns our own username."""
        return self._get("username")["username"]

    def fetch_recent_posts(self, account: str) -> list[Post]:
        """Latest posts of a public Business/Creator account. Costs one API call."""
        media_fields = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
        child_fields = "media_type,media_url,thumbnail_url"
        fields = (
            f"business_discovery.username({account})"
            f"{{media.limit({config.POSTS_PER_ACCOUNT}){{{media_fields},children{{{child_fields}}}}}}}"
        )
        return self._get(fields)["business_discovery"].get("media", {}).get("data", [])


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
