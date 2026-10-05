// Animation follows the voice: tools/timing.py writes each video's data/timing.json (line and word times in video
// seconds, from the joined TTS lines and a local Whisper pass), and these helpers look times up by line id and word.
import { plain } from "./words.ts";

export type TimedWord = { word: string; start: number; end: number; p?: number };
export type TimedLine = { id: string; text: string; start: number; end: number; words: TimedWord[] };
export type TimingJson = { duration: number; lead: number; lines: TimedLine[] };

export function makeTiming(timing: TimingJson) {
  const lines = timing.lines;
  function line(id: string): TimedLine {
    const found = lines.find((l) => l.id === id);
    if (!found) throw new Error(`no line ${id}`);
    return found;
  }
  /** Start (video seconds) of the nth occurrence of `w` in line `id` (accents and punctuation ignored). */
  function word(id: string, w: string, nth = 0): number {
    const hits = line(id).words.filter((x) => plain(x.word) === plain(w));
    if (!hits[nth]) throw new Error(`no word "${w}" in ${id}`);
    return hits[nth].start;
  }
  return { line, word, duration: timing.duration, lead: timing.lead };
}
