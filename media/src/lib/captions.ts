// Captions from the voice's word timings (data/timing.json, from faster-whisper): our words become
// @remotion/captions' `Caption`s, and its createTikTokStyleCaptions() groups them into pages (a phrase each). Pure
// logic, no React: tests/captions.test.mjs runs it in Node. The component that draws them is src/brand/captions.tsx.
import { type Caption, createTikTokStyleCaptions } from "@remotion/captions";
import type { TimingJson } from "./timing";
import { plain } from "./words.ts";

/** "minimal": a phrase at a time, chosen words emphasized. "kinetic": the phrase, with the word being said marked. */
export type CaptionStyle = "minimal" | "kinetic";

/** video.json's "captions" (absent: no captions, the default). */
export type CaptionsSettings = {
  style: CaptionStyle;
  /** The voice lines to caption (ids); default all. Skip a line the picture already writes out. */
  lines?: string[];
  /** Words to emphasize in "minimal" (accents, case and punctuation ignored). */
  emphasis?: string[];
  /** The deliverables (video.json "renders" keys) that show captions; default all. */
  deliverables?: string[];
  /** Characters per page before it breaks (default 24: one line at the default size). */
  maxChars?: number;
  /** "low" (default): above the safe zone's bottom; "high": right under the top of the safe zone. */
  place?: "low" | "high";
};

export type CaptionToken = { text: string; fromMs: number; toMs: number; emphasis: boolean };
export type CaptionPage = { text: string; startMs: number; endMs: number; tokens: CaptionToken[] };

