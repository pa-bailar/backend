// tools/paths.mjs: node --test media/tests/
import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { bundleDir, MEDIA, mediaHome, OUT } from "../tools/paths.mjs";

test("a relative PA_BAILAR_MEDIA_HOME is relative to the backend's root, as in tools/common.py", () => {
  assert.equal(mediaHome(undefined), "D:\\AI\\pa-bailar-media");
  assert.equal(mediaHome("../media-home"), path.resolve(MEDIA, "..", "..", "media-home"));
  assert.equal(mediaHome(MEDIA), MEDIA); // an absolute path stays as it is
});

test("each checkout has its own stills bundle in the shared home", () => {
  const here = bundleDir();
  assert.equal(path.dirname(here), OUT);
  assert.match(path.basename(here), /^\.bundle-[0-9a-f]{8}$/);
  assert.equal(bundleDir(MEDIA), here);
  assert.equal(bundleDir(MEDIA.toUpperCase()), here); // Windows paths ignore case
  assert.notEqual(bundleDir(path.join(MEDIA, "..", "..", "other-worktree", "media")), here);
});
