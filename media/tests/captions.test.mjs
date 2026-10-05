// The captions' pages (src/lib/captions.ts) from a real timing.json (teaser v2's) and small made-up ones:
// node --test media/tests/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { captionPages, captionsOn, currentToken, pageAt, splitPhrase, toCaptions } from "../src/lib/captions.ts";

const teaser = JSON.parse(readFileSync(new URL("../projects/teaser-v2/data/timing.json", import.meta.url), "utf8"));
const words = (...list) => list.map(([word, start, end]) => ({ word, start, end }));
const timing = (lines) => ({ duration: 10, lead: 0, lines });

test("pages break at punctuation, at each line's end and before passing maxChars", () => {
  const t = timing([
    { id: "a", text: "", start: 0, end: 2, words: words(["Hola,", 0, 0.3], ["¿qué", 0.35, 0.6], ["tal?", 0.62, 0.9]) },
    { id: "b", text: "", start: 1, end: 3, words: words(["uno", 1.0, 1.2], ["dos", 1.25, 1.4], ["tres", 1.45, 1.6]) },
  ]);
  const pages = captionPages(t, { style: "minimal", maxChars: 9 });
  assert.deepEqual(
    pages.map((p) => p.text),
    ["Hola,", "¿qué tal?", "uno", "dos tres"],
  );
  assert.equal(toCaptions(t, {})[1].text, " ¿qué");
});

test("a phrase too long for a page splits without a lone short word at the end", () => {
  assert.deepEqual(splitPhrase(["cuánto", "vale", "y", "cómo", "llegar."], 24), [3, 2]);
  assert.deepEqual(splitPhrase(["¿Quieres", "salir", "a", "bailar", "este", "finde…"], 24), [4, 2]);
  assert.deepEqual(splitPhrase(["registrarse,"], 5), [1]);
});

test("a page ends a hold after its last word, or when the next one starts", () => {
  const t = timing([
    { id: "a", text: "", start: 0, end: 1, words: words(["Uno.", 0, 0.5]) },
    { id: "b", text: "", start: 3, end: 4, words: words(["Dos.", 3, 3.5]) },
    { id: "c", text: "", start: 3, end: 4, words: words(["Tres.", 3.6, 4]) },
  ]);
  const pages = captionPages(t, { style: "minimal" });
  assert.deepEqual(
    pages.map((p) => [p.startMs, p.endMs]),
    [
      [0, 950],
      [3000, 3600],
      [3600, 4450],
    ],
  );
  assert.equal(pageAt(pages, 2000), null);
  assert.equal(pageAt(pages, 2950).text, "Dos.");
});

test("minimal emphasizes the chosen words; kinetic marks the word being said", () => {
  const t = timing([
    { id: "a", text: "", start: 0, end: 2, words: words(["salir", 0, 0.3], ["a", 0.3, 0.4], ["Bailar.", 0.4, 0.9]) },
  ]);
  const [minimal] = captionPages(t, { style: "minimal", emphasis: ["bailar"] });
  assert.deepEqual(
    minimal.tokens.map((x) => x.emphasis),
    [false, false, true],
  );
  const [kinetic] = captionPages(t, { style: "kinetic", emphasis: ["bailar"] });
  assert.ok(kinetic.tokens.every((x) => !x.emphasis));
  assert.equal(currentToken(kinetic, 350), 1);
  assert.equal(currentToken(kinetic, -10), -1);
});

test("the teaser's voice makes short pages, only for the lines and deliverables asked", () => {
  const pages = captionPages(teaser, { style: "minimal" });
  assert.ok(pages.length >= 10);
  for (const p of pages) assert.ok(p.text.length <= 24 || !p.text.includes(" "), p.text);
  for (let i = 1; i < pages.length; i++) assert.ok(pages[i].startMs >= pages[i - 1].endMs, pages[i].text);
  const only = captionPages(teaser, { style: "minimal", lines: ["c3"] });
  assert.deepEqual(
    only.map((p) => p.text),
    ["No hay que registrarse,", "es gratis."],
  );
  assert.equal(captionsOn(undefined, "teaser-v2-reel"), false);
  assert.equal(captionsOn({ style: "minimal" }, "teaser-v2-reel"), true);
  assert.equal(captionsOn({ style: "minimal", deliverables: ["reel"] }, "teaser-v2-with-music"), false);
  assert.equal(captionsOn({ style: "minimal", deliverables: ["reel"] }, "teaser-v2-reel"), true);
});
