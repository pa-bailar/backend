"""Fetch public posts with the Instagram Graph API (Business Discovery)."""

from datetime import datetime

import requests

from . import config


def fetch_recent_posts(account: str) -> list[dict]:
    """Latest posts of a public Business/Creator account. Costs one API call."""
    fields = (
        f"business_discovery.username({account})"
        f"{{media.limit({config.POSTS_PER_ACCOUNT}){{id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
        f"children{{media_type,media_url,thumbnail_url}}}}}}"
    )
    response = requests.get(
        f"{config.GRAPH_API}/{config.IG_USER_ID}",
        params={"fields": fields, "access_token": config.META_TOKEN},
        timeout=30,
    )
    data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message"))
    return data["business_discovery"].get("media", {}).get("data", [])


def published_at(post: dict) -> datetime:
    return datetime.fromisoformat(post["timestamp"].replace("+0000", "+00:00"))


def image_urls(post: dict) -> list[str]:
    """The photo, every carousel slide, or the video's preview frame."""
    items = post.get("children", {}).get("data", []) or [post]
    urls = [i.get("media_url") if i.get("media_type") == "IMAGE" else i.get("thumbnail_url") for i in items]
    return [u for u in urls if u][: config.MAX_IMAGES_PER_POST]


def download(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content
