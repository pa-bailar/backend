// The one word normalizer and the one time parser of the Node side (the timing helpers, the captions, stills.mjs).
// tools/common.py has their Python twins (_norm, at_seconds); tests/timing-cases.json holds the cases both must pass.
// No imports: Node runs this file as it is (tests, tools/stills.mjs).

/** A word as the voice's timing compares it: no accents (any combining mark), no punctuation, lower case. */
export const plain = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z']/g, "");

type Lines = { lines: { id: string; start: number; words: { word: string; start: number }[] }[] } | null | undefined;

/**
 * A moment in seconds: seconds ("8.5" or "8.5s"), a frame ("f255"), a line's start ("c4") or a word's start
 * ("c4:link", the nth with "c4:link:1"), from a video's data/timing.json. Throws on a line or word it can't find.
 */
export function secondsAt(spec: string, timing: Lines, fps = 30): number {
  const s = spec.trim();
  if (/^f\d+$/.test(s)) return Number(s.slice(1)) / fps;
  if (/^\d+(\.\d+)?s?$/.test(s)) return Number(s.replace(/s$/, ""));
  const [id, word, nth = "0"] = s.split(":");
  const line = timing?.lines.find((l) => l.id === id);
  if (!line) throw new Error(`no line "${id}" in timing.json (times are seconds, f<frame>, <line> or <line>:<word>)`);
  if (!word) return line.start;
  const hit = line.words.filter((w) => plain(w.word) === plain(word))[Number(nth)];
  if (!hit) throw new Error(`no word "${word}" (#${nth}) in ${id}`);
  return hit.start;
}