/** A pause in the voice longer than this starts a new page. */
const SILENCE_MS = 300;
/** A page stays this long after its last word ends (unless the next page comes first). */
const HOLD_MS = 450;
/** Punctuation that ends a phrase: a page breaks after it. */
const PHRASE_END = /[.,;:!?…]["»”']?$/;

/**
 * Our timing.json words → @remotion/captions `Caption`s (ms; every word after the first starts with a space, as
 * createTikTokStyleCaptions() expects), with a page break after each line, after phrase-ending punctuation, and
 * before a word that would take the page past `maxChars`.
 */
export function toCaptions(timing: TimingJson, settings: Pick<CaptionsSettings, "lines" | "maxChars">): Caption[] {
  const maxChars = settings.maxChars ?? 24;
  const lines = timing.lines.filter((l) => !settings.lines || settings.lines.includes(l.id));
  const out: Caption[] = [];
  for (const line of lines) {
    // Phrases: up to phrase-ending punctuation or the line's end; each split into pages that fit.
    let phrase: TimingJson["lines"][number]["words"] = [];
    line.words.forEach((w, i) => {
      phrase.push(w);
      if (i < line.words.length - 1 && !PHRASE_END.test(w.word.trim())) return;
      let at = 0;
      for (const size of splitPhrase(phrase.map((x) => x.word.trim()), maxChars)) {
        phrase.slice(at, at + size).forEach((x, j) => {
          const text = x.word.trim();
          out.push({
            text: out.length ? ` ${text}` : text,
            startMs: Math.round(x.start * 1000),
            endMs: Math.round(x.end * 1000),
            timestampMs: Math.round(((x.start + x.end) / 2) * 1000),
            confidence: x.p ?? null,
            ...(j === size - 1 ? { pageBreakAfter: true } : {}),
          });
        });
        at += size;
      }
      phrase = [];
    });
  }
  return out;
}

/** A page's last part shorter than this takes a word from the one before (no lone "llegar." on a page). */
const MIN_TAIL = 10;

/**
 * How many words go on each page of one phrase: as many as fit in `maxChars` (one word per page at least), then a
 * short last page borrows words from the one before while they still fit.
 */
export function splitPhrase(words: string[], maxChars: number): number[] {
  const sizes: number[] = [];
  let length = 0;
  for (const w of words) {
    if (sizes.length && length + 1 + w.length <= maxChars) {
      sizes[sizes.length - 1]++;
      length += 1 + w.length;
    } else {
      sizes.push(1);
      length = w.length;
    }
  }
  const chars = (from: number, n: number) => words.slice(from, from + n).join(" ").length;
  while (sizes.length > 1) {
    const last = sizes.length - 1;
    const start = sizes.slice(0, last).reduce((a, b) => a + b, 0);
    if (sizes[last - 1] < 2 || chars(start, sizes[last]) >= MIN_TAIL || chars(start - 1, sizes[last] + 1) > maxChars) break;
    sizes[last - 1]--;
    sizes[last]++;
  }
  return sizes;
}

/**
 * The pages to show: createTikTokStyleCaptions() over toCaptions(), each ending `HOLD_MS` after its last word or
 * when the next one starts, its tokens marked for emphasis ("minimal").
 */
export function captionPages(timing: TimingJson, settings: CaptionsSettings): CaptionPage[] {
  const { pages } = createTikTokStyleCaptions({
    captions: toCaptions(timing, settings),
    combineTokensWithinMilliseconds: 60_000, // pages break only where toCaptions() and the silences say
    breakOnSilenceAfterMilliseconds: SILENCE_MS,
  });
  const emphasis = new Set((settings.emphasis ?? []).map(plain));
  return pages.map((page, i) => {
    const tokens = page.tokens.map((t) => ({
      text: t.text.trim(),
      fromMs: t.fromMs,
      toMs: t.toMs,
      emphasis: settings.style === "minimal" && emphasis.has(plain(t.text)),
    }));
    const last = tokens[tokens.length - 1]?.toMs ?? page.startMs;
    const next = pages[i + 1]?.startMs ?? Infinity;
    return { text: page.text.trim(), startMs: page.startMs, endMs: Math.min(next, last + HOLD_MS), tokens };
  });
}

/** A page shows from this long before its first word (and a word lights this long before it's said, ~2 frames, as
 * the kit's kinetic type arrives). */
export const CAPTION_LEAD_MS = 70;
/** Pages closer than this share the card: no fade between them, the earlier one stays up through the gap. */
export const CAPTION_RUN_GAP_MS = 250;

/** The page on screen at `ms` (shown from `CAPTION_LEAD_MS` before its first word), or null. */
export function pageAt(pages: CaptionPage[], ms: number): CaptionPage | null {
  return pages.find((p) => ms >= p.startMs - CAPTION_LEAD_MS && ms < p.endMs) ?? null;
}

export type CaptionRun = { startMs: number; endMs: number; pages: CaptionPage[] };

/** Pages grouped into runs that share one card (gaps under `CAPTION_RUN_GAP_MS`). */
export function captionRuns(pages: CaptionPage[]): CaptionRun[] {
  const runs: CaptionRun[] = [];
  for (const p of pages) {
    const last = runs[runs.length - 1];
    if (last && p.startMs - last.endMs < CAPTION_RUN_GAP_MS) {
      last.endMs = p.endMs;
      last.pages.push(p);
    } else runs.push({ startMs: p.startMs, endMs: p.endMs, pages: [p] });
  }
  return runs;
}

const unit = (x: number) => Math.min(1, Math.max(0, x));

/**
 * What the card shows at `ms`: a page and the card's opacity, or null. The card fades in over `fadeMs`, ending when the
 * run's first page shows (`CAPTION_LEAD_MS` before its first word), and out over `fadeMs` after the run's last page
 * ends. While it fades, and in the short gaps inside a run, it keeps the nearest page: the first one fading in, the
 * last one shown after that.
 */
export function captionAt(
  pages: CaptionPage[],
  ms: number,
  fadeMs: number,
): { page: CaptionPage; opacity: number } | null {
  const run = captionRuns(pages).find((r) => ms >= r.startMs - CAPTION_LEAD_MS - fadeMs && ms < r.endMs + fadeMs);
  if (!run) return null;
  const fadeIn = fadeMs > 0 ? unit((ms - (run.startMs - CAPTION_LEAD_MS - fadeMs)) / fadeMs) : 1;
  const fadeOut = fadeMs > 0 ? unit((run.endMs + fadeMs - ms) / fadeMs) : 1;
  const opacity = Math.min(fadeIn, fadeOut);
  if (opacity <= 0) return null;
  const shown = run.pages.filter((p) => ms >= p.startMs - CAPTION_LEAD_MS);
  return { page: shown[shown.length - 1] ?? run.pages[0], opacity };
}

/** The token being said at `ms` ("kinetic"): from its start until the next token starts (or the page ends). */
export function currentToken(page: CaptionPage, ms: number): number {
  let current = -1;
  page.tokens.forEach((t, i) => {
    if (ms >= t.fromMs) current = i;
  });
  return current;
}

/** A composition's format when the video doesn't say: a Reel when its id ends with "-reel" ("teaser-v2-reel"). */
export const formatOf = (compositionId: string): "story" | "reel" =>
  compositionId.endsWith("-reel") ? "reel" : "story";

/** Whether a deliverable (a composition id ends with it: "teaser-v2-reel") shows captions. */
export function captionsOn(settings: CaptionsSettings | undefined, compositionId: string): boolean {
  if (!settings) return false;
  return !settings.deliverables || settings.deliverables.some((d) => compositionId.endsWith(`-${d}`));
}
