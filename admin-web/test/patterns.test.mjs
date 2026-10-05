// The shapes the admin page and its Worker accept (public/patterns.js) against the examples the backend's tests
// check too (tests/fixtures/patterns.json, tests/test_patterns.py): the two languages can't drift apart.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  ACCOUNT,
  EVENT_ID,
  EVENT_ID_MAX,
  HIDE_STORY_COMMAND,
  POST_LINK,
  POST_LINK_IN_TEXT,
  STORY_ID,
  STORY_LINK_IN_TEXT,
  UPLOAD_ID,
} from "../public/patterns.js";

const EXAMPLES = JSON.parse(readFileSync(new URL("../../tests/fixtures/patterns.json", import.meta.url), "utf8"));

const ACCEPTS = {
  account: (text) => ACCOUNT.test(text),
  post_link: (text) => POST_LINK.test(text),
  story_id: (text) => STORY_ID.test(text),
  event_id: (text) => EVENT_ID.test(text) && text.length <= EVENT_ID_MAX,
  upload_id: (text) => UPLOAD_ID.test(text),
};

for (const [kind, accepts] of Object.entries(ACCEPTS)) {
  describe(`the ${kind} shape, as the backend's`, () => {
    it("accepts the good examples", () => {
      for (const text of EXAMPLES[kind].good) assert.ok(accepts(text), text);
    });
    it("refuses the bad ones", () => {
      for (const text of EXAMPLES[kind].bad) assert.ok(!accepts(text), text);
    });
    it("asks for the link alone where only the inbox is lenient", () => {
      for (const text of EXAMPLES[kind].python_only ?? []) assert.ok(!accepts(text), text);
    });
  });
}

describe("finding links in shared text", () => {
  it("takes a post's link without Instagram's tracking", () => {
    const text = "Mira esto https://www.instagram.com/p/Dd5JAAxjhg5/?igsh=MWZ4b2E5 en Instagram";
    assert.equal(text.match(POST_LINK_IN_TEXT)?.[0], "https://www.instagram.com/p/Dd5JAAxjhg5/");
  });
  it("takes a story link's account", () => {
    const text = "https://www.instagram.com/stories/salsa.club/3456789012?utm_source=ig_story_item_share";
    assert.equal(text.match(STORY_LINK_IN_TEXT)?.[1], "salsa.club");
  });
  it("finds how to hide a story in its answer", () => {
    assert.equal("Ocultar: `/ocultar story-0123456789abcdef`".match(HIDE_STORY_COMMAND)?.[1], "story-0123456789abcdef");
  });
});
