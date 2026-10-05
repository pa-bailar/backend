"""The shapes the admin tools accept: an Instagram username, a post link, a story's id, an event's id, an uploaded
screenshot's id. One source for links.py, inbox.py, stories.py and normalize.py.

admin-web/public/patterns.js mirrors them for the admin page and its Worker, which check a request before it
becomes an issue. tests/fixtures/patterns.json holds examples that both test suites (pytest and node --test) check
against their own patterns, so the two languages can't drift apart.

Plain strings, not compiled: each module anchors them as it needs (a whole value, or found in a text).
"""

# An Instagram username, without its "@": letters, digits, "." and "_", at most 30 (Instagram's limit).
HANDLE = r"[A-Za-z0-9._]{1,30}"

# The start of a post link, as people paste it: https://www.instagram.com/p/<code>/ (also /reel/, /reels/ or /tv/,
# sometimes with the account first: /<account>/p/<code>/; the scheme and "www." optional). Compiled with re.ASCII:
# \w is ASCII letters, digits and _, like JavaScript's.
POST_LINK = r"(?:https?://)?(?:www\.|m\.)?instagram\.com/(?:(?P<account>[\w.]+)/)?(?:p|reel|reels|tv)/(?P<code>[\w-]+)"

# A story published from screenshots: "story-" and 16 hex digits (stories.story_id).
STORY_ID = r"story-[0-9a-f]{16}"

# An event's id on the site (ids.py, the event's URL): lowercase words joined by hyphens, like the site's
# check-data.mjs.
EVENT_ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
EVENT_ID_MAX = 120

# A screenshot the admin page uploaded (admin-web/src/index.js): 32 hex digits.
UPLOAD_ID = r"[0-9a-f]{32}"
