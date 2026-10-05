// The shapes the admin tools accept, for the page (app.js) and its Worker (src/index.js, which imports this file
// and bundles it): the same rules as pa_bailar/patterns.py, which reads the requests. tests/fixtures/patterns.json
// holds examples that both test suites check (admin-web/test/patterns.test.mjs here, tests/test_patterns.py
// there), so the two languages can't drift apart. Served as a static file too, for the page: it holds no data.

const HANDLE = String.raw`[A-Za-z0-9._]{1,30}`;
const POST = String.raw`https?:\/\/(?:www\.|m\.)?instagram\.com\/(?:[\w.]+\/)?(?:p|reel|reels|tv)\/[\w-]+\/?`;
const STORY = String.raw`story-[a-f0-9]{16}`;

/** An Instagram username, tested without its "@". */
export const ACCOUNT = new RegExp(`^${HANDLE}$`);

/**
 * The whole value is one post link (a slash, a query like ?igsh=… and a #fragment allowed, no spaces or new lines):
 * it goes into the issue's body, which the inbox reads line by line.
 */
export const POST_LINK = new RegExp(String.raw`^${POST}(?:\?[^\s#]*)?(?:#\S*)?$`, "i");

/** The first post link in a shared text, without what follows it (Instagram's tracking, ?igsh=…). */
export const POST_LINK_IN_TEXT = new RegExp(POST, "i");

/** A story's link in a shared text: its account is the first group. */
export const STORY_LINK_IN_TEXT = new RegExp(String.raw`https?:\/\/(?:www\.|m\.)?instagram\.com\/stories\/(${HANDLE})\/`, "i");

/** A story published from screenshots (pa_bailar/stories.py). */
export const STORY_ID = new RegExp(`^${STORY}$`);

/** "/ocultar story-…" in the answer to a story (how to undo it): the story's id is the first group. */
export const HIDE_STORY_COMMAND = new RegExp(String.raw`\/ocultar (${STORY})`);

/** An event's id on the site (pa_bailar/ids.py): lowercase words joined by hyphens, at most EVENT_ID_MAX long. */
export const EVENT_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const EVENT_ID_MAX = 120;

/** A screenshot the page uploaded (/api/uploads). */
export const UPLOAD_ID = /^[a-f0-9]{32}$/;
