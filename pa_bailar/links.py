"""Instagram post links, as people paste them, and links to the site's events.

A post link is https://www.instagram.com/p/<code>/ (also /reel/ or /tv/, sometimes with the account first:
/<account>/p/<code>/, and often with "?igsh=…" from the share button). The code identifies the post; the
account is only in the link sometimes, which matters because Instagram's API can only list an account's posts.
"""

import re

from . import config

_POST = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?instagram\.com/(?:(?P<account>[\w.]+)/)?(?:p|reel|reels|tv)/(?P<code>[\w-]+)",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(r"^@?([A-Za-z0-9._]{1,30})$")
_PROFILE = re.compile(r"^(?:https?://)?(?:www\.|m\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?(?:\?.*)?$", re.IGNORECASE)


def post_code(url: str) -> str | None:
    """ "https://www.instagram.com/p/Dd5JAAxjhg5/?igsh=x" → "Dd5JAAxjhg5"; None if it isn't a post link."""
    match = _POST.match(url.strip())
    return match.group("code") if match else None


def account_in_link(url: str) -> str | None:
    """The account when the link names it (instagram.com/<account>/p/<code>/), else None."""
    match = _POST.match(url.strip())
    return match.group("account").lower() if match and match.group("account") else None


def account_name(text: str) -> str | None:
    """ "@academia", "academia" or a profile link → "academia"; None if it isn't a valid username."""
    text = text.strip()
    match = _ACCOUNT.match(text) or _PROFILE.match(text)
    return match.group(1).lower().rstrip(".") if match else None


def same_post(permalink: str, code: str) -> bool:
    return post_code(permalink) == code


def event_url(event_id: str) -> str:
    return f"{config.SITE_URL}/evento/{event_id}/"
