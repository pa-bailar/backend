// src/lib/words.ts against the table tools/common.py passes too (tests/timing-cases.json): node --test media/tests/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { plain, secondsAt } from "../src/lib/words.ts";
import { frameAt } from "../tools/stills.mjs";

const cases = JSON.parse(readFileSync(new URL("./timing-cases.json", import.meta.url), "utf8"));

test("plain() normalizes words as common.py _norm does", () => {
  for (const [word, expected] of cases.words) assert.equal(plain(word), expected, word);
});

test("secondsAt() and stills.mjs frameAt() read moments as common.py at_seconds does", () => {
  for (const [spec, seconds] of cases.times) {
    assert.ok(Math.abs(secondsAt(spec, cases.timing, cases.fps) - seconds) < 1e-9, spec);
    assert.equal(frameAt(spec, cases.fps, cases.timing), Math.round(seconds * cases.fps), spec);
  }
  for (const spec of cases.errors) assert.throws(() => secondsAt(spec, cases.timing, cases.fps), spec);
});
