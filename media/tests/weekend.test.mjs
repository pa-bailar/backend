// The weekend rule in JS (src/data/events.ts weekend(), tools/capture.mjs weekendClock()) against the table the Python
// tests read too (weekend-cases.json): node --test media/tests/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { capital, dateLabel, weekend } from "../src/data/events.ts";
import { weekendClock } from "../tools/capture.mjs";

const { cases } = JSON.parse(readFileSync(new URL("./weekend-cases.json", import.meta.url), "utf8"));

test("events.ts weekend() follows the shared rule", () => {
  for (const c of cases) assert.deepEqual(weekend(c.today), { from: c.from, to: c.to }, c.today);
});

test("capture.mjs weekendClock() is that weekend's Saturday at 19:00, or today on a Sunday", () => {
  for (const c of cases) assert.equal(weekendClock(c.today), `${c.clock}T19:00:00-05:00`, c.today);
});

test("events.ts capital() starts a label with a capital (the videos' cards and day words)", () => {
  assert.equal(capital(dateLabel("2026-10-10")), "Sábado 10 oct");
  assert.equal(capital("ñapa"), "Ñapa");
  assert.equal(capital(""), "");
});
