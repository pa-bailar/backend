"""A public post read from its embed page: the fallback when Instagram's API can't give it to us.

Every public post has an embed version (instagram.com/p/<code>/embed/captioned/), the card websites use to show
a post. It needs no login and holds the post's author, caption and image (and, usually, structured data with
its videos and carousel slides). The API can't read posts of personal or private accounts, nor list a
collaboration under its co-author, so for a post we have the link of (pasted in the admin tools), this is how
we still read it.

  - Requests go out as a browser would (curl_cffi impersonating Chrome): Instagram answers plain scripts,
    including GitHub's runners, with an empty page.
  - Logged out, one page per post: public data only (Meta v. Bright Data, 2024). It can't list an account's
    posts: that needs a login, which we don't use.
  - The page has no publication time: "now" stands in (it only helps Gemini date "este sábado").
"""

import html
import json
import re
from datetime import UTC, datetime
from typing import Any, cast

from curl_cffi import requests

from . import config, links
from .instagram import MediaItem, Post, api_timestamp

ID_PREFIX = "public-"  # a post read here: the API knows it by another id (pipeline/base.py matches them by link)

EMBED_URL = "https://www.instagram.com/p/{code}/embed/captioned/"
_CONTEXT = re.compile(r'"contextJSON":"((?:[^"\\]|\\.)*)"')
_AUTHOR = re.compile(r'class="UsernameText">([^<]+)<')
_CAPTION = re.compile(r'<div class="Caption">(.*?)<div class="CaptionComments">', re.DOTALL)
_IMAGE = re.compile(r'class="EmbeddedMediaImage"[^>]*?src="([^"]+)"')
_VIDEO_TYPES = {"GraphVideo": "VIDEO", "GraphSidecar": "CAROUSEL_ALBUM", "GraphImage": "IMAGE"}


class PublicPostError(Exception):
    """The embed page couldn't be read (deleted, private, not answering): the message says why, in Spanish."""


def fetch_public_post(code: str) -> tuple[str, Post]:
    """(the author's username, the post in the API's shape) for the post with this code."""
    try:
        response = requests.get(EMBED_URL.format(code=code), impersonate="chrome", timeout=config.HTTP_TIMEOUT_SECONDS)
    except requests.RequestsError as error:
        raise PublicPostError(f"no se pudo abrir su página pública ({error})") from error
    if response.status_code != 200:
        raise PublicPostError(f"su página pública respondió {response.status_code}")
    return parse_embed(code, response.text)


def parse_embed(code: str, page: str) -> tuple[str, Post]:
    """The post in an embed page: from its structured data when it has it, else from the page itself."""
    parsed = _from_structured_data(code, page) or _from_page(code, page)
    if parsed is None:
        raise PublicPostError("su página pública no muestra la publicación (¿privada o borrada?)")
    # The author becomes an account (its posts, accounts.txt): only a valid username gets that far.
    author = links.account_name(parsed[0])
    if author is None:
        raise PublicPostError("su página pública no dice bien quién la publicó")
    return author, parsed[1]


def _post(code: str, post_id: str, media_type: str, caption: str, taken_at: int | None = None, **media: Any) -> Post:
    """In the API's shape. `taken_at`: when it was published (Unix time); unknown, now (the page's HTML
    doesn't say), so it counts as the newest post of its event."""
    moment = datetime.fromtimestamp(taken_at, UTC) if taken_at else datetime.now(UTC)
    return cast(
        Post,
        {
            "id": f"{ID_PREFIX}{post_id}",
            "media_type": media_type,
            "permalink": f"https://www.instagram.com/p/{code}/",
            "timestamp": api_timestamp(moment),
            "caption": caption,
            **media,
        },
    )


def _item(node: dict[str, Any]) -> MediaItem:
    """A slide (or the post itself) in the API's shape: a video's file and frame, or a photo."""
    if node.get("is_video"):
        return cast(
            MediaItem,
            {"media_type": "VIDEO", "media_url": node.get("video_url"), "thumbnail_url": node.get("display_url")},
        )
    return cast(MediaItem, {"media_type": "IMAGE", "media_url": node.get("display_url")})


def _from_structured_data(code: str, page: str) -> tuple[str, Post] | None:
    match = _CONTEXT.search(page)
    if not match:
        return None
    try:
        context = json.loads(json.loads(f'"{match.group(1)}"'))
    except ValueError:
        return None
    media = (context.get("gql_data") or {}).get("shortcode_media") or {}
    author = (media.get("owner") or {}).get("username")
    # The id names its flyer and clip files: digits only.
    if not author or not str(media.get("id", "")).isdigit():
        return None
    taken_at = media.get("taken_at_timestamp") if isinstance(media.get("taken_at_timestamp"), int) else None
    edges = (media.get("edge_media_to_caption") or {}).get("edges") or [{}]
    caption = edges[0].get("node", {}).get("text", "")
    media_type = _VIDEO_TYPES.get(media.get("__typename", ""), "IMAGE")
    if media_type == "CAROUSEL_ALBUM":
        children = [_item(edge["node"]) for edge in (media.get("edge_sidecar_to_children") or {}).get("edges", [])]
        return author, _post(code, media["id"], media_type, caption, taken_at, children={"data": children})
    files = {key: value for key, value in _item(media).items() if key != "media_type"}
    return author, _post(code, media["id"], media_type, caption, taken_at, **files)


def _from_page(code: str, page: str) -> tuple[str, Post] | None:
    author = _AUTHOR.search(page)
    image = _IMAGE.search(page)
    if not author or not image:
        return None
    caption = ""
    if match := _CAPTION.search(page):
        text = re.sub(r"<br\s*/?>", "\n", match.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        caption = text.removeprefix(author.group(1)).strip()  # the caption starts with the author's name
    return author.group(1), _post(code, code, "IMAGE", caption, media_url=html.unescape(image.group(1)))
